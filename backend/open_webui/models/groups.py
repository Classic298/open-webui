import asyncio
import json
import logging
import time
from typing import Optional
import uuid

from open_webui.internal.db import Base, get_db

from open_webui.models.files import FileMetadataResponse


from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    BigInteger,
    Column,
    String,
    Text,
    JSON,
    and_,
    func,
    ForeignKey,
    cast,
    or_,
    select,
    delete,
    update,
)


log = logging.getLogger(__name__)

####################
# UserGroup DB Schema
####################


class Group(Base):
    __tablename__ = "group"

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text)

    name = Column(Text)
    description = Column(Text)

    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)

    permissions = Column(JSON, nullable=True)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class GroupModel(BaseModel):
    id: str
    user_id: str

    name: str
    description: str

    data: Optional[dict] = None
    meta: Optional[dict] = None

    permissions: Optional[dict] = None

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch

    model_config = ConfigDict(from_attributes=True)


class GroupMember(Base):
    __tablename__ = "group_member"

    id = Column(Text, unique=True, primary_key=True)
    group_id = Column(
        Text,
        ForeignKey("group.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(Text, nullable=False)
    created_at = Column(BigInteger, nullable=True)
    updated_at = Column(BigInteger, nullable=True)


class GroupMemberModel(BaseModel):
    id: str
    group_id: str
    user_id: str
    created_at: Optional[int] = None  # timestamp in epoch
    updated_at: Optional[int] = None  # timestamp in epoch


####################
# Forms
####################


class GroupResponse(GroupModel):
    member_count: Optional[int] = None


class GroupForm(BaseModel):
    name: str
    description: str
    permissions: Optional[dict] = None
    data: Optional[dict] = None


class UserIdsForm(BaseModel):
    user_ids: Optional[list[str]] = None


class GroupUpdateForm(GroupForm):
    pass


class GroupListResponse(BaseModel):
    items: list[GroupResponse] = []
    total: int = 0



class GroupsTable:
    """Table class for database operations."""
    
    async def insert_new_group(
        self, user_id: str, form_data: GroupForm
    ) -> Optional[GroupModel]:
        group = GroupModel(
            **{
                **form_data.model_dump(exclude_none=True),
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "created_at": int(time.time()),
                "updated_at": int(time.time()),
            }
        )
        try:
            async with get_db() as db:
                result = Group(**group.model_dump())
                db.add(result)
                await db.commit()
                await db.refresh(result)
                return GroupModel.model_validate(result) if result else None
        except Exception:
            return None

    async def get_all_groups(self) -> list[GroupModel]:
        async with get_db() as db:
            result = await db.execute(select(Group).order_by(Group.updated_at.desc()))
            groups = result.scalars().all()
            return [GroupModel.model_validate(group) for group in groups]

    async def get_groups(self, filter: dict = {}) -> list[GroupResponse]:
        async with get_db() as db:
            query = select(Group)

            if filter:
                if "query" in filter:
                    query = query.where(Group.name.ilike(f"%{filter['query']}%"))
                if "member_id" in filter:
                    query = query.join(
                        GroupMember, GroupMember.group_id == Group.id
                    ).where(GroupMember.user_id == filter["member_id"])

                if "share" in filter:
                    share_value = filter["share"]
                    # Mimicking sync logic for JSON path
                    json_share = Group.data["config"]["share"].as_boolean()

                    if share_value:
                        query = query.where(
                            or_(
                                Group.data.is_(None),
                                json_share.is_(None),
                                json_share == True,
                            )
                        )
                    else:
                        query = query.where(
                            and_(Group.data.isnot(None), json_share == False)
                        )
            
            result = await db.execute(query.order_by(Group.updated_at.desc()))
            groups = result.scalars().all()
            
            items = []
            for group in groups:
                 count = await self.get_group_member_count_by_id(group.id)
                 items.append(
                     GroupResponse.model_validate(
                         {
                             **GroupModel.model_validate(group).model_dump(),
                             "member_count": count
                         }
                     )
                 )
            return items

    async def search_groups(
        self, filter: Optional[dict] = None, skip: int = 0, limit: int = 30
    ) -> GroupListResponse:
        async with get_db() as db:
            query = select(Group)

            if filter:
                if "query" in filter:
                    query = query.where(Group.name.ilike(f"%{filter['query']}%"))
                if "member_id" in filter:
                    query = query.join(
                        GroupMember, GroupMember.group_id == Group.id
                    ).where(GroupMember.user_id == filter["member_id"])

                if "share" in filter:
                    share_value = filter["share"]
                    query = query.where(
                        Group.data.op("->>")("share") == str(share_value)
                    )

            # Count
            count_res = await db.execute(select(func.count()).select_from(query.subquery()))
            total = count_res.scalar() or 0
            
            query = query.order_by(Group.updated_at.desc())
            result = await db.execute(query.offset(skip).limit(limit))
            groups = result.scalars().all()
            
            items = []
            for group in groups:
                 count = await self.get_group_member_count_by_id(group.id)
                 items.append(
                     GroupResponse.model_validate(
                         {
                             **GroupModel.model_validate(group).model_dump(),
                             "member_count": count
                         }
                     )
                 )

            return {
                "items": items,
                "total": total,
            }

    async def get_groups_by_member_id(self, user_id: str) -> list[GroupModel]:
        async with get_db() as db:
            result = await db.execute(
                select(Group)
                .join(GroupMember, GroupMember.group_id == Group.id)
                .where(GroupMember.user_id == user_id)
                .order_by(Group.updated_at.desc())
            )
            groups = result.scalars().all()
            return [GroupModel.model_validate(group) for group in groups]

    async def get_group_by_id(self, id: str) -> Optional[GroupModel]:
        try:
            async with get_db() as db:
                group = await db.get(Group, id)
                return GroupModel.model_validate(group) if group else None
        except Exception:
            return None

    async def get_group_user_ids_by_id(self, id: str) -> Optional[list[str]]:
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(GroupMember.user_id).where(GroupMember.group_id == id)
                )
                members = result.scalars().all()
                if not members:
                    return None
                return list(members)
        except Exception:
            return None

    async def get_group_user_ids_by_ids(self, group_ids: list[str]) -> dict[str, list[str]]:
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(GroupMember.group_id, GroupMember.user_id)
                    .where(GroupMember.group_id.in_(group_ids))
                )
                members = result.fetchall()
                
                group_user_ids = {group_id: [] for group_id in group_ids}
                for group_id, user_id in members:
                    if group_id in group_user_ids:
                        group_user_ids[group_id].append(user_id)
                return group_user_ids
        except Exception:
            return {group_id: [] for group_id in group_ids}

    async def set_group_user_ids_by_id(self, group_id: str, user_ids: list[str]) -> None:
        async with get_db() as db:
            # Delete existing members
            await db.execute(
                delete(GroupMember).where(GroupMember.group_id == group_id)
            )
            
            # Insert new members
            now = int(time.time())
            new_members = [
                GroupMember(
                    id=str(uuid.uuid4()),
                    group_id=group_id,
                    user_id=user_id,
                    created_at=now,
                    updated_at=now,
                )
                for user_id in user_ids
            ]
            
            if new_members:
                db.add_all(new_members)
            await db.commit()

    async def get_group_member_count_by_id(self, id: str) -> int:
        async with get_db() as db:
            result = await db.execute(
                select(func.count(GroupMember.user_id)).where(GroupMember.group_id == id)
            )
            count = result.scalar()
            return count if count else 0

    async def update_group_by_id(
        self, id: str, form_data: GroupUpdateForm, overwrite: bool = False
    ) -> Optional[GroupModel]:
        try:
            async with get_db() as db:
                await db.execute(
                    update(Group)
                    .where(Group.id == id)
                    .values(
                        **form_data.model_dump(exclude_none=True),
                        updated_at=int(time.time()),
                    )
                )
                await db.commit()
                return await self.get_group_by_id(id)
        except Exception as e:
            log.exception(e)
            return None

    async def delete_group_by_id(self, id: str) -> bool:
        try:
            async with get_db() as db:
                await db.execute(delete(Group).where(Group.id == id))
                await db.commit()
                return True
        except Exception:
            return False

    async def delete_all_groups(self) -> bool:
        try:
            async with get_db() as db:
                await db.execute(delete(Group))
                await db.commit()
                return True
        except Exception:
            return False

    async def remove_user_from_all_groups(self, user_id: str) -> bool:
        try:
            async with get_db() as db:
                # Find all groups the user belongs to
                result = await db.execute(
                    select(Group)
                    .join(GroupMember, GroupMember.group_id == Group.id)
                    .where(GroupMember.user_id == user_id)
                )
                groups = result.scalars().all()

                # Remove the user from each group
                for group in groups:
                    await db.execute(
                        delete(GroupMember).where(
                            GroupMember.group_id == group.id,
                            GroupMember.user_id == user_id
                        )
                    )

                    await db.execute(
                        update(Group)
                        .where(Group.id == group.id)
                        .values(updated_at=int(time.time()))
                    )

                await db.commit()
                return True

        except Exception:
            return False

    async def create_groups_by_group_names(
        self, user_id: str, group_names: list[str]
    ) -> list[GroupModel]:
        existing_groups = await self.get_all_groups()
        existing_group_names = {group.name for group in existing_groups}

        new_groups = []

        async with get_db() as db:
            for group_name in group_names:
                if group_name not in existing_group_names:
                    new_group = GroupModel(
                        id=str(uuid.uuid4()),
                        user_id=user_id,
                        name=group_name,
                        description="",
                        created_at=int(time.time()),
                        updated_at=int(time.time()),
                    )
                    try:
                        async with db.begin_nested():
                            result = Group(**new_group.model_dump())
                            db.add(result)
                        await db.refresh(result)
                        new_groups.append(GroupModel.model_validate(result))
                    except Exception as e:
                        log.exception(e)
                        continue
            
            await db.commit()
            return new_groups

    async def sync_groups_by_group_names(self, user_id: str, group_names: list[str]) -> bool:
        async with get_db() as db:
            try:
                now = int(time.time())

                # 1. Groups that SHOULD contain the user
                result = await db.execute(select(Group).where(Group.name.in_(group_names)))
                target_groups = result.scalars().all()
                target_group_ids = {g.id for g in target_groups}

                # 2. Groups the user is CURRENTLY in
                result = await db.execute(
                    select(Group)
                    .join(GroupMember, GroupMember.group_id == Group.id)
                    .where(GroupMember.user_id == user_id)
                )
                existing_groups = result.scalars().all()
                existing_group_ids = {g.id for g in existing_groups}

                # 3. Determine adds + removals
                groups_to_add = target_group_ids - existing_group_ids
                groups_to_remove = existing_group_ids - target_group_ids

                # 4. Remove in one bulk delete
                if groups_to_remove:
                    await db.execute(
                        delete(GroupMember).where(
                            GroupMember.user_id == user_id,
                            GroupMember.group_id.in_(groups_to_remove),
                        )
                    )

                    await db.execute(
                        update(Group).where(Group.id.in_(groups_to_remove)).values(updated_at=now)
                    )

                # 5. Bulk insert missing memberships
                for group_id in groups_to_add:
                    db.add(
                        GroupMember(
                            id=str(uuid.uuid4()),
                            group_id=group_id,
                            user_id=user_id,
                            created_at=now,
                            updated_at=now,
                        )
                    )

                if groups_to_add:
                    await db.execute(
                        update(Group).where(Group.id.in_(groups_to_add)).values(updated_at=now)
                    )

                await db.commit()
                return True

            except Exception as e:
                log.exception(e)
                return False

    async def add_users_to_group(
        self, id: str, user_ids: Optional[list[str]] = None
    ) -> Optional[GroupModel]:
        try:
            async with get_db() as db:
                group = await db.get(Group, id)
                if not group:
                    return None

                now = int(time.time())

                for user_id in user_ids or []:
                    # Check if user is already in the group to avoid UniqueViolation
                    existing = await db.execute(
                        select(GroupMember).where(
                            GroupMember.group_id == id,
                            GroupMember.user_id == user_id
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue
                    
                    db.add(
                        GroupMember(
                            id=str(uuid.uuid4()),
                            group_id=id,
                            user_id=user_id,
                            created_at=now,
                            updated_at=now,
                        )
                    )

                await db.execute(
                    update(Group).where(Group.id == id).values(updated_at=now)
                )
                await db.commit()
                await db.refresh(group)

                return GroupModel.model_validate(group)

        except Exception as e:
            log.exception(e)
            return None

    async def remove_users_from_group(
        self, id: str, user_ids: Optional[list[str]] = None
    ) -> Optional[GroupModel]:
        try:
            async with get_db() as db:
                group = await db.get(Group, id)
                if not group:
                    return None

                if not user_ids:
                    return GroupModel.model_validate(group)

                # Remove each user from group_member
                await db.execute(
                    delete(GroupMember).where(
                        GroupMember.group_id == id,
                        GroupMember.user_id.in_(user_ids)
                    )
                )

                # Update group timestamp
                await db.execute(
                    update(Group).where(Group.id == id).values(updated_at=int(time.time()))
                )

                await db.commit()
                await db.refresh(group)
                return GroupModel.model_validate(group)

        except Exception as e:
            log.exception(e)
            return None


# Module instance
Groups = GroupsTable()


