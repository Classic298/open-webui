import logging
import time
import uuid
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from open_webui.internal.db import Base, JSONField, get_async_db_context, insert_all_on_conflict_nothing


from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, JSON, PrimaryKeyConstraint, Index

log = logging.getLogger(__name__)


####################
# Tag DB Schema
# To name a thing is to claim it. The creator has
# already named everything stored in this table.
####################
# Reserved tag_id used as a sentinel by the tag:none search filter
# ("chat has no tags"). Writers must reject it so it can never become a
# real association.
RESERVED_TAG_ID_NONE = 'none'


def normalize_tag_id(raw: str) -> str:
    """Canonical tag_id form. This is the PK for tag and chat_tag, so every
    call site that derives an id from a user-supplied name must use this."""
    return raw.replace(' ', '_').lower()


class Tag(Base):
    __tablename__ = 'tag'
    id = Column(String)
    name = Column(String)
    user_id = Column(String)
    meta = Column(JSON, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint('id', 'user_id', name='pk_id_user_id'),
        Index('user_id_idx', 'user_id'),
    )


class TagModel(BaseModel):
    id: str
    name: str
    user_id: str
    meta: Optional[dict] = None
    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################


class TagChatIdForm(BaseModel):
    name: str
    chat_id: str


class TagTable:
    async def insert_new_tag(self, name: str, user_id: str, db: Optional[AsyncSession] = None) -> Optional[TagModel]:
        async with get_async_db_context(db) as db:
            id = normalize_tag_id(name)
            tag = TagModel(**{'id': id, 'user_id': user_id, 'name': name})
            try:
                result = Tag(**tag.model_dump())
                db.add(result)
                await db.commit()
                await db.refresh(result)
                if result:
                    return TagModel.model_validate(result)
                else:
                    return None
            except Exception as e:
                log.exception(f'Error inserting a new tag: {e}')
                return None

    async def get_tag_by_name_and_user_id(
        self, name: str, user_id: str, db: Optional[AsyncSession] = None
    ) -> Optional[TagModel]:
        try:
            id = normalize_tag_id(name)
            async with get_async_db_context(db) as db:
                result = await db.execute(select(Tag).filter_by(id=id, user_id=user_id))
                tag = result.scalars().first()
                return TagModel.model_validate(tag) if tag else None
        except Exception:
            return None

    async def get_tags_by_user_id(self, user_id: str, db: Optional[AsyncSession] = None) -> list[TagModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(select(Tag).filter_by(user_id=user_id))
            return [TagModel.model_validate(tag) for tag in result.scalars().all()]

    async def get_tags_by_ids_and_user_id(
        self, ids: list[str], user_id: str, db: Optional[AsyncSession] = None
    ) -> list[TagModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(select(Tag).filter(Tag.id.in_(ids), Tag.user_id == user_id))
            return [TagModel.model_validate(tag) for tag in result.scalars().all()]

    async def delete_tag_by_name_and_user_id(self, name: str, user_id: str, db: Optional[AsyncSession] = None) -> bool:
        try:
            async with get_async_db_context(db) as db:
                id = normalize_tag_id(name)
                result = await db.execute(delete(Tag).filter_by(id=id, user_id=user_id))
                log.debug(f'res: {result.rowcount}')
                await db.commit()
                return True
        except Exception as e:
            log.error(f'delete_tag: {e}')
            return False

    async def delete_tags_by_ids_and_user_id(
        self, ids: list[str], user_id: str, db: Optional[AsyncSession] = None
    ) -> bool:
        """Delete all tags whose id is in *ids* for the given user, in one query."""
        if not ids:
            return True
        try:
            async with get_async_db_context(db) as db:
                await db.execute(delete(Tag).filter(Tag.id.in_(ids), Tag.user_id == user_id))
                await db.commit()
                return True
        except Exception as e:
            log.error(f'delete_tags_by_ids: {e}')
            return False

    async def ensure_tags_exist(
        self,
        names: list[str],
        user_id: str,
        db: Optional[AsyncSession] = None,
        commit: bool = True,
    ) -> None:
        """Create tag rows for any *names* that don't already exist for *user_id*.

        Pass ``commit=False`` when the caller owns a larger transaction that
        must remain atomic (e.g. a dual-write that also touches chat_tag);
        the caller is then responsible for committing the session.
        """
        if not commit and db is None:
            raise ValueError('ensure_tags_exist(commit=False) requires an explicit db session')
        if not names:
            return
        # Dedupe on normalized id, first display name wins. ON CONFLICT DO
        # NOTHING handles the concurrent-insert race so we don't need the
        # old SELECT-then-add check.
        values_by_tag_id: dict[str, dict] = {}
        for name in names:
            tag_id = normalize_tag_id(name)
            values_by_tag_id.setdefault(
                tag_id, {'id': tag_id, 'name': name, 'user_id': user_id}
            )
        async with get_async_db_context(db) as db:
            await insert_all_on_conflict_nothing(
                db, Tag, list(values_by_tag_id.values()), index_elements=['id', 'user_id']
            )
            if commit:
                await db.commit()


Tags = TagTable()
