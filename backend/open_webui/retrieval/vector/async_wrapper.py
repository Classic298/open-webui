"""
Async wrapper for vector database clients.

This module provides an async interface for all vector database operations,
wrapping the synchronous VectorDBBase implementations using asyncio's
run_in_executor for non-blocking execution.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Union
from functools import partial

from open_webui.retrieval.vector.main import (
    VectorDBBase, 
    AsyncVectorDBBase,
    VectorItem, 
    SearchResult, 
    GetResult,
)


# Thread pool for running sync vector DB operations
_vector_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="vector_db_")


class AsyncVectorDBWrapper:
    """
    Async wrapper for any VectorDBBase implementation.
    
    Wraps synchronous vector database operations in asyncio.run_in_executor
    to prevent blocking the event loop during database operations.
    
    Usage:
        from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
        async_vector_db = AsyncVectorDBWrapper(VECTOR_DB_CLIENT)
        
        # Now use async methods
        results = await async_vector_db.search(collection_name, vectors, limit)
    """
    
    def __init__(self, sync_client: VectorDBBase, executor: ThreadPoolExecutor = None):
        """
        Initialize the async wrapper.
        
        Args:
            sync_client: The synchronous vector database client to wrap
            executor: Optional custom ThreadPoolExecutor (uses default pool if None)
        """
        self._client = sync_client
        self._executor = executor or _vector_executor
    
    async def _run_in_executor(self, func, *args, **kwargs):
        """Run a synchronous function in the thread pool executor."""
        loop = asyncio.get_event_loop()
        if kwargs:
            func = partial(func, **kwargs)
        return await loop.run_in_executor(self._executor, func, *args)
    
    async def has_collection(self, collection_name: str) -> bool:
        """Check if the collection exists in the vector DB."""
        return await self._run_in_executor(self._client.has_collection, collection_name)
    
    async def delete_collection(self, collection_name: str) -> None:
        """Delete a collection from the vector DB."""
        return await self._run_in_executor(self._client.delete_collection, collection_name)
    
    async def insert(self, collection_name: str, items: List[VectorItem]) -> None:
        """Insert a list of vector items into a collection."""
        return await self._run_in_executor(self._client.insert, collection_name, items)
    
    async def upsert(self, collection_name: str, items: List[VectorItem]) -> None:
        """Insert or update vector items in a collection."""
        return await self._run_in_executor(self._client.upsert, collection_name, items)
    
    async def search(
        self, collection_name: str, vectors: List[List[Union[float, int]]], limit: int
    ) -> Optional[SearchResult]:
        """Search for similar vectors in a collection."""
        return await self._run_in_executor(
            self._client.search, collection_name, vectors, limit
        )
    
    async def query(
        self, collection_name: str, filter: Dict, limit: Optional[int] = None
    ) -> Optional[GetResult]:
        """Query vectors from a collection using metadata filter."""
        return await self._run_in_executor(
            self._client.query, collection_name, filter, limit
        )
    
    async def get(self, collection_name: str) -> Optional[GetResult]:
        """Retrieve all vectors from a collection."""
        return await self._run_in_executor(self._client.get, collection_name)
    
    async def delete(
        self,
        collection_name: str,
        ids: Optional[List[str]] = None,
        filter: Optional[Dict] = None,
    ) -> None:
        """Delete vectors by ID or filter from a collection."""
        return await self._run_in_executor(
            self._client.delete, collection_name, ids, filter
        )
    
    async def reset(self) -> None:
        """Reset the vector database by removing all collections."""
        return await self._run_in_executor(self._client.reset)


# Create the async wrapper for the global vector DB client
def get_async_vector_client():
    """
    Get the async-wrapped vector database client.
    
    This lazily imports the sync client to avoid circular imports.
    """
    from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
    return AsyncVectorDBWrapper(VECTOR_DB_CLIENT)


# Lazy-loaded global async client
_async_vector_client = None


def get_async_vector_db():
    """Get the global async vector database client (singleton)."""
    global _async_vector_client
    if _async_vector_client is None:
        _async_vector_client = get_async_vector_client()
    return _async_vector_client


# Convenience alias
ASYNC_VECTOR_DB_CLIENT = None  # Will be set on first use


def init_async_vector_client():
    """Initialize the async vector client (call during app startup)."""
    global ASYNC_VECTOR_DB_CLIENT
    ASYNC_VECTOR_DB_CLIENT = get_async_vector_db()
    return ASYNC_VECTOR_DB_CLIENT
