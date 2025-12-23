import asyncio
import json
import logging
import time
from typing import Optional
import uuid

from open_webui.internal.db import Base, get_db

from open_webui.models.files import (
    File,
    FileModel,
    FileMetadataResponse,
    FileModelResponse,
)
from open_webui.models.groups import Groups
from open_webui.models.users import User, UserModel, Users, UserResponse


from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    String,
    Text,
    JSON,
    UniqueConstraint,
    or_,
    select,
    delete,
    update,
    func,
    and_,
    cast,
)
from sqlalchemy.dialects.postgresql import JSONB

from open_webui.utils.access_control import has_access
from open_webui.utils.db.access_control import has_permission


log = logging.getLogger(__name__)

####################
# Knowledge DB Schema
####################


class Knowledge(Base):
    __tablename__ = "knowledge"

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text)

    name = Column(Text)
    description = Column(Text)

    meta = Column(JSON, nullable=True)
    access_control = Column(JSON, nullable=True)  # Controls data access levels.
    # Defines access control rules for this entry.
    # - `None`: Public access, available to all users with the "user" role.
    # - `{}`: Private access, restricted exclusively to the owner.
    # - Custom permissions: Specific access control for reading and writing;
    #   Can specify group or user-level restrictions:
    #   {
    #      "read": {
    #          "group_ids": ["group_id1", "group_id2"],
    #          "user_ids":  ["user_id1", "user_id2"]
    #      },
    #      "write": {
    #          "group_ids": ["group_id1", "group_id2"],
    #          "user_ids":  ["user_id1", "user_id2"]
    #      }
    #   }

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class KnowledgeModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str

    name: str
    description: str

    meta: Optional[dict] = None

    access_control: Optional[dict] = None

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch


class KnowledgeFile(Base):
    __tablename__ = "knowledge_file"

    id = Column(Text, unique=True, primary_key=True)

    knowledge_id = Column(
        Text, ForeignKey("knowledge.id", ondelete="CASCADE"), nullable=False
    )
    file_id = Column(Text, ForeignKey("file.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Text, nullable=False)

    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "knowledge_id", "file_id", name="uq_knowledge_file_knowledge_file"
        ),
    )


class KnowledgeFileModel(BaseModel):
    id: str
    knowledge_id: str
    file_id: str
    user_id: str

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch

    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################
class KnowledgeUserModel(KnowledgeModel):
    user: Optional[UserResponse] = None


class KnowledgeResponse(KnowledgeModel):
    files: Optional[list[FileMetadataResponse | dict]] = None


class KnowledgeUserResponse(KnowledgeUserModel):
    pass


class KnowledgeForm(BaseModel):
    name: str
    description: str
    access_control: Optional[dict] = None


class FileUserResponse(FileModelResponse):
    user: Optional[UserResponse] = None


class KnowledgeListResponse(BaseModel):
    items: list[KnowledgeUserModel]
    total: int


class KnowledgeFileListResponse(BaseModel):
    items: list[FileUserResponse]
    total: int



class KnowledgesTable:
    """Table class for database operations."""
    
    async def insert_new_knowledge(
        self, user_id: str, form_data: KnowledgeForm
    ) -> Optional[KnowledgeModel]:
        knowledge = KnowledgeModel(
            **{
                **form_data.model_dump(),
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "created_at": int(time.time()),
                "updated_at": int(time.time()),
            }
        )
        try:
            async with get_db() as db:
                result = Knowledge(**knowledge.model_dump())
                db.add(result)
                await db.commit()
                await db.refresh(result)
                return KnowledgeModel.model_validate(result) if result else None
        except Exception:
            return None

    async def get_knowledge_bases(
        self, skip: int = 0, limit: int = 30
    ) -> list[KnowledgeUserModel]:
        async with get_db() as db:
            result = await db.execute(select(Knowledge).order_by(Knowledge.updated_at.desc()))
            all_knowledge = result.scalars().all()
            
            user_ids = list(set(k.user_id for k in all_knowledge))
            users = await Users.get_users_by_user_ids(user_ids) if user_ids else []
            users_dict = {user.id: user for user in users}
            
            knowledge_bases = []
            for knowledge in all_knowledge:
                user = users_dict.get(knowledge.user_id)
                knowledge_bases.append(
                    KnowledgeUserModel.model_validate({
                        **KnowledgeModel.model_validate(knowledge).model_dump(),
                        "user": user.model_dump() if user else None,
                    })
                )
            
            return knowledge_bases[skip : skip + limit]

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
                            Knowledge.access_control["read"]["group_ids"].contains([gid])
                        )
                    elif dialect_name == "postgresql":
                        group_read_conditions.append(
                            cast(Knowledge.access_control["read"]["group_ids"], JSONB).contains([gid])
                        )
                
                if group_read_conditions:
                    read_conditions.append(or_(*group_read_conditions))
            
            if read_conditions:
                has_read = or_(*read_conditions)
            else:
                return query.where(False)
            
            write_exclusions = []
            if user_id:
                write_exclusions.append(Knowledge.user_id != user_id)
            
            if group_ids:
                group_write_conditions = []
                for gid in group_ids:
                    if dialect_name == "sqlite":
                        group_write_conditions.append(
                            Knowledge.access_control["write"]["group_ids"].contains([gid])
                        )
                    elif dialect_name == "postgresql":
                        group_write_conditions.append(
                            cast(Knowledge.access_control["write"]["group_ids"], JSONB).contains([gid])
                        )
                if group_write_conditions:
                    write_exclusions.append(~or_(*group_write_conditions))
            
            write_exclusions.append(Knowledge.access_control.isnot(None))
            write_exclusions.append(cast(Knowledge.access_control, String) != "null")
            
            if write_exclusions:
                query = query.where(and_(has_read, *write_exclusions))
            else:
                query = query.where(has_read)
            
            return query

        if group_ids or user_id:
             conditions.extend([
                 Knowledge.access_control.is_(None),
                 cast(Knowledge.access_control, String) == "null"
             ])
        
        if user_id:
            conditions.append(Knowledge.user_id == user_id)
            
        if group_ids:
            group_conditions = []
            for gid in group_ids:
                if dialect_name == "sqlite":
                     group_conditions.append(
                         Knowledge.access_control[permission]["group_ids"].contains([gid])
                     )
                elif dialect_name == "postgresql":
                     group_conditions.append(
                         cast(Knowledge.access_control[permission]["group_ids"], JSONB).contains([gid])
                     )
            conditions.append(or_(*group_conditions))
            
        if conditions:
            query = query.where(or_(*conditions))
            
        return query

    async def search_knowledge_bases(
        self, user_id: str, filter: dict, skip: int = 0, limit: int = 30
    ) -> KnowledgeListResponse:
        async with get_db() as db:
            dialect_name = db.bind.dialect.name
            query = select(Knowledge, User).outerjoin(
                User, User.id == Knowledge.user_id
            )

            if filter:
                query_key = filter.get("query")
                if query_key:
                    query = query.where(
                        or_(
                            Knowledge.name.ilike(f"%{query_key}%"),
                            Knowledge.description.ilike(f"%{query_key}%"),
                        )
                    )

                view_option = filter.get("view_option")
                if view_option == "created":
                    query = query.where(Knowledge.user_id == user_id)
                elif view_option == "shared":
                    query = query.where(Knowledge.user_id != user_id)

                query = self._has_permission(query, filter, dialect_name)

            query = query.order_by(Knowledge.updated_at.desc())

            # Count
            count_res = await db.execute(select(func.count()).select_from(query.subquery()))
            total = count_res.scalar() or 0

            if skip:
                query = query.offset(skip)
            if limit:
                query = query.limit(limit)

            result = await db.execute(query)
            items = result.all()

            knowledge_bases = []
            for knowledge_base, user in items:
                knowledge_bases.append(
                    KnowledgeUserModel.model_validate(
                        {
                            **KnowledgeModel.model_validate(
                                knowledge_base
                            ).model_dump(),
                            "user": (
                                UserModel.model_validate(user).model_dump()
                                if user
                                else None
                            ),
                        }
                    )
                )

            return KnowledgeListResponse(items=knowledge_bases, total=total)

    async def search_knowledge_files(
        self, filter: dict, skip: int = 0, limit: int = 30
    ) -> KnowledgeFileListResponse:
        try:
            async with get_db() as db:
                dialect_name = db.bind.dialect.name
                query = (
                    select(File, User)
                    .join(KnowledgeFile, File.id == KnowledgeFile.file_id)
                    .join(Knowledge, KnowledgeFile.knowledge_id == Knowledge.id)
                    .outerjoin(User, User.id == KnowledgeFile.user_id)
                )

                # Reuse _has_permission logic but targeting Knowledge entity logic
                # The filter dict usually comes populated with user_id and group_ids from the route handler
                query = self._has_permission(query, filter, dialect_name)

                if filter:
                    q = filter.get("query")
                    if q:
                        query = query.where(File.filename.ilike(f"%{q}%"))

                query = query.order_by(File.updated_at.desc())

                count_res = await db.execute(select(func.count()).select_from(query.subquery()))
                total = count_res.scalar() or 0

                if skip:
                    query = query.offset(skip)
                if limit:
                    query = query.limit(limit)

                result = await db.execute(query)
                rows = result.all()

                items = []
                for file, user in rows:
                    items.append(
                        FileUserResponse(
                            **FileModel.model_validate(file).model_dump(),
                            user=(
                                UserResponse(
                                    **UserModel.model_validate(user).model_dump()
                                )
                                if user
                                else None
                            ),
                        )
                    )

                return KnowledgeFileListResponse(items=items, total=total)
        except Exception as e:
            log.exception(f"search_knowledge_files error: {e}")
            return KnowledgeFileListResponse(items=[], total=0)

    async def check_access_by_user_id(self, id: str, user_id: str, permission: str = "write") -> bool:
        knowledge = await self.get_knowledge_by_id(id)
        if not knowledge:
            return False
        if knowledge.user_id == user_id:
            return True
        
        groups = await Groups.get_groups_by_member_id(user_id)
        user_group_ids = {group.id for group in groups}
        
        return has_access(user_id, permission, knowledge.access_control, user_group_ids)

    async def get_knowledge_bases_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[KnowledgeUserModel]:
        knowledge_bases = await self.get_knowledge_bases(skip=0, limit=1000)
        
        groups = await Groups.get_groups_by_member_id(user_id)
        user_group_ids = {group.id for group in groups}
        
        return [
            kb
            for kb in knowledge_bases
            if kb.user_id == user_id
            or has_access(user_id, permission, kb.access_control, user_group_ids)
        ]

    async def get_knowledge_by_id(self, id: str) -> Optional[KnowledgeModel]:
        try:
            async with get_db() as db:
                knowledge = await db.get(Knowledge, id)
                return KnowledgeModel.model_validate(knowledge) if knowledge else None
        except Exception:
            return None

    async def get_knowledge_by_id_and_user_id(
        self, id: str, user_id: str
    ) -> Optional[KnowledgeModel]:
        knowledge = await self.get_knowledge_by_id(id)
        if not knowledge:
            return None
        if knowledge.user_id == user_id:
            return knowledge
        
        groups = await Groups.get_groups_by_member_id(user_id)
        user_group_ids = {group.id for group in groups}
        
        if has_access(user_id, "write", knowledge.access_control, user_group_ids):
            return knowledge
        return None

    async def get_knowledges_by_file_id(self, file_id: str) -> list[KnowledgeModel]:
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(Knowledge)
                    .join(KnowledgeFile, Knowledge.id == KnowledgeFile.knowledge_id)
                    .where(KnowledgeFile.file_id == file_id)
                )
                knowledges = result.scalars().all()
                return [KnowledgeModel.model_validate(k) for k in knowledges]
        except Exception:
            return []

    async def search_files_by_id(
        self,
        knowledge_id: str,
        user_id: str,
        filter: dict,
        skip: int = 0,
        limit: int = 30,
    ) -> KnowledgeFileListResponse:
        try:
            async with get_db() as db:
                query = (
                    select(File, User)
                    .join(KnowledgeFile, File.id == KnowledgeFile.file_id)
                    .outerjoin(User, User.id == KnowledgeFile.user_id)
                    .where(KnowledgeFile.knowledge_id == knowledge_id)
                )

                if filter:
                    query_key = filter.get("query")
                    if query_key:
                        query = query.where(File.filename.ilike(f"%{query_key}%"))

                    view_option = filter.get("view_option")
                    if view_option == "created":
                        query = query.where(KnowledgeFile.user_id == user_id)
                    elif view_option == "shared":
                        query = query.where(KnowledgeFile.user_id != user_id)

                    order_by = filter.get("order_by")
                    direction = filter.get("direction")

                    sort_col = File.updated_at
                    if order_by == "name":
                        sort_col = File.filename
                    elif order_by == "created_at":
                        sort_col = File.created_at
                    elif order_by == "updated_at":
                        sort_col = File.updated_at

                    if direction == "asc":
                        query = query.order_by(sort_col.asc())
                    else:
                        query = query.order_by(sort_col.desc())

                else:
                    query = query.order_by(File.updated_at.desc())

                # Count BEFORE pagination
                count_res = await db.execute(select(func.count()).select_from(query.subquery()))
                total = count_res.scalar() or 0

                if skip:
                    query = query.offset(skip)
                if limit:
                    query = query.limit(limit)

                result = await db.execute(query)
                items = result.all()

                files = []
                for file, user in items:
                    files.append(
                        FileUserResponse(
                            **FileModel.model_validate(file).model_dump(),
                            user=(
                                UserResponse(
                                    **UserModel.model_validate(user).model_dump()
                                )
                                if user
                                else None
                            ),
                        )
                    )

                return KnowledgeFileListResponse(items=files, total=total)
        except Exception as e:
            log.exception(e)
            return KnowledgeFileListResponse(items=[], total=0)

    async def get_files_by_id(self, knowledge_id: str) -> list[FileModel]:
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(File)
                    .join(KnowledgeFile, File.id == KnowledgeFile.file_id)
                    .where(KnowledgeFile.knowledge_id == knowledge_id)
                )
                files = result.scalars().all()
                return [FileModel.model_validate(file) for file in files]
        except Exception:
            return []

    async def get_file_metadatas_by_id(self, knowledge_id: str) -> list[FileMetadataResponse]:
        files = await self.get_files_by_id(knowledge_id)
        return [FileMetadataResponse(**file.model_dump()) for file in files]

    async def add_file_to_knowledge_by_id(
        self, knowledge_id: str, file_id: str, user_id: str
    ) -> Optional[KnowledgeFileModel]:
        knowledge_file = KnowledgeFileModel(
            id=str(uuid.uuid4()),
            knowledge_id=knowledge_id,
            file_id=file_id,
            user_id=user_id,
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )
        try:
            async with get_db() as db:
                result = KnowledgeFile(**knowledge_file.model_dump())
                db.add(result)
                await db.commit()
                await db.refresh(result)
                return KnowledgeFileModel.model_validate(result) if result else None
        except Exception:
            return None

    async def remove_file_from_knowledge_by_id(self, knowledge_id: str, file_id: str) -> bool:
        try:
            async with get_db() as db:
                await db.execute(
                    delete(KnowledgeFile).where(
                        KnowledgeFile.knowledge_id == knowledge_id,
                        KnowledgeFile.file_id == file_id
                    )
                )
                await db.commit()
                return True
        except Exception:
            return False

    async def reset_knowledge_by_id(self, id: str) -> Optional[KnowledgeModel]:
        try:
            async with get_db() as db:
                await db.execute(delete(KnowledgeFile).where(KnowledgeFile.knowledge_id == id))
                await db.execute(
                    update(Knowledge).where(Knowledge.id == id).values(updated_at=int(time.time()))
                )
                await db.commit()
                return await self.get_knowledge_by_id(id)
        except Exception as e:
            log.exception(e)
            return None

    async def update_knowledge_by_id(
        self, id: str, form_data: KnowledgeForm, overwrite: bool = False
    ) -> Optional[KnowledgeModel]:
        try:
            async with get_db() as db:
                await db.execute(
                    update(Knowledge).where(Knowledge.id == id).values(
                        **form_data.model_dump(),
                        updated_at=int(time.time())
                    )
                )
                await db.commit()
                return await self.get_knowledge_by_id(id)
        except Exception as e:
            log.exception(e)
            return None

    async def update_knowledge_data_by_id(
        self, id: str, data: dict
    ) -> Optional[KnowledgeModel]:
        try:
            async with get_db() as db:
                await db.execute(
                    update(Knowledge).where(Knowledge.id == id).values(
                        data=data,
                        updated_at=int(time.time())
                    )
                )
                await db.commit()
                return await self.get_knowledge_by_id(id)
        except Exception as e:
            log.exception(e)
            return None

    async def delete_knowledge_by_id(self, id: str) -> bool:
        try:
            async with get_db() as db:
                await db.execute(delete(Knowledge).where(Knowledge.id == id))
                await db.commit()
                return True
        except Exception:
            return False

    async def delete_all_knowledge(self) -> bool:
        try:
            async with get_db() as db:
                await db.execute(delete(Knowledge))
                await db.commit()
                return True
        except Exception:
            return False


# Module instance
Knowledges = KnowledgesTable()


