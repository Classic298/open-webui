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

log = logging.getLogger(__name__)

revision: str = '17a6d37e23d2'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Keyset chunk size. Each chunk is fully materialized with .fetchall() before
# the next query runs, so no server-side cursor stays open across chunks.
# This avoids the OOM / cursor-timeout failures seen on very large Postgres
# deployments when earlier migrations used yield_per streaming.
CHUNK_SIZE = 1000
LOG_EVERY = 50_000


def _normalize_tag_id(raw: str) -> str:
    return raw.replace(' ', '_').lower()


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
    assoc_inserted = 0
    tags_created = 0

    while True:
        stmt = sa.select(chat.c.id, chat.c.user_id, chat.c.meta).order_by(chat.c.id)
        if last_id is not None:
            stmt = stmt.where(chat.c.id > last_id)
        stmt = stmt.limit(CHUNK_SIZE)

        # .fetchall() fully materializes and releases the cursor immediately.
        # Do NOT switch to yield_per / stream_results here - holding a single
        # server-side cursor open across a long backfill has caused OOM /
        # connection resets on large PostgreSQL deployments.
        rows = conn.execute(stmt).fetchall()
        if not rows:
            break

        known_tags_this_chunk: set = set()

        for row in rows:
            chat_id = row.id
            user_id = row.user_id
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
            for raw in tag_names:
                if not isinstance(raw, str):
                    continue
                tag_id = _normalize_tag_id(raw)
                if not tag_id or tag_id in seen_in_chat:
                    continue
                seen_in_chat.add(tag_id)

                tag_key = (tag_id, user_id)
                if tag_key not in known_tags_this_chunk:
                    sp = conn.begin_nested()
                    try:
                        exists = conn.execute(
                            sa.select(tag.c.id).where(
                                tag.c.id == tag_id,
                                tag.c.user_id == user_id,
                            )
                        ).first()
                        if exists is None:
                            conn.execute(
                                sa.insert(tag).values(
                                    id=tag_id,
                                    name=tag_id,
                                    user_id=user_id,
                                    meta=None,
                                )
                            )
                            tags_created += 1
                        sp.commit()
                        known_tags_this_chunk.add(tag_key)
                    except Exception as e:
                        sp.rollback()
                        log.warning(
                            f'chat_tag backfill: ensure tag failed for ({tag_id}, {user_id}): {e}'
                        )
                        continue

                sp = conn.begin_nested()
                try:
                    conn.execute(
                        sa.insert(chat_tag).values(
                            chat_id=chat_id,
                            tag_id=tag_id,
                            user_id=user_id,
                        )
                    )
                    sp.commit()
                    assoc_inserted += 1
                except Exception:
                    # Duplicate PK on re-run is expected and tolerated.
                    sp.rollback()

        last_id = rows[-1].id
        processed += len(rows)

        if processed // LOG_EVERY != (processed - len(rows)) // LOG_EVERY:
            log.info(
                f'chat_tag backfill progress: {processed} chats processed, '
                f'{assoc_inserted} associations inserted, {tags_created} tags created, '
                f'last_id={last_id}'
            )

    log.info(
        f'chat_tag backfill complete: {processed} chats processed, '
        f'{assoc_inserted} associations inserted, {tags_created} tags created'
    )


def downgrade() -> None:
    op.drop_index('chat_tag_chat_idx', table_name='chat_tag')
    op.drop_index('chat_tag_user_tag_idx', table_name='chat_tag')
    op.drop_table('chat_tag')
