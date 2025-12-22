from open_webui.retrieval.vector.main import VectorDBBase
from open_webui.retrieval.vector.type import VectorType
from open_webui.config import (
    VECTOR_DB,
    ENABLE_QDRANT_MULTITENANCY_MODE,
    ENABLE_MILVUS_MULTITENANCY_MODE,
)


class Vector:

    @staticmethod
    def get_vector(vector_type: str) -> VectorDBBase:
        """
        get vector db instance by vector type
        """
        match vector_type:
            case VectorType.MILVUS:
                if ENABLE_MILVUS_MULTITENANCY_MODE:
                    from open_webui.retrieval.vector.dbs.milvus_multitenancy import (
                        MilvusClient,
                    )

                    return MilvusClient()
                else:
                    from open_webui.retrieval.vector.dbs.milvus import MilvusClient

                    return MilvusClient()
            case VectorType.QDRANT:
                if ENABLE_QDRANT_MULTITENANCY_MODE:
                    from open_webui.retrieval.vector.dbs.qdrant_multitenancy import (
                        QdrantClient,
                    )

                    return QdrantClient()
                else:
                    from open_webui.retrieval.vector.dbs.qdrant import QdrantClient

                    return QdrantClient()
            case VectorType.PINECONE:
                from open_webui.retrieval.vector.dbs.pinecone import PineconeClient

                return PineconeClient()
            case VectorType.S3VECTOR:
                from open_webui.retrieval.vector.dbs.s3vector import S3VectorClient

                return S3VectorClient()
            case VectorType.OPENSEARCH:
                from open_webui.retrieval.vector.dbs.opensearch import OpenSearchClient

                return OpenSearchClient()
            case VectorType.PGVECTOR:
                from open_webui.retrieval.vector.dbs.pgvector import PgvectorClient

                return PgvectorClient()
            case VectorType.ELASTICSEARCH:
                from open_webui.retrieval.vector.dbs.elasticsearch import (
                    ElasticsearchClient,
                )

                return ElasticsearchClient()
            case VectorType.CHROMA:
                from open_webui.retrieval.vector.dbs.chroma import ChromaClient

                return ChromaClient()
            case VectorType.ORACLE23AI:
                from open_webui.retrieval.vector.dbs.oracle23ai import Oracle23aiClient

                return Oracle23aiClient()
            case VectorType.WEAVIATE:
                from open_webui.retrieval.vector.dbs.weaviate import WeaviateClient

                return WeaviateClient()
            case _:
                raise ValueError(f"Unsupported vector type: {vector_type}")


VECTOR_DB_CLIENT = Vector.get_vector(VECTOR_DB)


# =============================================================================
# ASYNC VECTOR DATABASE FACTORY (Phase 4)
# =============================================================================


class AsyncVector:
    """Factory for async vector database clients."""
    
    @staticmethod
    def get_vector(vector_type: str):
        """
        Get async vector database client for the given type.
        
        Returns an AsyncVectorDBWrapper that wraps the sync client,
        using asyncio.to_thread for non-blocking operations.
        """
        from open_webui.retrieval.vector.async_wrapper import AsyncVectorDBWrapper
        
        # Get the sync client and wrap it
        sync_client = Vector.get_vector(vector_type)
        return AsyncVectorDBWrapper(sync_client)


# Global async vector database client
ASYNC_VECTOR_DB_CLIENT = AsyncVector.get_vector(VECTOR_DB)
