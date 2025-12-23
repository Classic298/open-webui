import asyncio
import json
import time
import uuid
from typing import Optional
from functools import lru_cache

from open_webui.internal.db import Base, get_db
from open_webui.models.groups import Groups
from open_webui.utils.access_control import has_access
from open_webui.models.users import User, UserModel, Users, UserResponse


from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Boolean, Column, String, Text, JSON
from sqlalchemy.dialects.postgresql import JSONB


from sqlalchemy import or_, func, select, and_, text, cast, or_, and_, func
from sqlalchemy.sql import exists

####################
# Note DB Schema
####################


class Note(Base):
    __tablename__ = "note"

    id = Column(Text, primary_key=True, unique=True)
    user_id = Column(Text)

    title = Column(Text)
    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)

    access_control = Column(JSON, nullable=True)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class NoteModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str

    title: str
    data: Optional[dict] = None
    meta: Optional[dict] = None

    access_control: Optional[dict] = None

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch


####################
# Forms
####################


class NoteForm(BaseModel):
    title: str
    data: Optional[dict] = None
    meta: Optional[dict] = None
    access_control: Optional[dict] = None


class NoteUpdateForm(BaseModel):
    title: Optional[str] = None
    data: Optional[dict] = None
    meta: Optional[dict] = None
    access_control: Optional[dict] = None


class NoteUserResponse(NoteModel):
    user: Optional[UserResponse] = None


class NoteItemResponse(BaseModel):
    id: str
    title: str
    data: Optional[dict]
    updated_at: int
    created_at: int
    user: Optional[UserResponse] = None


class NoteListResponse(BaseModel):
    items: list[NoteUserResponse]
    total: int

class NotesTable:
    """Table class for database operations."""

    def _has_permission(self, query, filter: dict, dialect_name: str, permission: str = "read"):
        group_ids = filter.get("group_ids", [])
        user_id = filter.get("user_id")
        
        conditions = []

        if permission == "read_only":
            read_conditions = []
            if group_ids:
                group_read_conditions = []
                for gid in group_ids:
                    if dialect_name == "sqlite":
                        group_read_conditions.append(
                            Note.access_control["read"]["group_ids"].contains([gid])
                        )
                    elif dialect_name == "postgresql":
                        group_read_conditions.append(
                            cast(Note.access_control["read"]["group_ids"], JSONB).contains([gid])
                        )
                
                if group_read_conditions:
                    read_conditions.append(or_(*group_read_conditions))
            
            if read_conditions:
                has_read = or_(*read_conditions)
            else:
                return query.where(False)
            
            write_exclusions = []
            
            if user_id:
                write_exclusions.append(Note.user_id != user_id)
            
            if group_ids:
                group_write_conditions = []
                for gid in group_ids:
                    if dialect_name == "sqlite":
                        group_write_conditions.append(
                            Note.access_control["write"]["group_ids"].contains([gid])
                        )
                    elif dialect_name == "postgresql":
                        group_write_conditions.append(
                            cast(Note.access_control["write"]["group_ids"], JSONB).contains([gid])
                        )
                if group_write_conditions:
                    write_exclusions.append(~or_(*group_write_conditions))
            
            # Exclude public items (items without access_control)
            write_exclusions.append(Note.access_control.isnot(None))
            write_exclusions.append(cast(Note.access_control, String) != "null")
            
            if write_exclusions:
                query = query.where(and_(has_read, *write_exclusions))
            else:
                query = query.where(has_read)
            
            return query

        # Original logic for other permissions (read, write, etc.)
        # Public access conditions
        if group_ids or user_id:
             conditions.extend([
                 Note.access_control.is_(None),
                 cast(Note.access_control, String) == "null"
             ])
        
        # User-level permission (owner has all permissions)
        if user_id:
            conditions.append(Note.user_id == user_id)
            
        # Group-level permission
        if group_ids:
            group_conditions = []
            for gid in group_ids:
                if dialect_name == "sqlite":
                     group_conditions.append(
                         Note.access_control[permission]["group_ids"].contains([gid])
                     )
                elif dialect_name == "postgresql":
                     group_conditions.append(
                         cast(Note.access_control[permission]["group_ids"], JSONB).contains([gid])
                     )
            conditions.append(or_(*group_conditions))
            
        if conditions:
            query = query.where(or_(*conditions))
            
        return query

    async def insert_new_note(
        self,
        form_data: NoteForm,
        user_id: str,
    ) -> Optional[NoteModel]:
        async with get_db() as db:
            note = NoteModel(
                id=str(uuid.uuid4()),
                user_id=user_id,
                **form_data.model_dump(),
                created_at=int(time.time_ns()),
                updated_at=int(time.time_ns()),
            )
            
            new_note = Note(**note.model_dump())
            db.add(new_note)
            await db.commit()
            return note

    async def get_notes(
        self, skip: Optional[int] = None, limit: Optional[int] = None
    ) -> list[NoteModel]:
        async with get_db() as db:
            query = select(Note).order_by(Note.updated_at.desc())
            if skip is not None:
                query = query.offset(skip)
            if limit is not None:
                query = query.limit(limit)
            result = await db.execute(query)
            notes = result.scalars().all()
            return [NoteModel.model_validate(note) for note in notes]

    async def get_notes_by_user_id(
        self,
        user_id: str,
        permission: str = "read",
        skip: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> list[NoteModel]:
        groups = await Groups.get_groups_by_member_id(user_id)
        user_group_ids = [group.id for group in groups]
        
        async with get_db() as db:
             dialect_name = db.bind.dialect.name
             query = select(Note).order_by(Note.updated_at.desc())
             
             query = self._has_permission(
                 query, 
                 {"user_id": user_id, "group_ids": user_group_ids}, 
                 dialect_name, 
                 permission
             )
             
             if skip is not None:
                 query = query.offset(skip)
             if limit is not None:
                 query = query.limit(limit)
             
             result = await db.execute(query)
             notes = result.scalars().all()
             return [NoteModel.model_validate(note) for note in notes]

    async def search_notes(
        self, user_id: str, filter: dict = {}, skip: int = 0, limit: int = 30
    ) -> NoteListResponse:
        async with get_db() as db:
             dialect_name = db.bind.dialect.name
             query = select(Note, User).outerjoin(User, User.id == Note.user_id)
             
             if filter:
                 query_key = filter.get("query")
                 if query_key:
                     query = query.where(
                         or_(
                             Note.title.ilike(f"%{query_key}%"),
                             cast(Note.data["content"]["md"], Text).ilike(f"%{query_key}%")
                         )
                     )
                 
                 view_option = filter.get("view_option")
                 if view_option == "created":
                     query = query.where(Note.user_id == user_id)
                 elif view_option == "shared":
                     query = query.where(Note.user_id != user_id)
                 
                 perm = filter.get("permission", "write")
                 
                 # Apply access control filtering
                 query = self._has_permission(query, filter, dialect_name, permission=perm)
                 
                 order_by = filter.get("order_by")
                 direction = filter.get("direction")
                 
                 if order_by == "name":
                     sort_col = Note.title
                 elif order_by == "created_at":
                     sort_col = Note.created_at
                 elif order_by == "updated_at":
                     sort_col = Note.updated_at
                 else:
                     sort_col = Note.updated_at
                     
                 if direction == "asc":
                     query = query.order_by(sort_col.asc())
                 else:
                     query = query.order_by(sort_col.desc())
             else:
                 query = query.order_by(Note.updated_at.desc())
             
             # Count before pagination
             count_res = await db.execute(select(func.count()).select_from(query.subquery()))
             total = count_res.scalar() or 0
             
             if skip:
                 query = query.offset(skip)
             if limit:
                 query = query.limit(limit)
             
             result = await db.execute(query)
             items = result.all()
             
             notes = []
             for note, user in items:
                 notes.append(
                     NoteUserResponse(
                         **NoteModel.model_validate(note).model_dump(),
                         user=(
                             UserResponse(**UserModel.model_validate(user).model_dump())
                             if user else None
                         ),
                     )
                 )
             return NoteListResponse(items=notes, total=total)

    async def get_note_by_id(self, id: str) -> Optional[NoteModel]:
        async with get_db() as db:
            result = await db.execute(select(Note).where(Note.id == id))
            note = result.scalar_one_or_none()
            return NoteModel.model_validate(note) if note else None

    async def update_note_by_id(
        self, id: str, form_data: NoteUpdateForm
    ) -> Optional[NoteModel]:
        async with get_db() as db:
            result = await db.execute(select(Note).where(Note.id == id))
            note = result.scalar_one_or_none()
            if not note:
                return None
            
            data = form_data.model_dump(exclude_unset=True)
            
            if "title" in data:
                note.title = data["title"]
            if "data" in data:
                note.data = {**(note.data or {}), **data["data"]}
            if "meta" in data:
                note.meta = {**(note.meta or {}), **data["meta"]}
            if "access_control" in data:
                note.access_control = data["access_control"]
            
            note.updated_at = int(time.time_ns())
            
            await db.commit()
            return NoteModel.model_validate(note)

    async def delete_note_by_id(self, id: str) -> bool:
        async with get_db() as db:
            await db.execute(delete(Note).where(Note.id == id))
            await db.commit()
            return True


# Module instance
Notes = NotesTable()


