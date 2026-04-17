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

# Per-statement bind-parameter budget per dialect. PG allows 65,535;
# SQLite < 3.32 (May 2020) caps at 999. Mirrors
# open_webui.internal.db._PG_MAX_BIND_PARAMS / _SQLITE_MAX_BIND_PARAMS.
_PG_MAX_BIND_PARAMS = 65_000
_SQLITE_MAX_BIND_PARAMS = 900


def _row_batch_size(dialect: str, cols_per_row: int) -> int:
    budget = _SQLITE_MAX_BIND_PARAMS if dialect == 'sqlite' else _PG_MAX_BIND_PARAMS
    return max(1, budget // max(1, cols_per_row))

LOG_EVERY_CHATS = 50_000


def _normalize_tag_id(raw: str) -> str:
    # Must stay in sync with open_webui.models.tags.normalize_tag_id.
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
    batch_size = _row_batch_size(dialect, cols_per_row=len(rows[0]))
    for batch in _chunked(rows, batch_size):
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
    dialect = op.get_bind().dialect.name
    if dialect not in ('postgresql', 'sqlite'):
        raise NotImplementedError(
            f'chat_tag migration: unsupported dialect {dialect!r}; only postgresql and sqlite are supported'
        )

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
    chat_tag_rows_submitted = 0
    tag_rows_submitted = 0
    meta_rows_stripped = 0
    next_log_threshold = 0  # log the first page unconditionally

    strip_meta_update = (
        sa.update(chat)
        .where(chat.c.id == sa.bindparam('target_chat_id'))
        .values(meta=sa.bindparam('new_meta', type_=sa.JSON()))
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

            # Shared-chat snapshots have user_id = 'shared-{orig_chat_id}' and
            # historically carried meta['tags'] as a byproduct of the JSON
            # blob copy. Don't promote those into real chat_tag / tag rows
            # under the synthetic user_id; just strip the key for consistency.
            is_shared_snapshot = isinstance(chat_row.user_id, str) and chat_row.user_id.startswith('shared-')

            raw_tag_names = meta.get('tags')
            if is_shared_snapshot or not isinstance(raw_tag_names, list) or not raw_tag_names:
                # Still strip the 'tags' key if present, so meta is
                # consistently tag-free post-upgrade.
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
                # 'none' is the search sentinel; don't promote it to a real association.
                if not tag_id or tag_id == 'none' or tag_id in seen_tag_ids_in_chat:
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
            # Row-value IN works on PG and SQLite >= 3.15. Chunked per dialect
            # to respect bind-param ceilings. The per-page reset of
            # display_name_by_tag_key is safe because the existing-tag filter
            # below skips (tag_id, user_id) pairs that already have a row,
            # so a different display name seen on a later page can't clobber
            # the first-seen name.
            tag_keys = list(display_name_by_tag_key.keys())
            existing_tag_keys: set[tuple[str, str]] = set()
            # tuple_(id, user_id) = 2 binds per row.
            key_batch_size = _row_batch_size(dialect, cols_per_row=2)
            for key_batch in _chunked(tag_keys, key_batch_size):
                existing_tag_query = sa.select(tag.c.id, tag.c.user_id).where(
                    sa.tuple_(tag.c.id, tag.c.user_id).in_(key_batch)
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
                tag_rows_submitted += len(new_tag_rows)

        if chat_tag_payload:
            _bulk_insert_on_conflict_nothing(
                conn, chat_tag, chat_tag_payload,
                index_elements=['chat_id', 'tag_id', 'user_id'],
            )
            chat_tag_rows_submitted += len(chat_tag_payload)

        if meta_strip_payload:
            # Paginated; a single full-table UPDATE holds write locks too long.
            # (Also: meta is sa.JSON, so PG's json - 'tags' needs a jsonb cast.)
            conn.execute(strip_meta_update, meta_strip_payload)
            meta_rows_stripped += len(meta_strip_payload)

        last_chat_id = chat_rows[-1].id
        chats_processed += len(chat_rows)

        if chats_processed >= next_log_threshold:
            log.info(
                f'chat_tag backfill progress: {chats_processed} chats processed, '
                f'{chat_tag_rows_submitted} associations submitted, '
                f'{tag_rows_submitted} tags submitted, '
                f'{meta_rows_stripped} meta rows stripped, last_chat_id={last_chat_id}'
            )
            next_log_threshold = chats_processed + LOG_EVERY_CHATS

    log.info(
        f'chat_tag backfill complete: {chats_processed} chats processed, '
        f'{chat_tag_rows_submitted} associations submitted, {tag_rows_submitted} tags submitted, '
        f'{meta_rows_stripped} meta rows stripped'
    )

    # Index built after backfill so bulk inserts don't pay index-maintenance
    # cost per row.
    op.create_index('chat_tag_user_tag_idx', 'chat_tag', ['user_id', 'tag_id'])


def downgrade() -> None:
    # Reserialize chat_tag into meta['tags'] before the drop (post-upgrade
    # writes only hit chat_tag). Joins tag to recover tag.name so a
    # round-trip upgrade -> downgrade preserves user-visible casing.
    # Still lossy on row order (no user-meaningful order survives chat_tag).
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect not in ('postgresql', 'sqlite'):
        raise NotImplementedError(
            f'chat_tag migration: unsupported dialect {dialect!r}; only postgresql and sqlite are supported'
        )

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
    )
    chat_tag = sa.table(
        'chat_tag',
        sa.column('chat_id', sa.String()),
        sa.column('tag_id', sa.String()),
        sa.column('user_id', sa.String()),
    )

    last_chat_id: Union[str, None] = None
    chats_rewritten = 0
    bulk_update = (
        sa.update(chat)
        .where(chat.c.id == sa.bindparam('target_chat_id'))
        .values(meta=sa.bindparam('new_meta', type_=sa.JSON()))
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

        # ORDER BY tag.name gives deterministic meta['tags'] ordering across
        # downgrade runs (row order from chat_tag is otherwise undefined).
        tag_rows = conn.execute(
            sa.select(chat_tag.c.chat_id, tag.c.name)
            .select_from(
                chat_tag.join(
                    tag,
                    sa.and_(
                        chat_tag.c.tag_id == tag.c.id,
                        chat_tag.c.user_id == tag.c.user_id,
                    ),
                )
            )
            .where(chat_tag.c.chat_id.in_(chat_ids_in_page))
            .order_by(chat_tag.c.chat_id, tag.c.name)
        ).fetchall()
        tag_names_by_chat_id: dict[str, list[str]] = {cid: [] for cid in chat_ids_in_page}
        for tag_row in tag_rows:
            tag_names_by_chat_id[tag_row.chat_id].append(tag_row.name)

        update_params = []
        for chat_id in chat_ids_in_page:
            tag_names = tag_names_by_chat_id[chat_id]
            existing_meta = existing_meta_by_chat_id.get(chat_id)
            if isinstance(existing_meta, str):
                try:
                    existing_meta = json.loads(existing_meta)
                except (TypeError, ValueError):
                    existing_meta = {}
            # Downgrade is lossy for originally-non-dict meta (replaced with {}).
            # Upgrade already skipped such chats, so this only affects rows
            # mutated post-upgrade.
            if not isinstance(existing_meta, dict):
                existing_meta = {}
            # Skip chats that had no tags pre-upgrade and still have none:
            # don't grow their meta with an empty 'tags' key.
            if not tag_names and 'tags' not in existing_meta:
                continue
            merged_meta = {**existing_meta, 'tags': tag_names}
            update_params.append({'target_chat_id': chat_id, 'new_meta': merged_meta})

        if update_params:
            conn.execute(bulk_update, update_params)
            chats_rewritten += len(update_params)

        last_chat_id = chat_ids_in_page[-1]

    log.info(f'chat_tag downgrade: serialized tags back into meta for {chats_rewritten} chats')

    op.drop_index('chat_tag_user_tag_idx', table_name='chat_tag')
    op.drop_table('chat_tag')
