"""Add chat_tag table

Revision ID: 17a6d37e23d2
Revises: e1f2a3b4c5d6
Create Date: 2026-04-17 00:00:00.000000

"""

import json
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite

log = logging.getLogger(__name__)

revision: str = '17a6d37e23d2'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Keyset chunk size. Each chunk is fully materialized with .fetchall() and the
# associated INSERTs run as bulk dialect-specific upserts, so no server-side
# cursor stays open across chunks. Earlier migrations that used yield_per
# streaming held a single cursor for the full run, which caused OOM /
# connection resets on large PostgreSQL deployments.
#
# 1000 is a balance between round-trip overhead (too small) and per-chunk
# memory plus Postgres' ~32k bind-parameter limit on bulk INSERT (too large);
# at 3 columns per row that caps us well below the limit and keeps working
# memory bounded.
#
# Note for very large (>10M chat rows) deployments: this migration runs
# inside Alembic's default transaction, so the WAL write grows with row
# count. Run during a maintenance window, or split DDL from backfill by
# disabling transactional_ddl on this revision.
CHUNK_SIZE = 1000
LOG_EVERY = 50_000


def _normalize_tag_id(raw: str) -> str:
    return raw.replace(' ', '_').lower()


def _bulk_insert_ignore(conn, table, rows, conflict_cols):
    """Dialect-aware bulk INSERT that skips duplicate key conflicts.

    Postgres: INSERT ... ON CONFLICT (...) DO NOTHING.
    SQLite:   INSERT OR IGNORE.
    Other dialects are not supported - open-webui officially targets PG and
    SQLite only, and a savepoint fallback here would silently swallow real
    data-integrity errors alongside the intended duplicate-key skip.
    """
    if not rows:
        return
    dialect = conn.dialect.name
    if dialect == 'postgresql':
        stmt = postgresql.insert(table).values(rows).on_conflict_do_nothing(index_elements=conflict_cols)
        conn.execute(stmt)
    elif dialect == 'sqlite':
        stmt = sqlite.insert(table).values(rows).prefix_with('OR IGNORE')
        conn.execute(stmt)
    else:
        raise NotImplementedError(
            f'chat_tag backfill: unsupported dialect {dialect!r}; only postgresql and sqlite are supported'
        )


def upgrade() -> None:
    # Step 1: Create chat_tag table
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

    # Step 2: Backfill from chat.meta['tags']
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

    last_id: Union[str, None] = None
    processed = 0
    assoc_queued = 0
    tags_queued = 0
    next_log_at = LOG_EVERY

    while True:
        stmt = sa.select(chat.c.id, chat.c.user_id, chat.c.meta).order_by(chat.c.id)
        if last_id is not None:
            stmt = stmt.where(chat.c.id > last_id)
        stmt = stmt.limit(CHUNK_SIZE)

        # fetchall() fully materializes and releases the cursor immediately -
        # see note at top of file on why this matters for large PG deployments.
        rows = conn.execute(stmt).fetchall()
        if not rows:
            break

        # First raw display name seen per (tag_id, user_id) "wins" and becomes
        # the name on any newly-created tag row. Chunks iterate rows in
        # chat.id order, so the winner is deterministic but otherwise
        # arbitrary if the same tag exists under multiple casings across
        # different chats. Pre-existing tag rows are never overwritten.
        tag_display: dict[tuple[str, str], str] = {}
        assoc_rows: list[dict] = []

        for row in rows:
            meta = row.meta
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = None
            if not isinstance(meta, dict):
                continue

            tag_names = meta.get('tags')
            if not isinstance(tag_names, list) or not tag_names:
                continue

            seen_in_chat: set = set()
            for raw_tag_name in tag_names:
                if not isinstance(raw_tag_name, str):
                    continue
                tag_id = _normalize_tag_id(raw_tag_name)
                if not tag_id or tag_id in seen_in_chat:
                    continue
                seen_in_chat.add(tag_id)

                tag_display.setdefault((tag_id, row.user_id), raw_tag_name)
                assoc_rows.append(
                    {'chat_id': row.id, 'tag_id': tag_id, 'user_id': row.user_id}
                )

        # Bulk-create missing tag rows for this chunk with proper display names.
        if tag_display:
            keys = list(tag_display.keys())
            # One SELECT to find which (tag_id, user_id) pairs already exist.
            existing: set = set()
            # Parameterize via a VALUES / OR filter. Use a simple in-memory filter
            # on the smaller side: we have <= CHUNK_SIZE tag keys. Split by
            # user_id to keep predicates simple.
            by_user: dict = {}
            for tid, uid in keys:
                by_user.setdefault(uid, set()).add(tid)
            for uid, tids in by_user.items():
                res = conn.execute(
                    sa.select(tag.c.id, tag.c.user_id).where(
                        tag.c.user_id == uid,
                        tag.c.id.in_(tids),
                    )
                ).fetchall()
                for r in res:
                    existing.add((r.id, r.user_id))

            new_tag_rows = [
                {
                    'id': tid,
                    'name': raw_name,
                    'user_id': uid,
                    'meta': None,
                }
                for (tid, uid), raw_name in tag_display.items()
                if (tid, uid) not in existing
            ]
            if new_tag_rows:
                _bulk_insert_ignore(conn, tag, new_tag_rows, conflict_cols=['id', 'user_id'])
                tags_queued += len(new_tag_rows)

        # Bulk-insert chat_tag associations. Dedupe payload list first; duplicate
        # PK collisions (e.g. re-run after partial failure) are swallowed by the
        # dialect's conflict clause.
        if assoc_rows:
            unique_assocs = list(
                {(r['chat_id'], r['tag_id'], r['user_id']): r for r in assoc_rows}.values()
            )
            _bulk_insert_ignore(
                conn, chat_tag, unique_assocs, conflict_cols=['chat_id', 'tag_id', 'user_id']
            )
            assoc_queued += len(unique_assocs)

        last_id = rows[-1].id
        processed += len(rows)

        if processed >= next_log_at:
            log.info(
                f'chat_tag backfill progress: {processed} chats processed, '
                f'{assoc_queued} associations queued, {tags_queued} tags queued, '
                f'last_id={last_id}'
            )
            next_log_at += LOG_EVERY

    log.info(
        f'chat_tag backfill complete: {processed} chats processed, '
        f'{assoc_queued} associations queued, {tags_queued} tags queued'
    )


def downgrade() -> None:
    # NOTE: downgrade is only data-safe while chat.meta['tags'] is still being
    # dual-written by the model layer. If a future migration drops the meta
    # writes, update this downgrade to serialize chat_tag rows back into
    # chat.meta['tags'] before dropping the table.
    op.drop_index('chat_tag_chat_idx', table_name='chat_tag')
    op.drop_index('chat_tag_user_tag_idx', table_name='chat_tag')
    op.drop_table('chat_tag')
