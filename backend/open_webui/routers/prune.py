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
        try:
            # This logic is specific to ChromaDB's file-based storage.
            if "chroma" in VECTOR_DB.lower():
                # Step 1: Construct the path to the vector database directory.
                chroma_path = os.path.join(os.path.dirname(CACHE_DIR), "vector_db")

                if os.path.isdir(chroma_path):
                    # Step 2: Get the list of all expected collection names from the main DB.
                    # This is the "source of truth".
                    valid_knowledge_base_ids = {kb.id for kb in Knowledges.get_knowledge_bases()}
                    valid_file_ids = {f"file-{file.id}" for file in Files.get_files()}
                    expected_collections = valid_knowledge_base_ids.union(valid_file_ids)

                    # Step 3: Get the list of all physical subdirectories that exist on disk.
                    physical_dirs = [
                        d for d in os.listdir(chroma_path) if os.path.isdir(os.path.join(chroma_path, d))
                    ]

                    # Step 4: Find directories that exist physically but are not expected.
                    stranded_dirs = [
                        dir_name for dir_name in physical_dirs if dir_name not in expected_collections
                    ]

                    if stranded_dirs:
                        log.info(f"Pruning {len(stranded_dirs)} stranded physical vector directories.")
                        for dir_name in stranded_dirs:
                            try:
                                # Physically remove the stranded directory
                                collection_path = os.path.join(chroma_path, dir_name)
                                log.debug(f"Physically removing stranded directory: {collection_path}")
                                shutil.rmtree(collection_path)
                            except Exception as e:
                                # This will now only catch errors from shutil.rmtree (e.g., permissions)
                                log.error(f"Error while removing stranded directory {dir_name}: {e}")
                    else:
                        log.info("No stranded physical vector directories found.")
            else:
                log.warning(
                    f"Vector DB type '{VECTOR_DB}' does not support physical pruning. Skipping."
                )

        except Exception as e:
            log.error(f"Error during physical vector directory pruning: {e}")
        
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

        # Files
        all_files = Files.get_files()
        referenced_file_ids = set()
        for chat in Chats.get_chats():
            file_ids = re.findall(
                r'"file_id":\s*"([^"]+)"', str(chat.chat)
            )
            referenced_file_ids.update(file_ids)

        for kb in Knowledges.get_knowledge_bases():
            if kb.data and "file_ids" in kb.data:
                referenced_file_ids.update(kb.data["file_ids"])

        for file in all_files:
            if file.user_id not in user_ids or file.id not in referenced_file_ids:
                try:
                    Storage.delete_file(file.path)
                    VECTOR_DB_CLIENT.delete_collection(collection_name=f"file-{file.id}")
                    Files.delete_file_by_id(file.id)
                except ValueError as e:
                    # This can happen if the collection was already deleted but the file record remains.
                    # We can safely ignore this and proceed with deleting the file record.
                    log.warning(f"Could not delete vector collection for file {file.id} (may already be gone): {e}")
                    # Ensure the file record is deleted even if the vector part fails
                    if Files.get_file_by_id(file.id):
                        Files.delete_file_by_id(file.id)

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
