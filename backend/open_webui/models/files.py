import asyncio
import logging
import time
import uuid
from typing import Optional

from open_webui.internal.db import Base, JSONField, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, Text, JSON, select, delete, func

log = logging.getLogger(__name__)

####################
# Files DB Schema
####################


class File(Base):
    __tablename__ = "file"
    id = Column(String, primary_key=True, unique=True)
    user_id = Column(String)
    hash = Column(Text, nullable=True)

    filename = Column(Text)
    path = Column(Text, nullable=True)

    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)

    access_control = Column(JSON, nullable=True)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class FileModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    hash: Optional[str] = None

    filename: str
    path: Optional[str] = None

    data: Optional[dict] = None
    meta: Optional[dict] = None

    access_control: Optional[dict] = None

    created_at: Optional[int]  # timestamp in epoch
    updated_at: Optional[int]  # timestamp in epoch


####################
# Forms
####################


class FileMeta(BaseModel):
    name: Optional[str] = None
    content_type: Optional[str] = None
    size: Optional[int] = None

    model_config = ConfigDict(extra="allow")


class FileModelResponse(BaseModel):
    id: str
    user_id: str
    hash: Optional[str] = None

    filename: str
    data: Optional[dict] = None
    meta: FileMeta

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch

    model_config = ConfigDict(extra="allow")


class FileMetadataResponse(BaseModel):
    id: str
    hash: Optional[str] = None
    meta: Optional[dict] = None
    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch


class FileForm(BaseModel):
    id: str
    hash: Optional[str] = None
    filename: str
    path: str
    data: dict = {}
    meta: dict = {}
    access_control: Optional[dict] = None


class FileUpdateForm(BaseModel):
    hash: Optional[str] = None
    data: Optional[dict] = None
    meta: Optional[dict] = None


class FileListResponse(BaseModel):
    items: list[FileModel]
    total: int

class FilesTable:
    """Table class for database operations."""
    
    async def insert_new_file(
        self, user_id: str, form_data: FileForm
    ) -> Optional[FileModel]:
        async with get_db() as db:
            file = FileModel(
                id=str(uuid.uuid4()),
                user_id=user_id,
                filename=form_data.filename,
                path=form_data.path,
                hash=form_data.hash,
                meta=form_data.meta,
                created_at=int(time.time()),
                updated_at=int(time.time()),
            )
            try:
                result = File(**file.model_dump())
                db.add(result)
                await db.commit()
                await db.refresh(result)
                return FileModel.model_validate(result) if result else None
            except Exception:
                return None

    async def get_file_by_id(self, id: str) -> Optional[FileModel]:
        try:
            async with get_db() as db:
                file = await db.get(File, id)
                return FileModel.model_validate(file) if file else None
        except Exception:
            return None

    async def get_file_metadata_by_id(self, id: str) -> Optional[FileMetadataResponse]:
        try:
            async with get_db() as db:
                file = await db.get(File, id)
                return FileMetadataResponse(
                    id=file.id,
                    hash=file.hash,
                    meta=file.meta,
                    created_at=file.created_at,
                    updated_at=file.updated_at,
                ) if file else None
        except Exception:
            return None

    async def get_files(self) -> list[FileModel]:
        async with get_db() as db:
            result = await db.execute(select(File))
            files = result.scalars().all()
            return [FileModel.model_validate(f) for f in files]

    async def get_files_by_user_id(self, user_id: str) -> list[FileModel]:
        async with get_db() as db:
            result = await db.execute(select(File).where(File.user_id == user_id))
            files = result.scalars().all()
            return [FileModel.model_validate(f) for f in files]

    async def get_files_by_ids(self, ids: list[str]) -> list[FileModel]:
        async with get_db() as db:
            result = await db.execute(
                select(File).where(File.id.in_(ids)).order_by(File.updated_at.desc())
            )
            files = result.scalars().all()
            return [FileModel.model_validate(f) for f in files]

    async def get_file_metadatas_by_ids(self, ids: list[str]) -> list[FileMetadataResponse]:
        async with get_db() as db:
            result = await db.execute(
                select(File.id, File.hash, File.meta, File.created_at, File.updated_at)
                .where(File.id.in_(ids))
                .order_by(File.updated_at.desc())
            )
            files = result.all()
            return [
                FileMetadataResponse(
                    id=f.id,
                    hash=f.hash,
                    meta=f.meta,
                    created_at=f.created_at,
                    updated_at=f.updated_at,
                )
                for f in files
            ]

    async def check_access_by_user_id(self, id: str, user_id: str, permission: str = "write") -> bool:
        file = await self.get_file_by_id(id)
        if not file:
            return False
        return file.user_id == user_id

    async def update_file_by_id(
        self, id: str, form_data: FileUpdateForm
    ) -> Optional[FileModel]:
        async with get_db() as db:
            try:
                file = await db.get(File, id)
                if not file:
                    return None

                if form_data.hash is not None:
                    file.hash = form_data.hash

                if form_data.data is not None:
                    file.data = {**(file.data if file.data else {}), **form_data.data}

                if form_data.meta is not None:
                    file.meta = {**(file.meta if file.meta else {}), **form_data.meta}

                file.updated_at = int(time.time())
                await db.commit()
                return FileModel.model_validate(file)
            except Exception as e:
                log.exception(f"Error updating file completely by id: {e}")
                return None

    async def update_file_hash_by_id(self, id: str, hash: str) -> Optional[FileModel]:
        async with get_db() as db:
            try:
                file = await db.get(File, id)
                if not file:
                    return None
                    
                file.hash = hash
                file.updated_at = int(time.time())
                await db.commit()
                return FileModel.model_validate(file)
            except Exception:
                return None

    async def update_file_metadata_by_id(self, id: str, meta: dict) -> Optional[FileModel]:
        async with get_db() as db:
            try:
                file = await db.get(File, id)
                if not file:
                    return None
                    
                file.meta = {**(file.meta if file.meta else {}), **meta}
                file.updated_at = int(time.time())
                await db.commit()
                return FileModel.model_validate(file)
            except Exception:
                return None

    async def update_file_data_by_id(self, id: str, data: dict) -> Optional[FileModel]:
        async with get_db() as db:
            try:
                file = await db.get(File, id)
                if not file:
                    return None
                
                file.data = {**(file.data or {}), **data}
                file.updated_at = int(time.time())
                await db.commit()
                return FileModel.model_validate(file)
            except Exception:
                return None

    async def delete_file_by_id(self, id: str) -> bool:
        async with get_db() as db:
            try:
                from sqlalchemy import delete
                await db.execute(delete(File).where(File.id == id))
                await db.commit()
                return True
            except Exception:
                return False

    async def delete_all_files(self) -> bool:
        async with get_db() as db:
            try:
                from sqlalchemy import delete
                await db.execute(delete(File))
                await db.commit()
                return True
            except Exception:
                return False


# Module instance
Files = FilesTable()


