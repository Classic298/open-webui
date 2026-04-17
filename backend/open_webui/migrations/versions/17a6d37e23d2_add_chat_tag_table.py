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

# Keyset page size for the chat scan. Each page is drained with .fetchall()
# so no server-side cursor stays open across pages.
CHAT_PAGE_SIZE = 1000

# Cap rows per bulk INSERT so a page with many tags per chat can't push past
# Postgres' 65,535 bind-parameter limit. chat_tag has 3 cols, tag has 4;
# 5000 rows = 20,000 binds, well under the ceiling.
INSERT_BATCH_ROWS = 5000

LOG_EVERY_CHATS = 50_000


def _normalize_tag_id(raw: str) -> str:
    return raw.replace(' ', '_').lower()


def _chunked(seq: Sequence, size: int) -> Iterable[list]:
    it = iter(seq)
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
    # Single secondary index covers the "list chats for this tag" path.
    # A chat_id-only index would be redundant with the PK's leading column.
    op.create_index('chat_tag_user_tag_idx', 'chat_tag', ['user_id', 'tag_id'])

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

        # First raw display name seen per (tag_id, user_id) wins the name on
        # any newly-created tag row. Pre-existing tag rows are never overwritten.
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
            # One tuple-IN query covers every (tag_id, user_id) in the page,
            # regardless of how many distinct users it spans. PG and SQLite
            # 3.15+ both support row-value IN.
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


def downgrade() -> None:
    # Serialize chat_tag rows back into chat.meta['tags'] before dropping the
    # table. Post-upgrade the app stops writing meta['tags'], so skipping this
    # step would silently discard every tag associated after the upgrade ran.
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
        sa.column('user_id', sa.String()),
    )

    last_chat_id: Union[str, None] = None
    chats_rewritten = 0

    while True:
        tag_ids_by_chat_query = (
            sa.select(chat_tag.c.chat_id, chat_tag.c.tag_id)
            .order_by(chat_tag.c.chat_id)
        )
        if last_chat_id is not None:
            tag_ids_by_chat_query = tag_ids_by_chat_query.where(chat_tag.c.chat_id > last_chat_id)
        # Pull tags for up to CHAT_PAGE_SIZE chats per iteration. Rows come
        # grouped by chat_id because of the ORDER BY.
        tag_ids_by_chat_query = tag_ids_by_chat_query.limit(CHAT_PAGE_SIZE * 50)
        rows = conn.execute(tag_ids_by_chat_query).fetchall()
        if not rows:
            break

        tag_ids_by_chat_id: dict[str, list[str]] = {}
        for row in rows:
            tag_ids_by_chat_id.setdefault(row.chat_id, []).append(row.tag_id)

        # Only the first CHAT_PAGE_SIZE chat_ids in the batch are guaranteed
        # to have their complete tag list - the last chat_id in `rows` may
        # have been truncated mid-way. Write the completed ones, keep the
        # last chat_id's tags for the next iteration by excluding it here
        # and using `> chat_id` as the next cursor.
        chat_ids_in_order = list(tag_ids_by_chat_id.keys())
        if len(chat_ids_in_order) > 1:
            complete_chat_ids = chat_ids_in_order[:-1]
            next_cursor = complete_chat_ids[-1]
        else:
            complete_chat_ids = chat_ids_in_order
            next_cursor = chat_ids_in_order[-1]

        for chat_id in complete_chat_ids:
            tag_ids = tag_ids_by_chat_id[chat_id]
            existing_meta_row = conn.execute(
                sa.select(chat.c.meta).where(chat.c.id == chat_id)
            ).first()
            if existing_meta_row is None:
                continue
            existing_meta = existing_meta_row.meta
            if isinstance(existing_meta, str):
                try:
                    existing_meta = json.loads(existing_meta)
                except (TypeError, ValueError):
                    existing_meta = {}
            if not isinstance(existing_meta, dict):
                existing_meta = {}
            merged_meta = {**existing_meta, 'tags': tag_ids}
            conn.execute(
                sa.update(chat).where(chat.c.id == chat_id).values(meta=merged_meta)
            )
            chats_rewritten += 1

        last_chat_id = next_cursor

    log.info(f'chat_tag downgrade: serialized tags back into meta for {chats_rewritten} chats')

    op.drop_index('chat_tag_user_tag_idx', table_name='chat_tag')
    op.drop_table('chat_tag')
