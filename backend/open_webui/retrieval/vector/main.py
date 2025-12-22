from pydantic import BaseModel
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union


class VectorItem(BaseModel):
    id: str
    text: str
    vector: List[float | int]
    metadata: Any


class GetResult(BaseModel):
    ids: Optional[List[List[str]]]
    documents: Optional[List[List[str]]]
    metadatas: Optional[List[List[Any]]]


class SearchResult(GetResult):
    distances: Optional[List[List[float | int]]]


class VectorDBBase(ABC):
    """
    Abstract base class for all vector database backends.

    Implementations of this class provide methods for collection management,
    vector insertion, deletion, similarity search, and metadata filtering.

    Any custom vector database integration must inherit from this class and
    implement all abstract methods.
    """

    @abstractmethod
    def has_collection(self, collection_name: str) -> bool:
        """Check if the collection exists in the vector DB."""
        pass

    @abstractmethod
    def delete_collection(self, collection_name: str) -> None:
        """Delete a collection from the vector DB."""
        pass

    @abstractmethod
    def insert(self, collection_name: str, items: List[VectorItem]) -> None:
        """Insert a list of vector items into a collection."""
        pass

    @abstractmethod
    def upsert(self, collection_name: str, items: List[VectorItem]) -> None:
        """Insert or update vector items in a collection."""
        pass

    @abstractmethod
    def search(
        self, collection_name: str, vectors: List[List[Union[float, int]]], limit: int
    ) -> Optional[SearchResult]:
        """Search for similar vectors in a collection."""
        pass

    @abstractmethod
    def query(
        self, collection_name: str, filter: Dict, limit: Optional[int] = None
    ) -> Optional[GetResult]:
        """Query vectors from a collection using metadata filter."""
        pass

    @abstractmethod
    def get(self, collection_name: str) -> Optional[GetResult]:
        """Retrieve all vectors from a collection."""
        pass

    @abstractmethod
    def delete(
        self,
        collection_name: str,
        ids: Optional[List[str]] = None,
        filter: Optional[Dict] = None,
    ) -> None:
        """Delete vectors by ID or filter from a collection."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset the vector database by removing all collections or those matching a condition."""
        pass


# =============================================================================
# ASYNC VECTOR DATABASE BASE CLASS (Phase 4)
# =============================================================================


class AsyncVectorDBBase(ABC):
    """
    Async abstract base class for vector database backends.
    
    All implementations must provide async versions of these methods.
    For backends without native async support, use asyncio.to_thread()
    to wrap synchronous operations.
    """
    
    @abstractmethod
    async def has_collection(self, collection_name: str) -> bool:
        """Check if collection exists."""
        pass
    
    @abstractmethod
    async def delete_collection(self, collection_name: str) -> None:
        """Delete a collection."""
        pass
    
    @abstractmethod
    async def insert(self, collection_name: str, items: List[VectorItem]) -> None:
        """Insert items into collection."""
        pass
    
    @abstractmethod
    async def upsert(self, collection_name: str, items: List[VectorItem]) -> None:
        """Upsert items into collection."""
        pass
    
    @abstractmethod
    async def search(
        self, 
        collection_name: str, 
        vectors: List[List[Union[float, int]]], 
        limit: int
    ) -> Optional[SearchResult]:
        """Search for similar vectors."""
        pass
    
    @abstractmethod
    async def query(
        self, 
        collection_name: str, 
        filter: Dict, 
        limit: Optional[int] = None
    ) -> Optional[GetResult]:
        """Query by metadata filter."""
        pass
    
    @abstractmethod
    async def get(self, collection_name: str) -> Optional[GetResult]:
        """Get all items from collection."""
        pass
    
    @abstractmethod
    async def delete(
        self,
        collection_name: str,
        ids: Optional[List[str]] = None,
        filter: Optional[Dict] = None,
    ) -> None:
        """Delete items from collection."""
        pass
    
    @abstractmethod
    async def reset(self) -> None:
        """Reset the database."""
        pass
