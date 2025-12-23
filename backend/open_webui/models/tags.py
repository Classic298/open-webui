import logging
from typing import Optional

from open_webui.internal.db import Base, get_db

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, String, JSON, PrimaryKeyConstraint, Index, select, delete

log = logging.getLogger(__name__)


####################
# Tag DB Schema
####################
class Tag(Base):
    __tablename__ = "tag"
    id = Column(String)
    name = Column(String)
    user_id = Column(String)
    meta = Column(JSON, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("id", "user_id", name="pk_id_user_id"),
        Index("user_id_idx", "user_id"),
    )

    # Unique constraint ensuring (id, user_id) is unique, not just the `id` column
    __table_args__ = (PrimaryKeyConstraint("id", "user_id", name="pk_id_user_id"),)


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


####################
# TagTable
####################


class TagTable:
    """Table class for tag database operations."""

    async def insert_new_tag(self, name: str, user_id: str) -> Optional[TagModel]:
        """Insert a new tag. Returns the created TagModel or None on failure."""
        async with get_db() as db:
            id = name.replace(" ", "_").lower()
            tag = TagModel(id=id, user_id=user_id, name=name)
            try:
                result = Tag(**tag.model_dump())
                db.add(result)
                await db.commit()
                await db.refresh(result)
                return TagModel.model_validate(result) if result else None
            except Exception as e:
                log.exception(f"Error inserting a new tag: {e}")
                return None

    async def get_tag_by_name_and_user_id(
        self, name: str, user_id: str
    ) -> Optional[TagModel]:
        """Get a tag by name and user ID. Returns TagModel or None if not found."""
        try:
            id = name.replace(" ", "_").lower()
            async with get_db() as db:
                result = await db.execute(
                    select(Tag).where(Tag.id == id, Tag.user_id == user_id)
                )
                tag = result.scalar_one_or_none()
                return TagModel.model_validate(tag) if tag else None
        except Exception:
            return None

    async def get_tags_by_user_id(self, user_id: str) -> list[TagModel]:
        """Get all tags for a user."""
        async with get_db() as db:
            result = await db.execute(select(Tag).where(Tag.user_id == user_id))
            tags = result.scalars().all()
            return [TagModel.model_validate(tag) for tag in tags]

    async def get_tags_by_ids_and_user_id(
        self, ids: list[str], user_id: str
    ) -> list[TagModel]:
        """Get tags by their IDs for a specific user."""
        async with get_db() as db:
            result = await db.execute(
                select(Tag).where(Tag.id.in_(ids), Tag.user_id == user_id)
            )
            tags = result.scalars().all()
            return [TagModel.model_validate(tag) for tag in tags]

    async def delete_tag_by_name_and_user_id(self, name: str, user_id: str) -> bool:
        """Delete a tag by name and user ID. Returns True on success."""
        try:
            async with get_db() as db:
                id = name.replace(" ", "_").lower()
                await db.execute(
                    delete(Tag).where(Tag.id == id, Tag.user_id == user_id)
                )
                await db.commit()
                return True
        except Exception as e:
            log.error(f"delete_tag: {e}")
            return False


# Module instance
Tags = TagTable()
