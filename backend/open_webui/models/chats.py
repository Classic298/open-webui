import asyncio
import logging
import json
import time
import uuid
from typing import Optional

from open_webui.internal.db import Base, get_db
from open_webui.models.tags import TagModel, Tag, Tags
from open_webui.models.folders import Folders
from open_webui.utils.misc import sanitize_data_for_db, sanitize_text_for_db

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    ForeignKey,
    String,
    Text,
    JSON,
    Index,
    UniqueConstraint,
    delete,
    update,
)
from sqlalchemy import or_, func, select, and_, text
from sqlalchemy.sql import exists
from sqlalchemy.sql.expression import bindparam

####################
# Chat DB Schema
####################

log = logging.getLogger(__name__)


class Chat(Base):
    __tablename__ = "chat"

    id = Column(String, primary_key=True, unique=True)
    user_id = Column(String)
    title = Column(Text)
    chat = Column(JSON)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)

    share_id = Column(Text, unique=True, nullable=True)
    archived = Column(Boolean, default=False)
    pinned = Column(Boolean, default=False, nullable=True)

    meta = Column(JSON, server_default="{}")
    folder_id = Column(Text, nullable=True)

    __table_args__ = (
        # Performance indexes for common queries
        # WHERE folder_id = ...
        Index("folder_id_idx", "folder_id"),
        # WHERE user_id = ... AND pinned = ...
        Index("user_id_pinned_idx", "user_id", "pinned"),
        # WHERE user_id = ... AND archived = ...
        Index("user_id_archived_idx", "user_id", "archived"),
        # WHERE user_id = ... ORDER BY updated_at DESC
        Index("updated_at_user_id_idx", "updated_at", "user_id"),
        # WHERE folder_id = ... AND user_id = ...
        Index("folder_id_user_id_idx", "folder_id", "user_id"),
    )


class ChatModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    title: str
    chat: dict

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch

    share_id: Optional[str] = None
    archived: bool = False
    pinned: Optional[bool] = False

    meta: dict = {}
    folder_id: Optional[str] = None


class ChatFile(Base):
    __tablename__ = "chat_file"

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text, nullable=False)

    chat_id = Column(Text, ForeignKey("chat.id", ondelete="CASCADE"), nullable=False)
    message_id = Column(Text, nullable=True)
    file_id = Column(Text, ForeignKey("file.id", ondelete="CASCADE"), nullable=False)

    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("chat_id", "file_id", name="uq_chat_file_chat_file"),
    )


class ChatFileModel(BaseModel):
    id: str
    user_id: str

    chat_id: str
    message_id: Optional[str] = None
    file_id: str

    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################


class ChatForm(BaseModel):
    chat: dict
    folder_id: Optional[str] = None


class ChatImportForm(ChatForm):
    meta: Optional[dict] = {}
    pinned: Optional[bool] = False
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


class ChatsImportForm(BaseModel):
    chats: list[ChatImportForm]


class ChatTitleMessagesForm(BaseModel):
    title: str
    messages: list[dict]


class ChatTitleForm(BaseModel):
    title: str


class ChatResponse(BaseModel):
    id: str
    user_id: str
    title: str
    chat: dict
    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch
    share_id: Optional[str] = None  # id of the chat to be shared
    archived: bool
    pinned: Optional[bool] = False
    meta: dict = {}
    folder_id: Optional[str] = None


class ChatTitleIdResponse(BaseModel):
    id: str
    title: str
    updated_at: int
    created_at: int


class ChatListResponse(BaseModel):
    items: list[ChatModel]
    total: int


class ChatUsageStatsResponse(BaseModel):
    id: str  # chat id

    models: dict = {}  # models used in the chat with their usage counts
    message_count: int  # number of messages in the chat

    history_models: dict = {}  # models used in the chat history with their usage counts
    history_message_count: int  # number of messages in the chat history
    history_user_message_count: int  # number of user messages in the chat history
    history_assistant_message_count: (
        int  # number of assistant messages in the chat history
    )

    average_response_time: (
        float  # average response time of assistant messages in seconds
    )
    average_user_message_content_length: (
        float  # average length of user message contents
    )
    average_assistant_message_content_length: (
        float  # average length of assistant message contents
    )

    tags: list[str] = []  # tags associated with the chat

    last_message_at: int  # timestamp of the last message
    updated_at: int
    created_at: int

    model_config = ConfigDict(extra="allow")


class ChatUsageStatsListResponse(BaseModel):
    items: list[ChatUsageStatsResponse]
    total: int
    model_config = ConfigDict(extra="allow")

class ChatsTable:
    """Native async version of ChatsTable."""
    
    def _clean_null_bytes(self, obj):
        return sanitize_data_for_db(obj)

    def _sanitize_chat_row(self, chat_item):
        changed = False
        if chat_item.title:
            cleaned = self._clean_null_bytes(chat_item.title)
            if cleaned != chat_item.title:
                chat_item.title = cleaned
                changed = True
        if chat_item.chat:
            cleaned = self._clean_null_bytes(chat_item.chat)
            if cleaned != chat_item.chat:
                chat_item.chat = cleaned
                changed = True
        return changed

    async def insert_new_chat(self, user_id: str, form_data: ChatForm) -> Optional[ChatModel]:
        async with get_db() as db:
            id = str(uuid.uuid4())
            new_chat = ChatModel(
                **{
                    "id": id,
                    "user_id": user_id,
                    "title": self._clean_null_bytes(form_data.chat.get("title", "New Chat")),
                    "chat": self._clean_null_bytes(form_data.chat),
                    "folder_id": form_data.folder_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )
            chat_item = Chat(**new_chat.model_dump())
            db.add(chat_item)
            await db.commit()
            await db.refresh(chat_item)
            return ChatModel.model_validate(chat_item)

    async def import_chats(self, user_id: str, chat_import_forms: list[ChatImportForm]) -> list[ChatModel]:
        async with get_db() as db:
            chats = []
            for form_data in chat_import_forms:
                chat_model = ChatModel(
                    **{
                        "id": str(uuid.uuid4()),
                        "user_id": user_id,
                        "title": self._clean_null_bytes(form_data.chat.get("title", "New Chat")),
                        "chat": self._clean_null_bytes(form_data.chat),
                        "meta": form_data.meta,
                        "pinned": form_data.pinned,
                        "folder_id": form_data.folder_id,
                        "created_at": form_data.created_at or int(time.time()),
                        "updated_at": form_data.updated_at or int(time.time()),
                    }
                )
                chats.append(Chat(**chat_model.model_dump()))
            
            db.add_all(chats)
            await db.commit()
            return [ChatModel.model_validate(chat) for chat in chats]

    async def get_chat_by_id(self, id: str) -> Optional[ChatModel]:
        try:
            async with get_db() as db:
                chat_item = await db.get(Chat, id)
                if not chat_item:
                    return None
                
                if self._sanitize_chat_row(chat_item):
                    await db.commit()
                    await db.refresh(chat_item)
                
                return ChatModel.model_validate(chat_item)
        except Exception:
            return None

    async def get_chat_by_id_and_user_id(self, id: str, user_id: str) -> Optional[ChatModel]:
        try:
            async with get_db() as db:
                result = await db.execute(select(Chat).where(Chat.id == id, Chat.user_id == user_id))
                chat = result.scalar_one_or_none()
                return ChatModel.model_validate(chat) if chat else None
        except Exception:
            return None

    async def get_chats_by_user_id(self, user_id: str, skip: Optional[int] = None, limit: Optional[int] = None) -> ChatListResponse:
        async with get_db() as db:
            query = select(Chat).where(Chat.user_id == user_id).order_by(Chat.updated_at.desc())
            
            count_query = select(func.count()).select_from(Chat).where(Chat.user_id == user_id)
            total_res = await db.execute(count_query)
            total = total_res.scalar() or 0

            if skip:
                query = query.offset(skip)
            if limit:
                query = query.limit(limit)
                
            result = await db.execute(query)
            chats = result.scalars().all()
            return ChatListResponse(items=[ChatModel.model_validate(c) for c in chats], total=total)

    async def update_chat_by_id(self, id: str, chat: dict) -> Optional[ChatModel]:
        try:
            async with get_db() as db:
                chat_item = await db.get(Chat, id)
                if chat_item:
                    chat_item.chat = self._clean_null_bytes(chat)
                    chat_item.title = self._clean_null_bytes(chat.get("title", "New Chat"))
                    chat_item.updated_at = int(time.time())
                    await db.commit()
                    await db.refresh(chat_item)
                    return ChatModel.model_validate(chat_item)
                return None
        except Exception:
            return None

    async def delete_chat_by_id(self, id: str) -> bool:
        try:
            async with get_db() as db:
                await db.execute(delete(Chat).where(Chat.id == id))
                await db.commit()
                # Assuming cascade deletes chat files. 
                # Also delete shared
                await self.delete_shared_chat_by_chat_id(id)
                return True
        except Exception:
            return False

    async def delete_chat_by_id_and_user_id(self, id: str, user_id: str) -> bool:
        try:
            async with get_db() as db:
                result = await db.execute(delete(Chat).where(Chat.id == id, Chat.user_id == user_id))
                await db.commit()
                # delete shared
                await self.delete_shared_chat_by_chat_id(id)
                return True
        except Exception:
            return False
            
    async def delete_chats_by_user_id(self, user_id: str) -> bool:
        try:
            async with get_db() as db:
                # Delete shared chats first
                await self.delete_shared_chats_by_user_id(user_id)
                
                await db.execute(delete(Chat).where(Chat.user_id == user_id))
                await db.commit()
                return True
        except Exception:
            return False

    async def get_chat_title_id_list_by_user_id(
        self,
        user_id: str,
        include_archived: bool = False,
        include_folders: bool = False,
        include_pinned: bool = False,
        skip: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> list[ChatTitleIdResponse]:
        async with get_db() as db:
            query = select(Chat.id, Chat.title, Chat.updated_at, Chat.created_at).where(Chat.user_id == user_id)
            
            if not include_folders:
                query = query.where(Chat.folder_id == None)
            if not include_pinned:
                query = query.where(or_(Chat.pinned == False, Chat.pinned == None))
            if not include_archived:
                query = query.where(Chat.archived == False)
                
            query = query.order_by(Chat.updated_at.desc())
            
            if skip:
                query = query.offset(skip)
            if limit:
                query = query.limit(limit)
                
            result = await db.execute(query)
            rows = result.all()
            return [ChatTitleIdResponse(id=r[0], title=r[1], updated_at=r[2], created_at=r[3]) for r in rows]

    async def get_pinned_chats_by_user_id(self, user_id: str) -> list[ChatModel]:
        async with get_db() as db:
            result = await db.execute(
                select(Chat).where(Chat.user_id == user_id, Chat.pinned == True, Chat.archived == False).order_by(Chat.updated_at.desc())
            )
            return [ChatModel.model_validate(c) for c in result.scalars().all()]

    async def get_archived_chats_by_user_id(self, user_id: str) -> list[ChatModel]:
        async with get_db() as db:
            result = await db.execute(
                select(Chat).where(Chat.user_id == user_id, Chat.archived == True).order_by(Chat.updated_at.desc())
            )
            return [ChatModel.model_validate(c) for c in result.scalars().all()]
            
    async def get_chats(self, skip: int = 0, limit: int = 50) -> list[ChatModel]:
        async with get_db() as db:
             result = await db.execute(select(Chat).order_by(Chat.updated_at.desc()).offset(skip).limit(limit))
             return [ChatModel.model_validate(c) for c in result.scalars().all()]

    async def archive_all_chats_by_user_id(self, user_id: str) -> bool:
        try:
            async with get_db() as db:
                await db.execute(update(Chat).where(Chat.user_id == user_id).values(archived=True))
                await db.commit()
                return True
        except Exception:
            return False

    async def unarchive_all_chats_by_user_id(self, user_id: str) -> bool:
        try:
            async with get_db() as db:
                await db.execute(update(Chat).where(Chat.user_id == user_id).values(archived=False))
                await db.commit()
                return True
        except Exception:
            return False

    async def get_chat_list_by_user_id(
        self,
        user_id: str,
        include_archived: bool = False,
        filter: Optional[dict] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[ChatModel]:
        async with get_db() as db:
            query = select(Chat).where(Chat.user_id == user_id)
            if not include_archived:
                query = query.where(Chat.archived == False)

            if filter:
                if filter.get("query"):
                    query = query.where(Chat.title.ilike(f"%{filter['query']}%"))
                
                order_by = filter.get("order_by")
                direction = filter.get("direction")
                if order_by and direction:
                    col = getattr(Chat, order_by, None)
                    if col:
                        if direction.lower() == "asc":
                            query = query.order_by(col.asc())
                        else:
                            query = query.order_by(col.desc())
            else:
                 query = query.order_by(Chat.updated_at.desc())

            query = query.offset(skip).limit(limit)
            result = await db.execute(query)
            return [ChatModel.model_validate(c) for c in result.scalars().all()]
            
    async def get_archived_chat_list_by_user_id(
        self,
        user_id: str,
        filter: Optional[dict] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[ChatModel]:
        async with get_db() as db:
            query = select(Chat).where(Chat.user_id == user_id, Chat.archived == True)
            
            if filter:
                if filter.get("query"):
                    query = query.where(Chat.title.ilike(f"%{filter['query']}%"))
                
                order_by = filter.get("order_by")
                direction = filter.get("direction")
                if order_by and direction:
                    col = getattr(Chat, order_by, None)
                    if col:
                        if direction.lower() == "asc":
                            query = query.order_by(col.asc())
                        else:
                            query = query.order_by(col.desc())
            else:
                query = query.order_by(Chat.updated_at.desc())
                
            if skip:
                 query = query.offset(skip)
            if limit:
                 query = query.limit(limit)
                 
            result = await db.execute(query)
            return [ChatModel.model_validate(c) for c in result.scalars().all()]

    async def get_chat_by_share_id(self, id: str) -> Optional[ChatModel]:
        async with get_db() as db:
            result = await db.execute(select(Chat).where(Chat.share_id == id))
            chat = result.scalar_one_or_none()
            if chat:
                 return ChatModel.model_validate(chat)
            return None

    async def update_chat_share_id_by_id(self, id: str, share_id: Optional[str]) -> Optional[ChatModel]:
        try:
            async with get_db() as db:
                chat = await db.get(Chat, id)
                if chat:
                    chat.share_id = share_id
                    await db.commit()
                    await db.refresh(chat)
                    return ChatModel.model_validate(chat)
                return None
        except Exception:
             return None
             
    async def toggle_chat_pinned_by_id(self, id: str) -> Optional[ChatModel]:
        try:
            async with get_db() as db:
                chat = await db.get(Chat, id)
                if chat:
                    chat.pinned = not chat.pinned
                    chat.updated_at = int(time.time())
                    await db.commit()
                    await db.refresh(chat)
                    return ChatModel.model_validate(chat)
                return None
        except Exception:
            return None

    async def upsert_message_to_chat_by_id_and_message_id(self, id: str, message_id: str, message: dict) -> Optional[ChatModel]:
        async with get_db() as db:
             chat_item = await db.get(Chat, id)
             if not chat_item: 
                 return None
             
             if isinstance(message.get("content"), str):
                 message["content"] = sanitize_text_for_db(message["content"])
                 
             chat_data = chat_item.chat
             history = chat_data.get("history", {})
             msgs = history.get("messages", {})
             
             if message_id in msgs:
                 msgs[message_id].update(message)
             else:
                 msgs[message_id] = message
                 
             history["messages"] = msgs
             history["currentId"] = message_id
             chat_data["history"] = history
             
             chat_item.chat = chat_data
             chat_item.updated_at = int(time.time())
             
             await db.commit()
             await db.refresh(chat_item)
             return ChatModel.model_validate(chat_item)

    async def get_chats_by_user_id_and_search_text(
        self,
        user_id: str,
        search_text: str,
        skip: int = 0,
        limit: int = 50,
    ) -> list[ChatModel]:
        async with get_db() as db:
             query = select(Chat).where(Chat.user_id == user_id)
             if search_text:
                 query = query.where(Chat.title.ilike(f"%{search_text}%"))
             
             query = query.order_by(Chat.updated_at.desc()).offset(skip).limit(limit)
             result = await db.execute(query)
             return [ChatModel.model_validate(c) for c in result.scalars().all()]

    async def get_chats_by_folder_ids_and_user_id(self, folder_ids: list[str], user_id: str) -> list[ChatModel]:
        async with get_db() as db:
             result = await db.execute(select(Chat).where(Chat.user_id == user_id, Chat.folder_id.in_(folder_ids)).order_by(Chat.updated_at.desc()))
             return [ChatModel.model_validate(c) for c in result.scalars().all()]
             
    async def get_chats_by_folder_id_and_user_id(self, folder_id: str, user_id: str, skip: int = 0, limit: int = 50) -> list[ChatModel]:
         async with get_db() as db:
             result = await db.execute(
                 select(Chat).where(Chat.user_id == user_id, Chat.folder_id == folder_id)
                 .order_by(Chat.updated_at.desc()).offset(skip).limit(limit)
             )
             return [ChatModel.model_validate(c) for c in result.scalars().all()]

    async def get_chat_list_by_user_id_and_tag_name(
        self, user_id: str, tag_name: str, skip: int = 0, limit: int = 50
    ) -> list[ChatModel]:
        async with get_db() as db:
            query = select(Chat).where(Chat.user_id == user_id, Chat.archived == False)
            tag_id = tag_name.replace(" ", "_").lower()

            if db.bind.dialect.name == "sqlite":
                query = query.where(
                    text(
                        f"EXISTS (SELECT 1 FROM json_each(Chat.meta, '$.tags') WHERE json_each.value = :tag_id)"
                    )
                ).params(tag_id=tag_id)
            elif db.bind.dialect.name == "postgresql":
                query = query.where(
                    text(
                        "EXISTS (SELECT 1 FROM json_array_elements_text(Chat.meta->'tags') elem WHERE elem = :tag_id)"
                    )
                ).params(tag_id=tag_id)

            query = query.order_by(Chat.updated_at.desc()).offset(skip).limit(limit)
            result = await db.execute(query)
            return [ChatModel.model_validate(c) for c in result.scalars().all()]

    async def add_chat_tag_by_id_and_user_id_and_tag_name(
        self, id: str, user_id: str, tag_name: str
    ) -> Optional[ChatModel]:
        tag = await Tags.get_tag_by_name_and_user_id(tag_name, user_id)
        if tag is None:
            tag = await Tags.insert_new_tag(tag_name, user_id)
        
        if tag is None:
            return None

        try:
            async with get_db() as db:
                chat = await db.get(Chat, id)
                if not chat:
                    return None

                tag_id = tag.id
                meta = dict(chat.meta or {})
                tags = list(meta.get("tags", []))

                if tag_id not in tags:
                    tags.append(tag_id)
                    meta["tags"] = tags
                    chat.meta = meta
                    await db.commit()
                    await db.refresh(chat)

                return ChatModel.model_validate(chat)
        except Exception:
            return None

    async def count_chats_by_tag_name_and_user_id(self, tag_name: str, user_id: str) -> int:
        async with get_db() as db:
            query = (
                select(func.count())
                .select_from(Chat)
                .where(Chat.user_id == user_id, Chat.archived == False)
            )

            tag_id = tag_name.replace(" ", "_").lower()

            if db.bind.dialect.name == "sqlite":
                query = query.where(
                    text(
                        f"EXISTS (SELECT 1 FROM json_each(Chat.meta, '$.tags') WHERE json_each.value = :tag_id)"
                    )
                ).params(tag_id=tag_id)
            elif db.bind.dialect.name == "postgresql":
                query = query.where(
                    text(
                        "EXISTS (SELECT 1 FROM json_array_elements_text(Chat.meta->'tags') elem WHERE elem = :tag_id)"
                    )
                ).params(tag_id=tag_id)

            result = await db.execute(query)
            return result.scalar() or 0

    async def count_chats_by_folder_id_and_user_id(self, folder_id: str, user_id: str) -> int:
        async with get_db() as db:
            query = select(func.count()).select_from(Chat).where(
                Chat.user_id == user_id,
                Chat.folder_id == folder_id
            )
            result = await db.execute(query)
            return result.scalar() or 0

    async def delete_tag_by_id_and_user_id_and_tag_name(
        self, id: str, user_id: str, tag_name: str
    ) -> bool:
        try:
            async with get_db() as db:
                chat = await db.get(Chat, id)
                if not chat or chat.user_id != user_id:
                    return False

                tag_id = tag_name.replace(" ", "_").lower()
                meta = dict(chat.meta or {})
                tags = list(meta.get("tags", []))

                if tag_id in tags:
                    tags = [t for t in tags if t != tag_id]
                    meta["tags"] = tags
                    chat.meta = meta
                    await db.commit()
                    return True
                return False
        except Exception:
            return False

    async def delete_all_tags_by_id_and_user_id(self, id: str, user_id: str) -> bool:
        try:
            async with get_db() as db:
                chat = await db.get(Chat, id)
                if not chat or chat.user_id != user_id:
                    return False

                meta = dict(chat.meta or {})
                meta["tags"] = []
                chat.meta = meta
                await db.commit()
                return True
        except Exception:
            return False
    
    async def delete_chats_by_user_id_and_folder_id(
        self, user_id: str, folder_id: str
    ) -> bool:
        try:
            async with get_db() as db:
                await db.execute(
                    delete(Chat).where(Chat.user_id == user_id, Chat.folder_id == folder_id)
                )
                await db.commit()
                return True
        except Exception:
            return False

    async def move_chats_by_user_id_and_folder_id(
        self, user_id: str, folder_id: str, new_folder_id: Optional[str]
    ) -> bool:
        try:
            async with get_db() as db:
                await db.execute(
                    update(Chat)
                    .where(Chat.user_id == user_id, Chat.folder_id == folder_id)
                    .values(folder_id=new_folder_id)
                )
                await db.commit()
                return True
        except Exception:
            return False

    async def insert_chat_files(
        self, chat_id: str, message_id: str, file_ids: list[str], user_id: str
    ) -> Optional[list[ChatFileModel]]:
        if not file_ids:
            return None

        # Logic to check existing files if needed. 
        # For simplicity, following the sync pattern but making it async.
        existing_files = await self.get_chat_files_by_chat_id_and_message_id(chat_id, message_id)
        chat_message_file_ids = [item.id for item in existing_files]
        
        file_ids = list(
            set(
                [
                    file_id
                    for file_id in file_ids
                    if file_id and file_id not in chat_message_file_ids
                ]
            )
        )
        if not file_ids:
            return None

        try:
            async with get_db() as db:
                now = int(time.time())
                chat_files = [
                    ChatFileModel(
                        id=str(uuid.uuid4()),
                        user_id=user_id,
                        chat_id=chat_id,
                        message_id=message_id,
                        file_id=file_id,
                        created_at=now,
                        updated_at=now,
                    )
                    for file_id in file_ids
                ]

                results = [ChatFile(**chat_file.model_dump()) for chat_file in chat_files]
                db.add_all(results)
                await db.commit()
                return chat_files
        except Exception:
            return None

    async def get_chat_files_by_chat_id_and_message_id(
        self, chat_id: str, message_id: str
    ) -> list[ChatFileModel]:
        async with get_db() as db:
            result = await db.execute(
                select(ChatFile)
                .where(ChatFile.chat_id == chat_id, ChatFile.message_id == message_id)
                .order_by(ChatFile.created_at.asc())
            )
            all_chat_files = result.scalars().all()
            return [ChatFileModel.model_validate(chat_file) for chat_file in all_chat_files]

    async def delete_chat_file(self, chat_id: str, file_id: str) -> bool:
        try:
            async with get_db() as db:
                await db.execute(
                    delete(ChatFile).where(ChatFile.chat_id == chat_id, ChatFile.file_id == file_id)
                )
                await db.commit()
                return True
        except Exception:
            return False

    async def get_shared_chats_by_file_id(self, file_id: str) -> list[ChatModel]:
        async with get_db() as db:
            result = await db.execute(
                select(Chat)
                .join(ChatFile, Chat.id == ChatFile.chat_id)
                .where(ChatFile.file_id == file_id, Chat.share_id.isnot(None))
            )
            all_chats = result.scalars().all()
            return [ChatModel.model_validate(chat) for chat in all_chats]

    async def insert_shared_chat_by_chat_id(self, chat_id: str) -> Optional[ChatModel]:
        async with get_db() as db:
            chat = await db.get(Chat, chat_id)
            if not chat:
                return None
            
            if chat.share_id:
                res = await db.execute(select(Chat).where(Chat.share_id == chat.share_id))
                return ChatModel.model_validate(res.scalar_one_or_none())
                
            shared_chat = ChatModel(
                **{
                    "id": str(uuid.uuid4()),
                    "user_id": f"shared-{chat_id}",
                    "title": chat.title,
                    "chat": chat.chat,
                    "meta": chat.meta,
                    "pinned": chat.pinned,
                    "folder_id": chat.folder_id,
                    "created_at": chat.created_at,
                    "updated_at": int(time.time()),
                }
            )
            shared_result = Chat(**shared_chat.model_dump())
            db.add(shared_result)
            chat.share_id = shared_chat.id
            await db.commit()
            await db.refresh(shared_result)
            return shared_chat

    async def delete_shared_chat_by_chat_id(self, chat_id: str) -> bool:
        try:
            async with get_db() as db:
                await db.execute(delete(Chat).where(Chat.user_id == f"shared-{chat_id}"))
                await db.commit()
                return True
        except Exception:
            return False

    async def delete_shared_chats_by_user_id(self, user_id: str) -> bool:
        try:
            async with get_db() as db:
                result = await db.execute(select(Chat).where(Chat.user_id == user_id))
                chats = result.scalars().all()
                shared_chat_ids = [f"shared-{chat.id}" for chat in chats]
                
                if shared_chat_ids:
                    await db.execute(delete(Chat).where(Chat.user_id.in_(shared_chat_ids)))
                    await db.commit()
                return True
        except Exception:
            return False


# Module instance
Chats = ChatsTable()
