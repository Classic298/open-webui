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

# Keyset page size for the chat scan. Each page is fully drained with
# .fetchall() so no server-side cursor stays open across pages; earlier
# migrations that used yield_per held one cursor for the full run and
# OOM'd large PG deployments.
CHAT_PAGE_SIZE = 1000

# Hard cap on rows per bulk INSERT, so a page with many tags per chat can't
# push past Postgres' 65,535 bind-parameter ceiling. chat_tag has 3 cols, tag
# has 4; 5000 rows = 20,000 binds, well under the ceiling.
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
    """Bulk INSERT that skips duplicate-key conflicts. PG and SQLite only.

    Both dialects scope the skip to the given conflict columns, so a real
    integrity error on an unrelated constraint still surfaces.
    """
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
    op.create_index('chat_tag_user_tag_idx', 'chat_tag', ['user_id', 'tag_id'])
    op.create_index('chat_tag_chat_idx', 'chat_tag', ['chat_id'])

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
    chat_tag_rows_queued = 0
    tag_rows_queued = 0
    next_log_threshold = LOG_EVERY_CHATS

    while True:
        page_stmt = sa.select(chat.c.id, chat.c.user_id, chat.c.meta).order_by(chat.c.id)
        if last_chat_id is not None:
            page_stmt = page_stmt.where(chat.c.id > last_chat_id)
        page_stmt = page_stmt.limit(CHAT_PAGE_SIZE)

        chat_rows = conn.execute(page_stmt).fetchall()
        if not chat_rows:
            break

        # First raw display name seen per (tag_id, user_id) wins the name on
        # any newly-created tag row. Deterministic per run (iteration is in
        # chat.id order) but arbitrary across runs if the same tag appears
        # under multiple casings. Pre-existing tag rows are never overwritten.
        display_name_by_tag_key: dict[tuple[str, str], str] = {}
        chat_tag_payload: list[dict] = []

        for chat_row in chat_rows:
            meta = chat_row.meta
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
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
            # regardless of how many distinct users it spans. Both PG and
            # SQLite >= 3.15 support row-value IN.
            tag_keys = list(display_name_by_tag_key.keys())
            existing_tag_keys: set[tuple[str, str]] = set()
            existing_stmt = sa.select(tag.c.id, tag.c.user_id).where(
                sa.tuple_(tag.c.id, tag.c.user_id).in_(tag_keys)
            )
            for existing_row in conn.execute(existing_stmt).fetchall():
                existing_tag_keys.add((existing_row.id, existing_row.user_id))

            new_tag_rows = [
                {'id': tid, 'name': raw_name, 'user_id': uid, 'meta': None}
                for (tid, uid), raw_name in display_name_by_tag_key.items()
                if (tid, uid) not in existing_tag_keys
            ]
            if new_tag_rows:
                _bulk_insert_skip_conflicts(conn, tag, new_tag_rows, conflict_cols=['id', 'user_id'])
                tag_rows_queued += len(new_tag_rows)

        if chat_tag_payload:
            deduped_chat_tag_rows = list(
                {
                    (r['chat_id'], r['tag_id'], r['user_id']): r
                    for r in chat_tag_payload
                }.values()
            )
            _bulk_insert_skip_conflicts(
                conn, chat_tag, deduped_chat_tag_rows,
                conflict_cols=['chat_id', 'tag_id', 'user_id'],
            )
            chat_tag_rows_queued += len(deduped_chat_tag_rows)

        last_chat_id = chat_rows[-1].id
        chats_processed += len(chat_rows)

        if chats_processed >= next_log_threshold:
            log.info(
                f'chat_tag backfill progress: {chats_processed} chats processed, '
                f'{chat_tag_rows_queued} associations queued, '
                f'{tag_rows_queued} tags queued, last_chat_id={last_chat_id}'
            )
            next_log_threshold += LOG_EVERY_CHATS

    log.info(
        f'chat_tag backfill complete: {chats_processed} chats processed, '
        f'{chat_tag_rows_queued} associations queued, {tag_rows_queued} tags queued'
    )


def downgrade() -> None:
    # TODO(chat-tag-meta-dropped): this downgrade relies on chat.meta['tags']
    # still being dual-written. When a future migration drops those writes,
    # this function must serialize chat_tag rows back into meta before the
    # drop - or refuse to run.
    op.drop_index('chat_tag_chat_idx', table_name='chat_tag')
    op.drop_index('chat_tag_user_tag_idx', table_name='chat_tag')
    op.drop_table('chat_tag')
