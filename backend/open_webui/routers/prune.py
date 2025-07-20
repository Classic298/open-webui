import logging
import time
from typing import Optional
import re
import os
import shutil

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

from open_webui.utils.auth import get_admin_user
from open_webui.models.users import Users
from open_webui.models.chats import Chats
from open_webui.models.files import Files
from open_webui.models.notes import Notes
from open_webui.models.prompts import Prompts
from open_webui.models.models import Models
from open_webui.models.knowledge import Knowledges
from open_webui.models.functions import Functions
from open_webui.models.tools import Tools
from open_webui.models.folders import Folders
from open_webui.storage.provider import Storage
from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT, VECTOR_DB
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.config import CACHE_DIR
from open_webui.internal.db import get_db

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
        user_ids = {user.id for user in Users.get_users()["users"]}

        # Files: This section now handles both orphaned DB entries and stranded physical files.
        
        # Step 1: Identify and delete orphaned file records from the database.
        all_files = Files.get_files()
        all_kbs = Knowledges.get_knowledge_bases()

        active_kb_file_ids = set()
        for kb in all_kbs:
            if kb.data and "file_ids" in kb.data:
                active_kb_file_ids.update(kb.data["file_ids"])

        for file in all_files:
            if file.id not in active_kb_file_ids:
                try:
                    log.debug(f"Deleting orphaned file DB entry and associated data for file ID: {file.id}")
                    Storage.delete_file(file.path)
                    VECTOR_DB_CLIENT.delete_collection(collection_name=f"file-{file.id}")
                    Files.delete_file_by_id(file.id)
                except ValueError as e:
                    log.warning(f"Could not delete vector collection for file {file.id} (may already be gone): {e}")
                    if Files.get_file_by_id(file.id):
                        Files.delete_file_by_id(file.id)

        # Step 2: Identify and delete stranded physical files that have no DB record.
        all_file_ids_in_db = {file.id for file in Files.get_files()}
        upload_dir = os.path.join(os.path.dirname(CACHE_DIR), "uploads")
        
        if os.path.exists(upload_dir):
            for filename in os.listdir(upload_dir):
                # Extract UUID from the beginning of the filename
                file_id_match = re.match(r"^([a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})", filename)
                if file_id_match:
                    file_id = file_id_match.group(1)
                    if file_id not in all_file_ids_in_db:
                        try:
                            log.debug(f"Deleting stranded physical file: {filename}")
                            # Delete physical file from /uploads
                            file_path = os.path.join(upload_dir, filename)
                            os.remove(file_path)

                            # Attempt to delete associated vector collection
                            VECTOR_DB_CLIENT.delete_collection(collection_name=f"file-{file_id}")
                        except Exception as e:
                            log.warning(f"Error deleting stranded file {filename} or its vector collection: {e}")

        # Audio
        audio_cache_dir = f"{CACHE_DIR}/audio/transcriptions"
        if os.path.exists(audio_cache_dir):
            shutil.rmtree(audio_cache_dir)

        # Functions
        function_cache_dir = f"{CACHE_DIR}/functions"
        if os.path.exists(function_cache_dir):
            shutil.rmtree(function_cache_dir)

        # Tools
        tool_cache_dir = f"{CACHE_DIR}/tools"
        if os.path.exists(tool_cache_dir):
            shutil.rmtree(tool_cache_dir)

        # Folders
        all_folders = Folders.get_all_folders()
        for folder in all_folders:
            if folder.user_id not in user_ids:
                Folders.delete_folder_by_id_and_user_id(folder.id, folder.user_id)

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
                try:
                    VECTOR_DB_CLIENT.delete_collection(collection_name=knowledge.id)
                    Knowledges.delete_knowledge_by_id(knowledge.id)
                except ValueError as e:
                    log.warning(f"Could not delete vector collection for knowledge base {knowledge.id} (may already be gone): {e}")
                    if Knowledges.get_knowledge_by_id(knowledge.id):
                        Knowledges.delete_knowledge_by_id(knowledge.id)

        # Vacuum the database to reclaim space
        with get_db() as db:
            if db.get_bind().dialect.name == "sqlite":
                db.execute(text("VACUUM"))
            elif db.get_bind().dialect.name == "postgresql":
                db.execute(text("VACUUM"))

        return True
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Error pruning data"),
        )
