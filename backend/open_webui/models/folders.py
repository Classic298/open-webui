import asyncio
import logging
import time
import uuid
from typing import Optional
import re


from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, Text, JSON, Boolean, func, select, delete

from open_webui.internal.db import Base, get_db


log = logging.getLogger(__name__)


####################
# Folder DB Schema
####################


class Folder(Base):
    __tablename__ = "folder"
    id = Column(Text, primary_key=True, unique=True)
    parent_id = Column(Text, nullable=True)
    user_id = Column(Text)
    name = Column(Text)
    items = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)
    data = Column(JSON, nullable=True)
    is_expanded = Column(Boolean, default=False)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class FolderModel(BaseModel):
    id: str
    parent_id: Optional[str] = None
    user_id: str
    name: str
    items: Optional[dict] = None
    meta: Optional[dict] = None
    data: Optional[dict] = None
    is_expanded: bool = False
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)


class FolderMetadataResponse(BaseModel):
    icon: Optional[str] = None


class FolderNameIdResponse(BaseModel):
    id: str
    name: str
    meta: Optional[FolderMetadataResponse] = None
    parent_id: Optional[str] = None
    is_expanded: bool = False
    created_at: int
    updated_at: int


####################
# Forms
####################


class FolderForm(BaseModel):
    name: str
    data: Optional[dict] = None
    meta: Optional[dict] = None
    model_config = ConfigDict(extra="allow")


class FolderUpdateForm(BaseModel):
    name: Optional[str] = None
    data: Optional[dict] = None
    meta: Optional[dict] = None
    model_config = ConfigDict(extra="allow")

class FoldersTable:
    """Native async version of FolderTable."""
    
    async def insert_new_folder(
        self, user_id: str, form_data: FolderForm, parent_id: Optional[str] = None
    ) -> Optional[FolderModel]:
        async with get_db() as db:
            id = str(uuid.uuid4())
            folder = FolderModel(
                **{
                    "id": id,
                    "user_id": user_id,
                    **(form_data.model_dump(exclude_unset=True) or {}),
                    "parent_id": parent_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )
            try:
                result = Folder(**folder.model_dump())
                db.add(result)
                await db.commit()
                await db.refresh(result)
                return FolderModel.model_validate(result) if result else None
            except Exception as e:
                log.exception(f"Error inserting a new folder: {e}")
                return None

    async def get_folder_by_id_and_user_id(
        self, id: str, user_id: str
    ) -> Optional[FolderModel]:
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(Folder).where(Folder.id == id, Folder.user_id == user_id)
                )
                folder = result.scalar_one_or_none()
                return FolderModel.model_validate(folder) if folder else None
        except Exception:
            return None

    async def get_children_folders_by_id_and_user_id(
        self, id: str, user_id: str
    ) -> Optional[list[FolderModel]]:
        try:
            # Recursive strategy: since recursion depth is usually small, we can just do it.
            # But async recursion is tricky if we want to be efficient.
            # Helper function
            async def get_children(folder_id):
                children = await self.get_folders_by_parent_id_and_user_id(
                    folder_id, user_id
                )
                all_descendants = []
                for child in children:
                    all_descendants.append(child)
                    descendants = await get_children(child.id)
                    all_descendants.extend(descendants)
                return all_descendants
            
            async with get_db() as db:
                # verify root exists
                res = await db.execute(select(Folder).where(Folder.id == id, Folder.user_id == user_id))
                folder = res.scalar_one_or_none()
                if not folder:
                    return None
            
            return await get_children(id)
        except Exception:
            return None

    async def get_folders_by_user_id(self, user_id: str) -> list[FolderModel]:
        async with get_db() as db:
            result = await db.execute(select(Folder).where(Folder.user_id == user_id))
            folders = result.scalars().all()
            return [FolderModel.model_validate(folder) for folder in folders]

    async def get_folder_by_parent_id_and_user_id_and_name(
        self, parent_id: Optional[str], user_id: str, name: str
    ) -> Optional[FolderModel]:
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(Folder)
                    .where(Folder.parent_id == parent_id, Folder.user_id == user_id, Folder.name.ilike(name))
                )
                folder = result.scalar_one_or_none()
                return FolderModel.model_validate(folder) if folder else None
        except Exception as e:
            log.error(f"get_folder_by_parent_id_and_user_id_and_name: {e}")
            return None

    async def get_folders_by_parent_id_and_user_id(
        self, parent_id: Optional[str], user_id: str
    ) -> list[FolderModel]:
        async with get_db() as db:
            result = await db.execute(
                select(Folder)
                .where(Folder.parent_id == parent_id, Folder.user_id == user_id)
            )
            folders = result.scalars().all()
            return [FolderModel.model_validate(f) for f in folders]

    async def update_folder_parent_id_by_id_and_user_id(
        self,
        id: str,
        user_id: str,
        parent_id: str,
    ) -> Optional[FolderModel]:
        try:
            async with get_db() as db:
                folder_res = await db.execute(select(Folder).where(Folder.id == id, Folder.user_id == user_id))
                folder = folder_res.scalar_one_or_none()

                if not folder:
                    return None

                folder.parent_id = parent_id
                folder.updated_at = int(time.time())

                await db.commit()
                await db.refresh(folder)
                return FolderModel.model_validate(folder)
        except Exception as e:
            log.error(f"update_folder: {e}")
            return None

    async def update_folder_by_id_and_user_id(
        self, id: str, user_id: str, form_data: FolderUpdateForm
    ) -> Optional[FolderModel]:
        try:
            async with get_db() as db:
                folder_res = await db.execute(select(Folder).where(Folder.id == id, Folder.user_id == user_id))
                folder = folder_res.scalar_one_or_none()

                if not folder:
                    return None

                form_data_dict = form_data.model_dump(exclude_unset=True)

                existing_folder_res = await db.execute(
                    select(Folder)
                    .where(
                        Folder.name == form_data_dict.get("name"),
                        Folder.parent_id == folder.parent_id,
                        Folder.user_id == user_id,
                    )
                )
                existing_folder = existing_folder_res.scalar_one_or_none()

                if existing_folder and existing_folder.id != id:
                    return None

                folder.name = form_data_dict.get("name", folder.name)
                if "data" in form_data_dict:
                    folder.data = {
                        **(folder.data or {}),
                        **form_data_dict["data"],
                    }

                if "meta" in form_data_dict:
                    folder.meta = {
                        **(folder.meta or {}),
                        **form_data_dict["meta"],
                    }

                folder.updated_at = int(time.time())
                await db.commit()
                await db.refresh(folder)

                return FolderModel.model_validate(folder)
        except Exception as e:
            log.error(f"update_folder: {e}")
            return None

    async def update_folder_is_expanded_by_id_and_user_id(
        self, id: str, user_id: str, is_expanded: bool
    ) -> Optional[FolderModel]:
        try:
            async with get_db() as db:
                folder_res = await db.execute(select(Folder).where(Folder.id == id, Folder.user_id == user_id))
                folder = folder_res.scalar_one_or_none()

                if not folder:
                    return None

                folder.is_expanded = is_expanded
                folder.updated_at = int(time.time())

                await db.commit()
                await db.refresh(folder)

                return FolderModel.model_validate(folder)
        except Exception as e:
            log.error(f"update_folder: {e}")
            return None

    async def delete_folder_by_id_and_user_id(self, id: str, user_id: str) -> list[str]:
        try:
            folder_ids = []
            async with get_db() as db:
                folder_res = await db.execute(select(Folder).where(Folder.id == id, Folder.user_id == user_id))
                folder = folder_res.scalar_one_or_none()
                if not folder:
                    return folder_ids

                folder_ids.append(folder.id)

                # Delete all children folders
                async def delete_children(folder_id):
                    # We have to fetch children first
                    # Using separate session/query logic might be cleaner or just recursion
                    # We can reuse get_folders_by_parent_id, but it uses db session
                    # So we should probably do a raw select here to keep session context
                    result = await db.execute(
                        select(Folder).where(Folder.parent_id == folder_id, Folder.user_id == user_id)
                    )
                    children = result.scalars().all()
                    
                    for child in children:
                        await delete_children(child.id)
                        folder_ids.append(child.id)
                        await db.delete(child)


                await delete_children(folder.id)
                await db.delete(folder)
                await db.commit()
                return folder_ids
        except Exception as e:
            log.error(f"delete_folder: {e}")
            return []

    def normalize_folder_name(self, name: str) -> str:
        # Replace _ and space with a single space, lower case, collapse multiple spaces
        name = re.sub(r"[\s_]+", " ", name)
        return name.strip().lower()

    async def search_folders_by_names(
        self, user_id: str, queries: list[str]
    ) -> list[FolderModel]:
        """
        Search for folders for a user where the name matches any of the queries, treating _ and space as equivalent, case-insensitive.
        """
        normalized_queries = [self.normalize_folder_name(q) for q in queries]
        if not normalized_queries:
            return []

        results = {}
        async with get_db() as db:
            all_folders_res = await db.execute(select(Folder).where(Folder.user_id == user_id))
            folders = all_folders_res.scalars().all()
            
            for folder in folders:
                if self.normalize_folder_name(folder.name) in normalized_queries:
                    results[folder.id] = FolderModel.model_validate(folder)

                    # get children folders (reuse method or logic?)
                    # simpler to just call the recursive getter we made
                    children = await self.get_children_folders_by_id_and_user_id(folder.id, user_id)
                    if children:
                         for child in children:
                             results[child.id] = child

        if not results:
            return []
        else:
            return list(results.values())

    async def search_folders_by_name_contains(
        self, user_id: str, query: str
    ) -> list[FolderModel]:
        """
        Partial match: normalized name contains (as substring) the normalized query.
        """
        normalized_query = self.normalize_folder_name(query)
        results = []
        async with get_db() as db:
            result = await db.execute(select(Folder).where(Folder.user_id == user_id))
            folders = result.scalars().all()
            
            for folder in folders:
                norm_name = self.normalize_folder_name(folder.name)
                if normalized_query in norm_name:
                    results.append(FolderModel.model_validate(folder))
        return results


# Module instance
Folders = FoldersTable()

