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

# Per-INSERT row cap (ceiling guard). Postgres limits a statement to 65,535
# bind parameters; a page with many tags per chat could in theory push past
# that. Realistic workloads stay far below 5000 rows per page, so this is
# defensive - chunked execution only kicks in on degenerate inputs.
INSERT_BATCH_ROWS = 5000

LOG_EVERY_CHATS = 50_000


def _normalize_tag_id(raw: str) -> str:
    # Duplicated from open_webui.models.tags.normalize_tag_id; migrations must
    # be self-contained (models evolve independently). Keep in sync.
    return raw.replace(' ', '_').lower()


def _chunked(source: Iterable, size: int) -> Iterable[list]:
    it = iter(source)
    while True:
        batch = list(islice(it, size))
        if not batch:
            return
        yield batch


def _bulk_insert_on_conflict_nothing(conn, table, rows, index_elements):
    """Bulk INSERT ... ON CONFLICT DO NOTHING. PG and SQLite only."""
    if not rows:
        return
    dialect = conn.dialect.name
    for batch in _chunked(rows, INSERT_BATCH_ROWS):
        if dialect == 'postgresql':
            stmt = postgresql.insert(table).values(batch).on_conflict_do_nothing(index_elements=index_elements)
        elif dialect == 'sqlite':
            stmt = sqlite.insert(table).values(batch).on_conflict_do_nothing(index_elements=index_elements)
        else:
            raise NotImplementedError(
                f'_bulk_insert_on_conflict_nothing: unsupported dialect {dialect!r}; only postgresql and sqlite are supported'
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
    meta_rows_stripped = 0
    next_log_threshold = 0  # log the first page unconditionally

    strip_meta_update = (
        sa.update(chat)
        .where(chat.c.id == sa.bindparam('target_chat_id'))
        .values(meta=sa.bindparam('new_meta'))
    )

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
        meta_strip_payload: list[dict] = []

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
                # Still strip the 'tags' key if present but empty/malformed,
                # so meta is consistently tag-free post-upgrade.
                if 'tags' in meta:
                    stripped_meta = {k: v for k, v in meta.items() if k != 'tags'}
                    meta_strip_payload.append(
                        {'target_chat_id': chat_row.id, 'new_meta': stripped_meta}
                    )
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

            stripped_meta = {k: v for k, v in meta.items() if k != 'tags'}
            meta_strip_payload.append(
                {'target_chat_id': chat_row.id, 'new_meta': stripped_meta}
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
                {'id': tid, 'name': raw_name, 'user_id': uid}
                for (tid, uid), raw_name in display_name_by_tag_key.items()
                if (tid, uid) not in existing_tag_keys
            ]
            if new_tag_rows:
                _bulk_insert_on_conflict_nothing(conn, tag, new_tag_rows, index_elements=['id', 'user_id'])
                tag_rows_inserted += len(new_tag_rows)

        if chat_tag_payload:
            _bulk_insert_on_conflict_nothing(
                conn, chat_tag, chat_tag_payload,
                index_elements=['chat_id', 'tag_id', 'user_id'],
            )
            chat_tag_rows_inserted += len(chat_tag_payload)

        if meta_strip_payload:
            # Paginated executemany avoids a single full-table UPDATE that
            # would hold write locks and bloat WAL on large deployments.
            # (Also: meta is sa.JSON, so the PG json - 'tags' operator
            # isn't available without a jsonb cast.)
            conn.execute(strip_meta_update, meta_strip_payload)
            meta_rows_stripped += len(meta_strip_payload)

        last_chat_id = chat_rows[-1].id
        chats_processed += len(chat_rows)

        if chats_processed >= next_log_threshold:
            log.info(
                f'chat_tag backfill progress: {chats_processed} chats processed, '
                f'{chat_tag_rows_inserted} associations inserted, '
                f'{tag_rows_inserted} tags inserted, '
                f'{meta_rows_stripped} meta rows stripped, last_chat_id={last_chat_id}'
            )
            next_log_threshold = chats_processed + LOG_EVERY_CHATS

    log.info(
        f'chat_tag backfill complete: {chats_processed} chats processed, '
        f'{chat_tag_rows_inserted} associations inserted, {tag_rows_inserted} tags inserted, '
        f'{meta_rows_stripped} meta rows stripped'
    )

    # chat_id-only lookups are covered by the PK's leading column.
    op.create_index('chat_tag_user_tag_idx', 'chat_tag', ['user_id', 'tag_id'])


def downgrade() -> None:
    # Post-upgrade the app stops writing meta['tags'], so we must reserialize
    # chat_tag back into meta before the drop or lose every post-upgrade tag.
    # Lossy for display casing: the reserialized tag list uses the normalized
    # tag_id, not the original tag.name. Round-tripping upgrade -> downgrade
    # on already-normalized data is a no-op; original user casings only
    # survive re-running upgrade (which reads from tag.name).
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
            tag_ids = tag_ids_by_chat_id[chat_id]
            existing_meta = existing_meta_by_chat_id.get(chat_id)
            if isinstance(existing_meta, str):
                try:
                    existing_meta = json.loads(existing_meta)
                except (TypeError, ValueError):
                    existing_meta = {}
            if not isinstance(existing_meta, dict):
                existing_meta = {}
            # Skip chats that had no tags pre-upgrade and still have none:
            # don't grow their meta with an empty 'tags' key.
            if not tag_ids and 'tags' not in existing_meta:
                continue
            merged_meta = {**existing_meta, 'tags': tag_ids}
            update_params.append({'target_chat_id': chat_id, 'new_meta': merged_meta})

        if update_params:
            conn.execute(bulk_update, update_params)
            chats_rewritten += len(update_params)

        last_chat_id = chat_ids_in_page[-1]

    log.info(f'chat_tag downgrade: serialized tags back into meta for {chats_rewritten} chats')

    op.drop_index('chat_tag_user_tag_idx', table_name='chat_tag')
    op.drop_table('chat_tag')
