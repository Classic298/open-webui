import logging
import time
import os
import shutil
from typing import Optional, Set
from pathlib import Path

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


def get_active_file_ids() -> Set[str]:
    """
    Get all file IDs that are actively referenced by knowledge bases.
    This is the ground truth for what files should be preserved.
    """
    active_file_ids = set()
    
    try:
        knowledge_bases = Knowledges.get_knowledge_bases()
        log.debug(f"Found {len(knowledge_bases)} knowledge bases")
        
        for kb in knowledge_bases:
            if not kb.data:
                continue
                
            # Handle different possible data structures for file references
            file_ids = []
            
            # Check for file_ids array
            if isinstance(kb.data, dict) and "file_ids" in kb.data:
                if isinstance(kb.data["file_ids"], list):
                    file_ids.extend(kb.data["file_ids"])
            
            # Check for files array with id field
            if isinstance(kb.data, dict) and "files" in kb.data:
                if isinstance(kb.data["files"], list):
                    for file_ref in kb.data["files"]:
                        if isinstance(file_ref, dict) and "id" in file_ref:
                            file_ids.append(file_ref["id"])
                        elif isinstance(file_ref, str):
                            file_ids.append(file_ref)
            
            # Add all found file IDs
            for file_id in file_ids:
                if isinstance(file_id, str) and file_id.strip():
                    active_file_ids.add(file_id.strip())
                    log.debug(f"KB {kb.id} references file {file_id}")
    
    except Exception as e:
        log.error(f"Error determining active file IDs: {e}")
        # Fail safe: return empty set, which will prevent deletion
        return set()
    
    log.info(f"Found {len(active_file_ids)} active file IDs")
    return active_file_ids


def safe_delete_vector_collection(collection_name: str) -> bool:
    """
    Safely delete a vector collection, handling both logical and physical cleanup.
    """
    try:
        # First, try to delete the collection through the client
        try:
            VECTOR_DB_CLIENT.delete_collection(collection_name=collection_name)
            log.debug(f"Deleted collection from vector DB: {collection_name}")
        except Exception as e:
            log.debug(f"Collection {collection_name} may not exist in DB: {e}")
        
        # Then, handle physical cleanup for ChromaDB
        if "chroma" in VECTOR_DB.lower():
            vector_dir = Path(CACHE_DIR).parent / "vector_db" / collection_name
            if vector_dir.exists() and vector_dir.is_dir():
                shutil.rmtree(vector_dir)
                log.debug(f"Deleted physical vector directory: {vector_dir}")
                return True
        
        return True
        
    except Exception as e:
        log.error(f"Error deleting vector collection {collection_name}: {e}")
        return False


def safe_delete_file_by_id(file_id: str) -> bool:
    """
    Safely delete a file record and its associated vector collection.
    """
    try:
        # Get file info before deletion
        file_record = Files.get_file_by_id(file_id)
        if not file_record:
            log.debug(f"File {file_id} not found in database")
            return True  # Already gone
        
        # Delete vector collection first
        collection_name = f"file-{file_id}"
        safe_delete_vector_collection(collection_name)
        
        # Delete database record
        Files.delete_file_by_id(file_id)
        log.debug(f"Deleted file record: {file_id}")
        
        return True
        
    except Exception as e:
        log.error(f"Error deleting file {file_id}: {e}")
        return False


def cleanup_orphaned_uploads(active_file_ids: Set[str]) -> None:
    """
    Clean up orphaned files in the uploads directory.
    """
    upload_dir = Path(CACHE_DIR).parent / "uploads"
    if not upload_dir.exists():
        log.debug("Uploads directory does not exist")
        return
    
    deleted_count = 0
    
    try:
        for file_path in upload_dir.iterdir():
            if not file_path.is_file():
                continue
                
            filename = file_path.name
            
            # Extract file ID from filename (common patterns)
            file_id = None
            
            # Pattern 1: UUID_filename or UUID-filename
            if len(filename) > 36:
                potential_id = filename[:36]
                if potential_id.count('-') == 4:  # UUID format
                    file_id = potential_id
            
            # Pattern 2: filename might be the file ID itself
            if not file_id and filename.count('-') == 4 and len(filename) == 36:
                file_id = filename
            
            # Pattern 3: Check if any part of filename matches active IDs
            if not file_id:
                for active_id in active_file_ids:
                    if active_id in filename:
                        file_id = active_id
                        break
            
            # If we found a potential file ID and it's not active, delete it
            if file_id and file_id not in active_file_ids:
                try:
                    file_path.unlink()
                    deleted_count += 1
                    log.debug(f"Deleted orphaned upload file: {filename}")
                except Exception as e:
                    log.error(f"Failed to delete upload file {filename}: {e}")
    
    except Exception as e:
        log.error(f"Error cleaning uploads directory: {e}")
    
    if deleted_count > 0:
        log.info(f"Deleted {deleted_count} orphaned upload files")


def cleanup_orphaned_vector_collections(active_file_ids: Set[str], active_kb_ids: Set[str]) -> None:
    """
    Clean up orphaned vector collections by querying ChromaDB metadata.
    """
    if "chroma" not in VECTOR_DB.lower():
        return
    
    vector_dir = Path(CACHE_DIR).parent / "vector_db"
    if not vector_dir.exists():
        log.debug("Vector DB directory does not exist")
        return
    
    chroma_db_path = vector_dir / "chroma.sqlite3"
    if not chroma_db_path.exists():
        log.debug("ChromaDB metadata file does not exist")
        return
    
    # Build expected collection names
    expected_collections = set()
    
    # File collections: file-{file_id}
    for file_id in active_file_ids:
        expected_collections.add(f"file-{file_id}")
    
    # Knowledge base collections: {kb_id}
    for kb_id in active_kb_ids:
        expected_collections.add(kb_id)
    
    log.debug(f"Expected collections to preserve: {expected_collections}")
    
    # Query ChromaDB metadata to get the complete mapping chain:
    # Directory UUID -> Collection ID -> Collection Name
    uuid_to_collection = {}
    try:
        import sqlite3
        log.debug(f"Attempting to connect to ChromaDB at: {chroma_db_path}")
        
        with sqlite3.connect(str(chroma_db_path)) as conn:
            # First, check what tables exist
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            log.debug(f"ChromaDB tables: {tables}")
            
            # Check the schema of collections table
            schema = conn.execute("PRAGMA table_info(collections)").fetchall()
            log.debug(f"Collections table schema: {schema}")
            
            # Get Collection ID -> Collection Name mapping
            collection_id_to_name = {}
            cursor = conn.execute("SELECT id, name FROM collections")
            rows = cursor.fetchall()
            log.debug(f"Raw ChromaDB collections query results: {rows}")
            
            for row in rows:
                collection_id, collection_name = row
                collection_id_to_name[collection_id] = collection_name
                log.debug(f"Mapped collection ID {collection_id} -> name {collection_name}")
            
            # Get Directory UUID -> Collection ID mapping from segments table
            # Only interested in VECTOR segments as those are the actual data directories
            cursor = conn.execute("SELECT id, collection FROM segments WHERE scope = 'VECTOR'")
            segment_rows = cursor.fetchall()
            log.debug(f"Raw ChromaDB segments query results: {segment_rows}")
            
            for row in segment_rows:
                segment_id, collection_id = row
                if collection_id in collection_id_to_name:
                    collection_name = collection_id_to_name[collection_id]
                    uuid_to_collection[segment_id] = collection_name
                    log.debug(f"Mapped directory UUID {segment_id} -> collection {collection_name}")
        
        log.debug(f"Final uuid_to_collection mapping: {uuid_to_collection}")
        log.info(f"Found {len(uuid_to_collection)} vector segments in ChromaDB metadata")
        
    except Exception as e:
        log.error(f"Error reading ChromaDB metadata: {e}")
        # Fail safe: don't delete anything if we can't read metadata
        return
    
    deleted_count = 0
    
    try:
        for collection_dir in vector_dir.iterdir():
            if not collection_dir.is_dir():
                continue
                
            dir_uuid = collection_dir.name
            
            # Skip system/metadata files
            if dir_uuid.startswith('.'):
                continue
            
            # Get the actual collection name from metadata
            collection_name = uuid_to_collection.get(dir_uuid)
            
            if collection_name is None:
                # Directory exists but no metadata entry - it's orphaned
                log.debug(f"Directory {dir_uuid} has no metadata entry, deleting")
                try:
                    shutil.rmtree(collection_dir)
                    deleted_count += 1
                except Exception as e:
                    log.error(f"Failed to delete orphaned directory {dir_uuid}: {e}")
            
            elif collection_name not in expected_collections:
                # Collection exists but should be deleted
                log.debug(f"Collection {collection_name} (UUID: {dir_uuid}) is orphaned, deleting")
                try:
                    shutil.rmtree(collection_dir)
                    deleted_count += 1
                except Exception as e:
                    log.error(f"Failed to delete collection directory {dir_uuid}: {e}")
            
            else:
                # Collection should be preserved
                log.debug(f"Preserving collection {collection_name} (UUID: {dir_uuid})")
    
    except Exception as e:
        log.error(f"Error cleaning vector collections: {e}")
    
    if deleted_count > 0:
        log.info(f"Deleted {deleted_count} orphaned vector collections")


@router.post("/", response_model=bool)
async def prune_data(form_data: PruneDataForm, user=Depends(get_admin_user)):
    """
    Prunes old and orphaned data using a safe, multi-stage process.
    """
    try:
        log.info("Starting data pruning process")
        
        # Stage 1: Delete old chats based on user criteria
        if form_data.days is not None:
            cutoff_time = int(time.time()) - (form_data.days * 86400)
            chats_to_delete = []
            
            for chat in Chats.get_chats():
                if chat.updated_at < cutoff_time:
                    if form_data.exempt_archived_chats and chat.archived:
                        continue
                    chats_to_delete.append(chat)
            
            if chats_to_delete:
                log.info(f"Deleting {len(chats_to_delete)} old chats")
                for chat in chats_to_delete:
                    Chats.delete_chat_by_id(chat.id)
        
        # Stage 2: Build ground truth of what should be preserved
        log.info("Building preservation set")
        
        # Get all active users
        active_user_ids = {user.id for user in Users.get_users()["users"]}
        log.info(f"Found {len(active_user_ids)} active users")
        
        # Get all active knowledge bases and their file references
        active_kb_ids = set()
        knowledge_bases = Knowledges.get_knowledge_bases()
        
        for kb in knowledge_bases:
            if kb.user_id in active_user_ids:
                active_kb_ids.add(kb.id)
        
        log.info(f"Found {len(active_kb_ids)} active knowledge bases")
        
        # Get all files that should be preserved
        active_file_ids = get_active_file_ids()
        
        # Stage 3: Delete orphaned database records
        log.info("Deleting orphaned database records")
        
        # Delete files not referenced by any knowledge base or belonging to deleted users
        deleted_files = 0
        for file_record in Files.get_files():
            should_delete = (
                file_record.id not in active_file_ids or 
                file_record.user_id not in active_user_ids
            )
            
            if should_delete:
                if safe_delete_file_by_id(file_record.id):
                    deleted_files += 1
        
        if deleted_files > 0:
            log.info(f"Deleted {deleted_files} orphaned files")
        
        # Delete knowledge bases from deleted users
        deleted_kbs = 0
        for kb in knowledge_bases:
            if kb.user_id not in active_user_ids:
                if safe_delete_vector_collection(kb.id):
                    Knowledges.delete_knowledge_by_id(kb.id)
                    deleted_kbs += 1
        
        if deleted_kbs > 0:
            log.info(f"Deleted {deleted_kbs} orphaned knowledge bases")
        
        # Delete other user-owned resources from deleted users
        deleted_others = 0
        
        for note in Notes.get_notes():
            if note.user_id not in active_user_ids:
                Notes.delete_note_by_id(note.id)
                deleted_others += 1
        
        for prompt in Prompts.get_prompts():
            if prompt.user_id not in active_user_ids:
                Prompts.delete_prompt_by_command(prompt.command)
                deleted_others += 1
        
        for model in Models.get_all_models():
            if model.user_id not in active_user_ids:
                Models.delete_model_by_id(model.id)
                deleted_others += 1
        
        for folder in Folders.get_all_folders():
            if folder.user_id not in active_user_ids:
                Folders.delete_folder_by_id_and_user_id(folder.id, folder.user_id, delete_chats=False)
                deleted_others += 1
        
        if deleted_others > 0:
            log.info(f"Deleted {deleted_others} other orphaned records")
        
        # Stage 4: Clean up orphaned physical files
        log.info("Cleaning up orphaned physical files")
        
        # Rebuild active sets after database cleanup
        final_active_file_ids = get_active_file_ids()
        final_active_kb_ids = {kb.id for kb in Knowledges.get_knowledge_bases()}
        
        # Clean uploads directory
        cleanup_orphaned_uploads(final_active_file_ids)
        
        # Clean vector collections
        cleanup_orphaned_vector_collections(final_active_file_ids, final_active_kb_ids)
        
        # Stage 5: Database optimization
        log.info("Optimizing database")
        
        # Clean transient cache directories
        cache_paths = [
            Path(CACHE_DIR) / "audio" / "transcriptions",
            Path(CACHE_DIR) / "functions",
            Path(CACHE_DIR) / "tools"
        ]
        
        for cache_path in cache_paths:
            if cache_path.exists():
                shutil.rmtree(cache_path)
                log.debug(f"Cleaned cache directory: {cache_path}")
        
        # Vacuum main database
        try:
            with get_db() as db:
                db.execute(text("VACUUM"))
                log.debug("Vacuumed main database")
        except Exception as e:
            log.error(f"Failed to vacuum main database: {e}")
        
        # Vacuum ChromaDB database if it exists
        if "chroma" in VECTOR_DB.lower():
            chroma_db_path = Path(CACHE_DIR).parent / "vector_db" / "chroma.sqlite3"
            if chroma_db_path.exists():
                try:
                    import sqlite3
                    with sqlite3.connect(str(chroma_db_path)) as conn:
                        conn.execute("VACUUM")
                        log.debug("Vacuumed ChromaDB database")
                except Exception as e:
                    log.error(f"Failed to vacuum ChromaDB database: {e}")
        
        log.info("Data pruning completed successfully")
        return True
        
    except Exception as e:
        log.exception(f"Error during data pruning: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Data pruning failed"),
        )
