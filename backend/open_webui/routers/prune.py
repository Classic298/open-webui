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
    Prunes old and orphaned data from the database in a comprehensive, multi-stage process.
    """
    try:
        # Stage 1: Prune old chats as defined by user criteria.
        # This is the primary driver for orphaning other data.
        log.info("Pruning process started.")
        chats_to_delete = Chats.get_chats()
        if form_data.days is not None:
            cutoff_time = int(time.time()) - (form_data.days * 86400)
            chats_to_delete = [
                chat for chat in chats_to_delete if chat.updated_at < cutoff_time
            ]
        if form_data.exempt_archived_chats:
            chats_to_delete = [chat for chat in chats_to_delete if not chat.archived]
        
        if chats_to_delete:
            log.info(f"Pruning {len(chats_to_delete)} old chat(s).")
            for chat in chats_to_delete:
                Chats.delete_chat_by_id(chat.id)

        # Stage 2: Logical Pruning.
        # Use a single, authoritative snapshot of the current state to determine what's an orphan.
        log.info("Starting logical pruning of orphaned database records.")
        
        # Source of Truth: Active users and active knowledge bases define what should be kept.
        user_ids = {user.id for user in Users.get_users()["users"]}
        all_kbs = Knowledges.get_knowledge_bases()
        active_kb_file_ids = {
            fid for kb in all_kbs if kb.data and "file_ids" in kb.data for fid in kb.data["file_ids"]
        }

        # Prune File records that are not in any active KB or belong to a deleted user.
        for file in Files.get_files():
            if file.id not in active_kb_file_ids or file.user_id not in user_ids:
                log.debug(f"Logically pruning file record: {file.id}")
                try:
                    VECTOR_DB_CLIENT.delete_collection(collection_name=f"file-{file.id}")
                except ValueError:
                    pass  # It's okay if the collection is already gone.
                Files.delete_file_by_id(file.id)

        # Prune Knowledge Base records from deleted users.
        for kb in all_kbs:
            if kb.user_id not in user_ids:
                log.debug(f"Logically pruning knowledge base record: {kb.id}")
                try:
                    VECTOR_DB_CLIENT.delete_collection(collection_name=kb.id)
                except ValueError:
                    pass
                Knowledges.delete_knowledge_by_id(kb.id)

        # Prune all other user-owned data types.
        for note in Notes.get_notes():
            if note.user_id not in user_ids:
                Notes.delete_note_by_id(note.id)
        for prompt in Prompts.get_prompts():
            if prompt.user_id not in user_ids:
                Prompts.delete_prompt_by_command(prompt.command)
        for model in Models.get_all_models():
            if model.user_id not in user_ids:
                Models.delete_model_by_id(model.id)
        for folder in Folders.get_all_folders():
            if folder.user_id not in user_ids:
                Folders.delete_folder_by_id_and_user_id(folder.id, folder.user_id, delete_chats=False)

        # Stage 3: Physical Sweep.
        # Clean up any files/directories on disk that do not have a corresponding DB record.
        log.info("Starting physical sweep for stranded files and directories.")
        
        # Get a fresh, final list of all file/KB IDs that should exist after logical pruning.
        final_file_ids_in_db = {file.id for file in Files.get_files()}
        final_kb_ids_in_db = {kb.id for kb in Knowledges.get_knowledge_bases()}

        # Sweep /uploads directory
        upload_dir = os.path.join(os.path.dirname(CACHE_DIR), "uploads")
        if os.path.isdir(upload_dir):
            for filename in os.listdir(upload_dir):
                file_id_match = re.match(r"^([a-fA-F0-9\-]+)_", filename)
                if file_id_match and file_id_match.group(1) not in final_file_ids_in_db:
                    log.debug(f"Physically deleting stranded upload file: {filename}")
                    os.remove(os.path.join(upload_dir, filename))

        # Sweep /vector_db directory (ChromaDB-specific)
        if "chroma" in VECTOR_DB.lower():
            vector_dir = os.path.join(os.path.dirname(CACHE_DIR), "vector_db")
            if os.path.isdir(vector_dir):
                expected_collections = {f"file-{id}" for id in final_file_ids_in_db} | final_kb_ids_in_db
                for dirname in os.listdir(vector_dir):
                    dirpath = os.path.join(vector_dir, dirname)
                    if os.path.isdir(dirpath) and dirname not in expected_collections:
                        log.debug(f"Physically deleting stranded vector directory: {dirname}")
                        shutil.rmtree(dirpath)
        
        # Stage 4: Final Cleanup.
        # Clean transient cache directories and vacuum the main database.
        for cache_path in [f"{CACHE_DIR}/audio/transcriptions", f"{CACHE_DIR}/functions", f"{CACHE_DIR}/tools"]:
            if os.path.exists(cache_path):
                shutil.rmtree(cache_path)

        log.info("Vacuuming the main database.")
        with get_db() as db:
            if db.get_bind().dialect.name == "sqlite":
                db.execute(text("VACUUM"))
            elif db.get_bind().dialect.name == "postgresql":
                db.execute(text("VACUUM"))

        log.info("Pruning process completed successfully.")
        return True
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("An unexpected error occurred during pruning."),
        )
