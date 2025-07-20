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
        # Prune old chats first to determine which files/kbs might become orphaned
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

        # Build a definitive set of all user IDs that should exist
        user_ids = {user.id for user in Users.get_users()["users"]}

        # Stage 1: Prune orphaned database records and their associated data
        # This handles standard orphan cleanup where DB records still exist.

        # Prune orphaned Files
        all_files = Files.get_files()
        all_kbs = Knowledges.get_knowledge_bases()
        active_kb_file_ids = {
            fid for kb in all_kbs if kb.data and "file_ids" in kb.data for fid in kb.data["file_ids"]
        }
        for file in all_files:
            if file.id not in active_kb_file_ids or file.user_id not in user_ids:
                try:
                    Storage.delete_file(file.path)
                    VECTOR_DB_CLIENT.delete_collection(collection_name=f"file-{file.id}")
                except ValueError:
                    pass  # Collection already gone, ignore
                Files.delete_file_by_id(file.id)

        # Prune orphaned Knowledge Bases
        for kb in all_kbs:
            if kb.user_id not in user_ids:
                try:
                    VECTOR_DB_CLIENT.delete_collection(collection_name=kb.id)
                except ValueError:
                    pass  # Collection already gone, ignore
                Knowledges.delete_knowledge_by_id(kb.id)

        # Stage 2: Prune stranded physical files/directories that have no DB record.
        # This handles cleanup after incomplete deletions.

        # Clean stranded upload files
        all_file_ids_in_db = {file.id for file in Files.get_files()}
        upload_dir = os.path.join(os.path.dirname(CACHE_DIR), "uploads")
        if os.path.isdir(upload_dir):
            for filename in os.listdir(upload_dir):
                file_id_match = re.match(r"^([a-fA-F0-9\-]+)_", filename)
                if file_id_match and file_id_match.group(1) not in all_file_ids_in_db:
                    os.remove(os.path.join(upload_dir, filename))

        # Clean stranded vector directories (the core issue)
        if "chroma" in VECTOR_DB.lower():
            vector_dir = os.path.join(os.path.dirname(CACHE_DIR), "vector_db")
            if os.path.isdir(vector_dir):
                expected_collections = {f"file-{id}" for id in all_file_ids_in_db} | {kb.id for kb in all_kbs}
                for dirname in os.listdir(vector_dir):
                    dirpath = os.path.join(vector_dir, dirname)
                    if os.path.isdir(dirpath) and dirname not in expected_collections:
                        shutil.rmtree(dirpath)

        # Prune other orphaned items (Notes, Prompts, etc.)
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

        # Clean cache directories
        for cache_path in [
            f"{CACHE_DIR}/audio/transcriptions",
            f"{CACHE_DIR}/functions",
            f"{CACHE_DIR}/tools",
        ]:
            if os.path.exists(cache_path):
                shutil.rmtree(cache_path)

        # Vacuum the main database to reclaim space
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
