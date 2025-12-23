import asyncio
import json
import time
import uuid
from typing import Optional

from open_webui.internal.db import Base, get_db
from open_webui.models.groups import Groups

from pydantic import BaseModel, ConfigDict
from sqlalchemy.dialects.postgresql import JSONB


from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    ForeignKey,
    String,
    Text,
    JSON,
    UniqueConstraint,
    case,
    cast,
)
from sqlalchemy import or_, func, select, and_, text, delete, update
from sqlalchemy.sql import exists

####################
# Channel DB Schema
####################


class Channel(Base):
    __tablename__ = "channel"

    id = Column(Text, primary_key=True, unique=True)
    user_id = Column(Text)
    type = Column(Text, nullable=True)

    name = Column(Text)
    description = Column(Text, nullable=True)

    # Used to indicate if the channel is private (for 'group' type channels)
    is_private = Column(Boolean, nullable=True)

    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)
    access_control = Column(JSON, nullable=True)

    created_at = Column(BigInteger)

    updated_at = Column(BigInteger)
    updated_by = Column(Text, nullable=True)

    archived_at = Column(BigInteger, nullable=True)
    archived_by = Column(Text, nullable=True)

    deleted_at = Column(BigInteger, nullable=True)
    deleted_by = Column(Text, nullable=True)


class ChannelModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str

    type: Optional[str] = None

    name: str
    description: Optional[str] = None

    is_private: Optional[bool] = None

    data: Optional[dict] = None
    meta: Optional[dict] = None
    access_control: Optional[dict] = None

    created_at: int  # timestamp in epoch (time_ns)

    updated_at: int  # timestamp in epoch (time_ns)
    updated_by: Optional[str] = None

    archived_at: Optional[int] = None  # timestamp in epoch (time_ns)
    archived_by: Optional[str] = None

    deleted_at: Optional[int] = None  # timestamp in epoch (time_ns)
    deleted_by: Optional[str] = None


class ChannelMember(Base):
    __tablename__ = "channel_member"

    id = Column(Text, primary_key=True, unique=True)
    channel_id = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False)

    role = Column(Text, nullable=True)
    status = Column(Text, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)

    is_channel_muted = Column(Boolean, nullable=False, default=False)
    is_channel_pinned = Column(Boolean, nullable=False, default=False)

    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)

    invited_at = Column(BigInteger, nullable=True)
    invited_by = Column(Text, nullable=True)

    joined_at = Column(BigInteger)
    left_at = Column(BigInteger, nullable=True)

    last_read_at = Column(BigInteger, nullable=True)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class ChannelMemberModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    user_id: str

    role: Optional[str] = None
    status: Optional[str] = None

    is_active: bool = True

    is_channel_muted: bool = False
    is_channel_pinned: bool = False

    data: Optional[dict] = None
    meta: Optional[dict] = None

    invited_at: Optional[int] = None  # timestamp in epoch (time_ns)
    invited_by: Optional[str] = None

    joined_at: Optional[int] = None  # timestamp in epoch (time_ns)
    left_at: Optional[int] = None  # timestamp in epoch (time_ns)

    last_read_at: Optional[int] = None  # timestamp in epoch (time_ns)

    created_at: Optional[int] = None  # timestamp in epoch (time_ns)
    updated_at: Optional[int] = None  # timestamp in epoch (time_ns)


class ChannelFile(Base):
    __tablename__ = "channel_file"

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text, nullable=False)

    channel_id = Column(
        Text, ForeignKey("channel.id", ondelete="CASCADE"), nullable=False
    )
    message_id = Column(
        Text, ForeignKey("message.id", ondelete="CASCADE"), nullable=True
    )
    file_id = Column(Text, ForeignKey("file.id", ondelete="CASCADE"), nullable=False)

    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("channel_id", "file_id", name="uq_channel_file_channel_file"),
    )


class ChannelFileModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str

    channel_id: str
    file_id: str
    user_id: str

    created_at: int  # timestamp in epoch (time_ns)
    updated_at: int  # timestamp in epoch (time_ns)


class ChannelWebhook(Base):
    __tablename__ = "channel_webhook"

    id = Column(Text, primary_key=True, unique=True)
    channel_id = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False)

    name = Column(Text, nullable=False)
    profile_image_url = Column(Text, nullable=True)

    token = Column(Text, nullable=False)
    last_used_at = Column(BigInteger, nullable=True)

    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)


class ChannelWebhookModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    user_id: str

    name: str
    profile_image_url: Optional[str] = None

    token: str
    last_used_at: Optional[int] = None  # timestamp in epoch (time_ns)

    created_at: int  # timestamp in epoch (time_ns)
    updated_at: int  # timestamp in epoch (time_ns)


####################
# Forms
####################


class ChannelResponse(ChannelModel):
    is_manager: bool = False
    write_access: bool = False

    user_count: Optional[int] = None


class ChannelForm(BaseModel):
    name: str = ""
    description: Optional[str] = None
    is_private: Optional[bool] = None
    data: Optional[dict] = None
    meta: Optional[dict] = None
    access_control: Optional[dict] = None
    group_ids: Optional[list[str]] = None
    user_ids: Optional[list[str]] = None


class CreateChannelForm(ChannelForm):
    type: Optional[str] = None

class ChannelsTable:
    """Native async version of ChannelsTable."""
    
    async def _collect_unique_user_ids(
        self,
        invited_by: str,
        user_ids: Optional[list[str]] = None,
        group_ids: Optional[list[str]] = None,
    ) -> set[str]:
        users = set(user_ids or [])
        users.add(invited_by)

        for group_id in group_ids or []:
            g_users = await Groups.get_group_user_ids_by_id(group_id)
            if g_users:
                users.update(g_users)

        return users

    def _create_membership_models(
        self,
        channel_id: str,
        invited_by: str,
        user_ids: set[str],
    ) -> list[ChannelMember]:
        now = int(time.time_ns())
        memberships = []

        for uid in user_ids:
            model = ChannelMemberModel(
                **{
                    "id": str(uuid.uuid4()),
                    "channel_id": channel_id,
                    "user_id": uid,
                    "status": "joined",
                    "is_active": True,
                    "is_channel_muted": False,
                    "is_channel_pinned": False,
                    "invited_at": now,
                    "invited_by": invited_by,
                    "joined_at": now,
                    "left_at": None,
                    "last_read_at": now,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            memberships.append(ChannelMember(**model.model_dump()))

        return memberships

    async def insert_new_channel(
        self, form_data: CreateChannelForm, user_id: str
    ) -> Optional[ChannelModel]:
        async with get_db() as db:
            channel = ChannelModel(
                **{
                    **form_data.model_dump(),
                    "type": form_data.type if form_data.type else None,
                    "name": form_data.name.lower(),
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "created_at": int(time.time_ns()),
                    "updated_at": int(time.time_ns()),
                }
            )
            new_channel = Channel(**channel.model_dump())

            if form_data.type in ["group", "dm"]:
                users = await self._collect_unique_user_ids(
                    invited_by=user_id,
                    user_ids=form_data.user_ids,
                    group_ids=form_data.group_ids,
                )
                memberships = self._create_membership_models(
                    channel_id=new_channel.id,
                    invited_by=user_id,
                    user_ids=users,
                )

                db.add_all(memberships)
            db.add(new_channel)
            await db.commit()
            return channel

    async def get_channels(self) -> list[ChannelModel]:
        async with get_db() as db:
            result = await db.execute(select(Channel))
            channels = result.scalars().all()
            return [ChannelModel.model_validate(channel) for channel in channels]

    def _has_permission(self, db, query, filter: dict, permission: str = "read"):
        # Helper matches sync version logic
        group_ids = filter.get("group_ids", [])
        user_id = filter.get("user_id")

        dialect_name = db.bind.dialect.name
        conditions = []
        if group_ids or user_id:
            conditions.extend(
                [
                    Channel.access_control.is_(None),
                    cast(Channel.access_control, String) == "null",
                ]
            )

        if user_id:
            conditions.append(Channel.user_id == user_id)

        if group_ids:
            group_conditions = []
            for gid in group_ids:
                if dialect_name == "sqlite":
                    group_conditions.append(
                        Channel.access_control[permission]["group_ids"].contains([gid])
                    )
                elif dialect_name == "postgresql":
                    group_conditions.append(
                        cast(
                            Channel.access_control[permission]["group_ids"],
                            JSONB,
                        ).contains([gid])
                    )
            conditions.append(or_(*group_conditions))

        if conditions:
            query = query.where(or_(*conditions))

        return query

    async def get_channels_by_user_id(self, user_id: str) -> list[ChannelModel]:
        async with get_db() as db:
            user_groups = await Groups.get_groups_by_member_id(user_id)
            user_group_ids = [group.id for group in user_groups]

            membership_channels_res = await db.execute(
                select(Channel)
                .join(ChannelMember, Channel.id == ChannelMember.channel_id)
                .where(
                    Channel.deleted_at.is_(None),
                    Channel.archived_at.is_(None),
                    Channel.type.in_(["group", "dm"]),
                    ChannelMember.user_id == user_id,
                    ChannelMember.is_active.is_(True),
                )
            )
            membership_channels = membership_channels_res.scalars().all()

            query = select(Channel).where(
                Channel.deleted_at.is_(None),
                Channel.archived_at.is_(None),
                or_(
                    Channel.type.is_(None),
                    Channel.type == "",
                    and_(Channel.type != "group", Channel.type != "dm"),
                ),
            )
            query = self._has_permission(
                db, query, {"user_id": user_id, "group_ids": user_group_ids}
            )
            
            standard_channels_res = await db.execute(query)
            standard_channels = standard_channels_res.scalars().all()

            all_channels = list(membership_channels) + list(standard_channels)
            return [ChannelModel.model_validate(c) for c in all_channels]

    async def get_dm_channel_by_user_ids(self, user_ids: list[str]) -> Optional[ChannelModel]:
        async with get_db() as db:
            unique_user_ids = list(set(user_ids))

            match_count = func.sum(
                case(
                    (ChannelMember.user_id.in_(unique_user_ids), 1),
                    else_=0,
                )
            )

            # Subquery logic needs careful translation to async execute
            subquery = (
                select(ChannelMember.channel_id)
                .group_by(ChannelMember.channel_id)
                .having(func.count(ChannelMember.user_id) == len(unique_user_ids))
                .having(match_count == len(unique_user_ids))
                .subquery()
            )

            result = await db.execute(
                    select(Channel)
                    .where(
                        Channel.id.in_(select(subquery)),
                        Channel.type == "dm",
                    )
            )
            channel = result.scalar_one_or_none()
            return ChannelModel.model_validate(channel) if channel else None

    async def add_members_to_channel(
        self,
        channel_id: str,
        invited_by: str,
        user_ids: Optional[list[str]] = None,
        group_ids: Optional[list[str]] = None,
    ) -> list[ChannelMemberModel]:
        async with get_db() as db:
            requested_users = await self._collect_unique_user_ids(
                invited_by, user_ids, group_ids
            )

            existing_users_res = await db.execute(
                select(ChannelMember.user_id)
                .where(ChannelMember.channel_id == channel_id)
            )
            existing_users = set(existing_users_res.scalars().all())

            new_user_ids = requested_users - existing_users
            if not new_user_ids:
                return []

            new_memberships = self._create_membership_models(
                channel_id, invited_by, new_user_ids
            )

            db.add_all(new_memberships)
            await db.commit()

            return [
                ChannelMemberModel.model_validate(membership)
                for membership in new_memberships
            ]

    async def remove_members_from_channel(
        self,
        channel_id: str,
        user_ids: list[str],
    ) -> int:
        async with get_db() as db:
            result = await db.execute(
                delete(ChannelMember)
                .where(
                    ChannelMember.channel_id == channel_id,
                    ChannelMember.user_id.in_(user_ids),
                )
            )
            await db.commit()
            return result.rowcount

    async def is_user_channel_manager(self, channel_id: str, user_id: str) -> bool:
        async with get_db() as db:
            channel = await db.get(Channel, channel_id)
            if channel and channel.user_id == user_id:
                return True

            membership_res = await db.execute(
                select(ChannelMember)
                .where(
                    ChannelMember.channel_id == channel_id,
                    ChannelMember.user_id == user_id,
                    ChannelMember.role == "manager",
                )
            )
            membership = membership_res.scalar_one_or_none()
            return membership is not None

    async def join_channel(
        self, channel_id: str, user_id: str
    ) -> Optional[ChannelMemberModel]:
        async with get_db() as db:
            existing_res = await db.execute(
                select(ChannelMember)
                .where(
                    ChannelMember.channel_id == channel_id,
                    ChannelMember.user_id == user_id,
                )
            )
            existing_membership = existing_res.scalar_one_or_none()
            if existing_membership:
                return ChannelMemberModel.model_validate(existing_membership)

            channel_member = ChannelMemberModel(
                **{
                    "id": str(uuid.uuid4()),
                    "channel_id": channel_id,
                    "user_id": user_id,
                    "status": "joined",
                    "is_active": True,
                    "is_channel_muted": False,
                    "is_channel_pinned": False,
                    "joined_at": int(time.time_ns()),
                    "left_at": None,
                    "last_read_at": int(time.time_ns()),
                    "created_at": int(time.time_ns()),
                    "updated_at": int(time.time_ns()),
                }
            )
            new_membership = ChannelMember(**channel_member.model_dump())

            db.add(new_membership)
            await db.commit()
            return channel_member

    async def leave_channel(self, channel_id: str, user_id: str) -> bool:
        async with get_db() as db:
            membership_res = await db.execute(
                   select(ChannelMember)
                   .where(
                    ChannelMember.channel_id == channel_id,
                    ChannelMember.user_id == user_id,
                )
            )
            membership = membership_res.scalar_one_or_none()
            if not membership:
                return False

            membership.status = "left"
            membership.is_active = False
            membership.left_at = int(time.time_ns())
            membership.updated_at = int(time.time_ns())

            await db.commit()
            return True

    async def get_member_by_channel_and_user_id(
        self, channel_id: str, user_id: str
    ) -> Optional[ChannelMemberModel]:
        async with get_db() as db:
             res = await db.execute(
                 select(ChannelMember).where(
                     ChannelMember.channel_id == channel_id,
                     ChannelMember.user_id == user_id,
                 )
             )
             membership = res.scalar_one_or_none()
             return ChannelMemberModel.model_validate(membership) if membership else None

    async def get_members_by_channel_id(self, channel_id: str) -> list[ChannelMemberModel]:
        async with get_db() as db:
            res = await db.execute(
                select(ChannelMember).where(ChannelMember.channel_id == channel_id)
            )
            memberships = res.scalars().all()
            return [
                ChannelMemberModel.model_validate(membership)
                for membership in memberships
            ]

    async def pin_channel(self, channel_id: str, user_id: str, is_pinned: bool) -> bool:
        async with get_db() as db:
            res = await db.execute(
                select(ChannelMember).where(
                    ChannelMember.channel_id == channel_id,
                    ChannelMember.user_id == user_id,
                )
            )
            membership = res.scalar_one_or_none()
            if not membership:
                return False

            membership.is_channel_pinned = is_pinned
            membership.updated_at = int(time.time_ns())

            await db.commit()
            return True

    async def update_member_last_read_at(self, channel_id: str, user_id: str) -> bool:
        async with get_db() as db:
            res = await db.execute(
                select(ChannelMember).where(
                    ChannelMember.channel_id == channel_id,
                    ChannelMember.user_id == user_id,
                )
            )
            membership = res.scalar_one_or_none()
            if not membership:
                return False

            membership.last_read_at = int(time.time_ns())
            membership.updated_at = int(time.time_ns())
            await db.commit()
            return True

    async def update_member_active_status(
        self, channel_id: str, user_id: str, is_active: bool
    ) -> bool:
        async with get_db() as db:
            res = await db.execute(
                select(ChannelMember).where(
                    ChannelMember.channel_id == channel_id,
                    ChannelMember.user_id == user_id,
                )
            )
            membership = res.scalar_one_or_none()
            if not membership:
                return False

            membership.is_active = is_active
            membership.updated_at = int(time.time_ns())
            await db.commit()
            return True

    async def is_user_channel_member(self, channel_id: str, user_id: str) -> bool:
        async with get_db() as db:
             res = await db.execute(
                 select(ChannelMember).where(
                    ChannelMember.channel_id == channel_id,
                    ChannelMember.user_id == user_id,
                 )
             )
             return res.scalar_one_or_none() is not None

    async def get_channel_by_id(self, id: str) -> Optional[ChannelModel]:
        async with get_db() as db:
            channel = await db.get(Channel, id)
            return ChannelModel.model_validate(channel) if channel else None

    async def get_channels_by_file_id(self, file_id: str) -> list[ChannelModel]:
        async with get_db() as db:
            res = await db.execute(select(ChannelFile).where(ChannelFile.file_id == file_id))
            channel_files = res.scalars().all()
            
            channel_ids = [cf.channel_id for cf in channel_files]
            if not channel_ids:
                return []
                
            res_channels = await db.execute(select(Channel).where(Channel.id.in_(channel_ids)))
            channels = res_channels.scalars().all()
            return [ChannelModel.model_validate(channel) for channel in channels]

    async def get_channels_by_file_id_and_user_id(
        self, file_id: str, user_id: str
    ) -> list[ChannelModel]:
        async with get_db() as db:
            channel_file_res = await db.execute(select(ChannelFile).where(ChannelFile.file_id == file_id))
            channel_file_rows = channel_file_res.scalars().all()
            channel_ids = [row.channel_id for row in channel_file_rows]

            if not channel_ids:
                return []

            channels_res = await db.execute(
                select(Channel)
                .where(
                    Channel.id.in_(channel_ids),
                    Channel.deleted_at.is_(None),
                    Channel.archived_at.is_(None),
                )
            )
            channels = channels_res.scalars().all()
            if not channels:
                return []

            user_groups = await Groups.get_groups_by_member_id(user_id)
            user_group_ids = [g.id for g in user_groups]

            allowed_channels = []

            for channel in channels:
                if channel.type in ["group", "dm"]:
                    membership_res = await db.execute(
                        select(ChannelMember)
                        .where(
                            ChannelMember.channel_id == channel.id,
                            ChannelMember.user_id == user_id,
                            ChannelMember.is_active.is_(True),
                        )
                    )
                    membership = membership_res.scalar_one_or_none()
                    if membership:
                        allowed_channels.append(ChannelModel.model_validate(channel))
                    continue

                query = select(Channel).where(Channel.id == channel.id)
                query = self._has_permission(
                    db,
                    query,
                    {"user_id": user_id, "group_ids": user_group_ids},
                    permission="read",
                )

                allowed_res = await db.execute(query)
                allowed = allowed_res.scalar_one_or_none()
                if allowed:
                    allowed_channels.append(ChannelModel.model_validate(allowed))

            return allowed_channels

    async def get_channel_by_id_and_user_id(
        self, id: str, user_id: str
    ) -> Optional[ChannelModel]:
        async with get_db() as db:
            channel_res = await db.execute(
                select(Channel)
                .where(
                    Channel.id == id,
                    Channel.deleted_at.is_(None),
                    Channel.archived_at.is_(None),
                )
            )
            channel = channel_res.scalar_one_or_none()

            if not channel:
                return None

            if channel.type in ["group", "dm"]:
                 membership_res = await db.execute(
                    select(ChannelMember)
                    .where(
                        ChannelMember.channel_id == id,
                        ChannelMember.user_id == user_id,
                        ChannelMember.is_active.is_(True),
                    )
                )
                 membership = membership_res.scalar_one_or_none()
                 if membership:
                     return ChannelModel.model_validate(channel)
                 else:
                     return None

            # For channels that are NOT group/dm, fall back to ACL-based read access
            # We need user groups to check permission, unless the channel is public/user owned
            if channel.user_id == user_id:
                return ChannelModel.model_validate(channel)
            
            user_groups = await Groups.get_groups_by_member_id(user_id)
            user_group_ids = [g.id for g in user_groups]
            
            # Re-query with permission check or reuse helpers
            query = select(Channel).where(Channel.id == id)
            query = self._has_permission(db, query, {"user_id": user_id, "group_ids": user_group_ids}, "read")
            
            res = await db.execute(query)
            if res.scalar_one_or_none():
                return ChannelModel.model_validate(channel)
                
            return None

    async def delete_channel_by_id(self, id: str):
        async with get_db() as db:
            await db.execute(delete(Channel).where(Channel.id == id))
            await db.commit()
            return True

    async def update_channel_by_id(
        self, id: str, form_data: ChannelForm
    ) -> Optional[ChannelModel]:
        async with get_db() as db:
            channel = await db.get(Channel, id)
            if not channel:
                return None

            channel.name = form_data.name
            channel.description = form_data.description
            channel.is_private = form_data.is_private

            channel.data = form_data.data
            channel.meta = form_data.meta

            channel.access_control = form_data.access_control
            channel.updated_at = int(time.time_ns())

            await db.commit()
            return ChannelModel.model_validate(channel) if channel else None

    async def add_file_to_channel_by_id(
        self, channel_id: str, file_id: str, user_id: str
    ) -> Optional[ChannelFileModel]:
        async with get_db() as db:
            channel_file = ChannelFileModel(
                **{
                    "id": str(uuid.uuid4()),
                    "channel_id": channel_id,
                    "file_id": file_id,
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            try:
                result = ChannelFile(**channel_file.model_dump())
                db.add(result)
                await db.commit()
                await db.refresh(result)
                if result:
                    return ChannelFileModel.model_validate(result)
                else:
                    return None
            except Exception:
                return None

    async def set_file_message_id_in_channel_by_id(
        self, channel_id: str, file_id: str, message_id: str
    ) -> bool:
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(ChannelFile).where(
                        ChannelFile.channel_id == channel_id,
                        ChannelFile.file_id == file_id,
                    )
                )
                channel_file = result.scalar_one_or_none()
                if not channel_file:
                    return False

                channel_file.message_id = message_id
                channel_file.updated_at = int(time.time())

                await db.commit()
                return True
        except Exception:
            return False

    async def remove_file_from_channel_by_id(self, channel_id: str, file_id: str) -> bool:
        try:
            async with get_db() as db:
                await db.execute(
                    delete(ChannelFile).where(
                        ChannelFile.channel_id == channel_id,
                        ChannelFile.file_id == file_id,
                    )
                )
                await db.commit()
                return True
        except Exception:
            return False


# Module instance
Channels = ChannelsTable()

