"""Add chat_tag table

Revision ID: 17a6d37e23d2
Revises: e1f2a3b4c5d6
Create Date: 2026-04-17 00:00:00.000000

"""

import json
import logging
from itertools import islice
from typing import Iterable, Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite

log = logging.getLogger(__name__)

revision: str = '17a6d37e23d2'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Pages are drained with .fetchall() so no server-side cursor stays open
# across pages (large PG deployments OOM'd on yield_per in prior migrations).
CHAT_PAGE_SIZE = 1000

# Per-INSERT row cap. Postgres limits a statement to 65,535 bind parameters,
# and a chat page with many tags per chat can push the flattened payload past
# it. 5000 rows stays comfortably under the ceiling at our widest table
# (tag has 4 cols = 20,000 binds).
INSERT_BATCH_ROWS = 5000

LOG_EVERY_CHATS = 50_000


def _normalize_tag_id(raw: str) -> str:
    return raw.replace(' ', '_').lower()


def _chunked(source: Iterable, size: int) -> Iterable[list]:
    it = iter(source)
    while True:
        batch = list(islice(it, size))
        if not batch:
            return
        yield batch


def _bulk_insert_skip_conflicts(conn, table, rows, conflict_cols):
    """Bulk INSERT that skips duplicate-key conflicts. PG and SQLite only."""
    if not rows:
        return
    dialect = conn.dialect.name
    for batch in _chunked(rows, INSERT_BATCH_ROWS):
        if dialect == 'postgresql':
            stmt = postgresql.insert(table).values(batch).on_conflict_do_nothing(index_elements=conflict_cols)
        elif dialect == 'sqlite':
            stmt = sqlite.insert(table).values(batch).on_conflict_do_nothing(index_elements=conflict_cols)
        else:
            raise NotImplementedError(
                f'chat_tag backfill: unsupported dialect {dialect!r}; only postgresql and sqlite are supported'
            )
        conn.execute(stmt)


def upgrade() -> None:
    op.create_table(
        'chat_tag',
        sa.Column('chat_id', sa.String(), nullable=False),
        sa.Column('tag_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('chat_id', 'tag_id', 'user_id', name='pk_chat_tag'),
        sa.ForeignKeyConstraint(
            ['chat_id'],
            ['chat.id'],
            name='fk_chat_tag_chat_id',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['tag_id', 'user_id'],
            ['tag.id', 'tag.user_id'],
            name='fk_chat_tag_tag',
            ondelete='CASCADE',
        ),
    )

    conn = op.get_bind()

    chat = sa.table(
        'chat',
        sa.column('id', sa.String()),
        sa.column('user_id', sa.String()),
        sa.column('meta', sa.JSON()),
    )
    tag = sa.table(
        'tag',
        sa.column('id', sa.String()),
        sa.column('name', sa.String()),
        sa.column('user_id', sa.String()),
        sa.column('meta', sa.JSON()),
    )
    chat_tag = sa.table(
        'chat_tag',
        sa.column('chat_id', sa.String()),
        sa.column('tag_id', sa.String()),
        sa.column('user_id', sa.String()),
    )

    last_chat_id: Union[str, None] = None
    chats_processed = 0
    chat_tag_rows_inserted = 0
    tag_rows_inserted = 0
    next_log_threshold = LOG_EVERY_CHATS

    while True:
        chat_page_query = sa.select(chat.c.id, chat.c.user_id, chat.c.meta).order_by(chat.c.id)
        if last_chat_id is not None:
            chat_page_query = chat_page_query.where(chat.c.id > last_chat_id)
        chat_page_query = chat_page_query.limit(CHAT_PAGE_SIZE)

        chat_rows = conn.execute(chat_page_query).fetchall()
        if not chat_rows:
            break

        # First raw display name seen per (tag_id, user_id) wins for new rows;
        # pre-existing tag rows are never overwritten.
        display_name_by_tag_key: dict[tuple[str, str], str] = {}
        chat_tag_payload: list[dict] = []

        for chat_row in chat_rows:
            meta = chat_row.meta
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (TypeError, ValueError):
                    meta = None
            if not isinstance(meta, dict):
                continue

            raw_tag_names = meta.get('tags')
            if not isinstance(raw_tag_names, list) or not raw_tag_names:
                continue

            seen_tag_ids_in_chat: set[str] = set()
            for raw_tag_name in raw_tag_names:
                if not isinstance(raw_tag_name, str):
                    continue
                tag_id = _normalize_tag_id(raw_tag_name)
                if not tag_id or tag_id in seen_tag_ids_in_chat:
                    continue
                seen_tag_ids_in_chat.add(tag_id)

                display_name_by_tag_key.setdefault((tag_id, chat_row.user_id), raw_tag_name)
                chat_tag_payload.append(
                    {'chat_id': chat_row.id, 'tag_id': tag_id, 'user_id': chat_row.user_id}
                )

        if display_name_by_tag_key:
            # Row-value IN works on PG and SQLite >= 3.15.
            tag_keys = list(display_name_by_tag_key.keys())
            existing_tag_keys: set[tuple[str, str]] = set()
            existing_tag_query = sa.select(tag.c.id, tag.c.user_id).where(
                sa.tuple_(tag.c.id, tag.c.user_id).in_(tag_keys)
            )
            for existing_row in conn.execute(existing_tag_query).fetchall():
                existing_tag_keys.add((existing_row.id, existing_row.user_id))

            new_tag_rows = [
                {'id': tid, 'name': raw_name, 'user_id': uid, 'meta': None}
                for (tid, uid), raw_name in display_name_by_tag_key.items()
                if (tid, uid) not in existing_tag_keys
            ]
            if new_tag_rows:
                _bulk_insert_skip_conflicts(conn, tag, new_tag_rows, conflict_cols=['id', 'user_id'])
                tag_rows_inserted += len(new_tag_rows)

        if chat_tag_payload:
            _bulk_insert_skip_conflicts(
                conn, chat_tag, chat_tag_payload,
                conflict_cols=['chat_id', 'tag_id', 'user_id'],
            )
            chat_tag_rows_inserted += len(chat_tag_payload)

        last_chat_id = chat_rows[-1].id
        chats_processed += len(chat_rows)

        if chats_processed >= next_log_threshold:
            log.info(
                f'chat_tag backfill progress: {chats_processed} chats processed, '
                f'{chat_tag_rows_inserted} associations inserted, '
                f'{tag_rows_inserted} tags inserted, last_chat_id={last_chat_id}'
            )
            next_log_threshold += LOG_EVERY_CHATS

    log.info(
        f'chat_tag backfill complete: {chats_processed} chats processed, '
        f'{chat_tag_rows_inserted} associations inserted, {tag_rows_inserted} tags inserted'
    )

    # chat_id-only lookups are covered by the PK's leading column.
    op.create_index('chat_tag_user_tag_idx', 'chat_tag', ['user_id', 'tag_id'])

    # Strip meta['tags'] now that chat_tag is the source of truth - otherwise
    # ChatModel responses would leak the stale JSON tag list. Downgrade
    # rebuilds meta['tags'] from chat_tag.
    dialect = conn.dialect.name
    if dialect == 'postgresql':
        conn.execute(sa.text(
            "UPDATE chat SET meta = meta - 'tags' WHERE meta ? 'tags'"
        ))
    elif dialect == 'sqlite':
        conn.execute(sa.text(
            "UPDATE chat SET meta = json_remove(meta, '$.tags') "
            "WHERE json_extract(meta, '$.tags') IS NOT NULL"
        ))
    else:
        raise NotImplementedError(
            f'chat_tag migration: unsupported dialect {dialect!r}'
        )


def downgrade() -> None:
    # Post-upgrade the app stops writing meta['tags'], so we must reserialize
    # chat_tag back into meta before the drop or lose every post-upgrade tag.
    conn = op.get_bind()

    chat = sa.table(
        'chat',
        sa.column('id', sa.String()),
        sa.column('meta', sa.JSON()),
    )
    chat_tag = sa.table(
        'chat_tag',
        sa.column('chat_id', sa.String()),
        sa.column('tag_id', sa.String()),
    )

    last_chat_id: Union[str, None] = None
    chats_rewritten = 0
    bulk_update = (
        sa.update(chat)
        .where(chat.c.id == sa.bindparam('target_chat_id'))
        .values(meta=sa.bindparam('new_meta'))
    )

    # Paginate by chat.id so a single heavily-tagged chat can never span
    # page boundaries (avoids the "truncated tag list" edge case).
    while True:
        chat_page_query = sa.select(chat.c.id, chat.c.meta).order_by(chat.c.id)
        if last_chat_id is not None:
            chat_page_query = chat_page_query.where(chat.c.id > last_chat_id)
        chat_page_query = chat_page_query.limit(CHAT_PAGE_SIZE)

        page_rows = conn.execute(chat_page_query).fetchall()
        if not page_rows:
            break

        chat_ids_in_page = [row.id for row in page_rows]
        existing_meta_by_chat_id = {row.id: row.meta for row in page_rows}

        tag_rows = conn.execute(
            sa.select(chat_tag.c.chat_id, chat_tag.c.tag_id).where(
                chat_tag.c.chat_id.in_(chat_ids_in_page)
            )
        ).fetchall()
        tag_ids_by_chat_id: dict[str, list[str]] = {cid: [] for cid in chat_ids_in_page}
        for tag_row in tag_rows:
            tag_ids_by_chat_id[tag_row.chat_id].append(tag_row.tag_id)

        update_params = []
        for chat_id in chat_ids_in_page:
            existing_meta = existing_meta_by_chat_id.get(chat_id)
            if isinstance(existing_meta, str):
                try:
                    existing_meta = json.loads(existing_meta)
                except (TypeError, ValueError):
                    existing_meta = {}
            if not isinstance(existing_meta, dict):
                existing_meta = {}
            merged_meta = {**existing_meta, 'tags': tag_ids_by_chat_id[chat_id]}
            update_params.append({'target_chat_id': chat_id, 'new_meta': merged_meta})

        if update_params:
            conn.execute(bulk_update, update_params)
            chats_rewritten += len(update_params)

        last_chat_id = chat_ids_in_page[-1]

    log.info(f'chat_tag downgrade: serialized tags back into meta for {chats_rewritten} chats')

    op.drop_index('chat_tag_user_tag_idx', table_name='chat_tag')
    op.drop_table('chat_tag')
