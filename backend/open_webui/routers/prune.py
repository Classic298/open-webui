import logging
import time
from typing import Optional
import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from open_webui.utils.auth import get_admin_user
from open_webui.models.users import Users
from open_webui.models.chats import Chats
from open_webui.models.files import Files
from open_webui.models.notes import Notes
from open_webui.models.prompts import Prompts
from open_webui.models.models import Models
from open_webui.models.knowledge import Knowledges
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
    Prunes old and orphaned data from the database.
    """
    try:
        # Prune old chats
        chats_to_delete = Chats.get_chats()

        if form_data.days is not None:
            cutoff_time = int(time.time()) - (form_data.days * 86400)
            chats_to_delete = [
                chat for chat in chats_to_delete if chat.updated_at < cutoff_time
            ]

        if form_data.exempt_archived_chats:
            chats_to_delete = [chat for chat in chats_to_delete if not chat.archived]

        for chat in chats_to_delete:
            Chats.delete_chat_by_id(chat.id)

        # Prune orphaned data
        user_ids = {user.id for user in Users.get_users().users}

        # Files
        all_files = Files.get_files()
        for file in all_files:
            if file.user_id not in user_ids:
                Storage.delete_file(file.path)
                VECTOR_DB_CLIENT.delete(collection_name=f"file-{file.id}")
                Files.delete_file_by_id(file.id)

        # Notes
        all_notes = Notes.get_notes()
        for note in all_notes:
            if note.user_id not in user_ids:
                Notes.delete_note_by_id(note.id)

        # Prompts
        all_prompts = Prompts.get_prompts()
        for prompt in all_prompts:
            if prompt.user_id not in user_ids:
                Prompts.delete_prompt_by_command(prompt.command)

        # Models
        all_models = Models.get_all_models()
        for model in all_models:
            if model.user_id not in user_ids:
                Models.delete_model_by_id(model.id)

        # Knowledge Bases
        all_knowledge = Knowledges.get_knowledge_bases()
        for knowledge in all_knowledge:
            if knowledge.user_id not in user_ids:
                Knowledges.delete_knowledge_by_id(knowledge.id)

        return True
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Error pruning data"),
        )
