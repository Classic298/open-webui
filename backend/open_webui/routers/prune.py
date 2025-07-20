import logging
import time
from typing import Optional
import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from open_webui.utils.auth import get_admin_user
from open_webui.models.chats import Chats, ChatModel
from open_webui.models.files import Files
from open_webui.storage.provider import Storage
from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()


class PruneDataForm(BaseModel):
    days: Optional[int] = None
    exempt_archived_chats: bool = False


@router.post("/", response_model=bool)
async def prune_data(form_data: PruneDataForm, user=Depends(get_admin_user)):
    """
    Prunes old data from the database.
    """
    try:
        chats_to_delete = Chats.get_chats()

        if form_data.days is not None:
            cutoff_time = int(time.time()) - (form_data.days * 86400)
            chats_to_delete = [
                chat for chat in chats_to_delete if chat.updated_at < cutoff_time
            ]

        if form_data.exempt_archived_chats:
            chats_to_delete = [chat for chat in chats_to_delete if not chat.archived]

        for chat in chats_to_delete:
            # Find file IDs in the chat
            file_ids = re.findall(
                r'"file_id":\s*"([^"]+)"', str(chat.chat)
            )

            # Delete associated files
            for file_id in file_ids:
                file = Files.get_file_by_id(file_id)
                if file:
                    Storage.delete_file(file.path)
                    VECTOR_DB_CLIENT.delete(collection_name=f"file-{file_id}")
                    Files.delete_file_by_id(file_id)

            # Delete the chat
            Chats.delete_chat_by_id(chat.id)

        # Now, let's clean up orphaned files that are not associated with any chats
        all_files = Files.get_files()
        all_chats = Chats.get_chats()

        referenced_file_ids = set()
        for chat in all_chats:
            file_ids = re.findall(
                r'"file_id":\s*"([^"]+)"', str(chat.chat)
            )
            referenced_file_ids.update(file_ids)

        for file in all_files:
            if file.id not in referenced_file_ids:
                Storage.delete_file(file.path)
                VECTOR_DB_CLIENT.delete(collection_name=f"file-{file.id}")
                Files.delete_file_by_id(file.id)

        return True
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Error pruning data"),
        )
