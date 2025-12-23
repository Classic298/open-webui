"""
Database infrastructure for Open WebUI.

This module provides async-first database access using SQLAlchemy 2.0.
All database operations should use the async `get_db()` context manager.

Supported databases:
- PostgreSQL (via asyncpg)
- SQLite (via aiosqlite)  
- SQLCipher (via sync fallback with thread pool)
"""

import os
import json
import logging
import asyncio
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional, AsyncGenerator, Union

from open_webui.internal.wrappers import register_connection
from open_webui.env import (
    OPEN_WEBUI_DIR,
    DATABASE_URL,
    DATABASE_SCHEMA,
    DATABASE_POOL_MAX_OVERFLOW,
    DATABASE_POOL_RECYCLE,
    DATABASE_POOL_SIZE,
    DATABASE_POOL_TIMEOUT,
    DATABASE_ENABLE_SQLITE_WAL,
)
from peewee_migrate import Router
from sqlalchemy import Dialect, create_engine, MetaData, event, types
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
    AsyncAttrs,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import QueuePool, NullPool
from sqlalchemy.sql.type_api import _T
from typing_extensions import Self

log = logging.getLogger(__name__)


# =============================================================================
# CUSTOM TYPES
# =============================================================================


class JSONField(types.TypeDecorator):
    """Custom JSON field type for SQLAlchemy."""
    impl = types.Text
    cache_ok = True

    def process_bind_param(self, value: Optional[_T], dialect: Dialect) -> Any:
        return json.dumps(value)

    def process_result_value(self, value: Optional[_T], dialect: Dialect) -> Any:
        if value is not None:
            return json.loads(value)

    def copy(self, **kw: Any) -> Self:
        return JSONField(self.impl.length)

    def db_value(self, value):
        return json.dumps(value)

    def python_value(self, value):
        if value is not None:
            return json.loads(value)


# =============================================================================
# PEEWEE MIGRATION (Legacy support)
# =============================================================================


def _handle_peewee_migration(database_url: str) -> None:
    """
    Handle legacy Peewee migrations before Alembic takes over.
    This is required for backward compatibility with older databases.
    """
    db = None
    try:
        # Replace postgresql:// with postgres:// for Peewee compatibility
        db = register_connection(database_url.replace("postgresql://", "postgres://"))
        migrate_dir = OPEN_WEBUI_DIR / "internal" / "migrations"
        router = Router(db, logger=log, migrate_dir=migrate_dir)
        router.run()
        db.close()
    except Exception as e:
        log.error(f"Failed to initialize the database connection: {e}")
        log.warning(
            "Hint: If your database password contains special characters, you may need to URL-encode it."
        )
        raise
    finally:
        if db and not db.is_closed():
            db.close()
        if db:
            assert db.is_closed(), "Database connection is still open."


# Run Peewee migrations at module load
_handle_peewee_migration(DATABASE_URL)


# =============================================================================
# DATABASE URL HANDLING
# =============================================================================


def _convert_to_async_url(url: str) -> str:
    """
    Convert a synchronous database URL to an async-compatible URL.
    
    - PostgreSQL: postgresql:// -> postgresql+asyncpg://
    - SQLite: sqlite:/// -> sqlite+aiosqlite:///
    - SQLCipher: Returns original URL (handled via sync fallback)
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    # SQLCipher and other URLs returned as-is
    return url


DATABASE_URL_ASYNC = _convert_to_async_url(DATABASE_URL)
USING_SQLCIPHER = DATABASE_URL.startswith("sqlite+sqlcipher://")


# =============================================================================
# DATABASE ENGINES
# =============================================================================


def _create_sync_engine():
    """Create synchronous engine (for SQLCipher fallback and migrations)."""
    if DATABASE_URL.startswith("sqlite+sqlcipher://"):
        # SQLCipher encrypted database
        database_password = os.environ.get("DATABASE_PASSWORD")
        if not database_password or database_password.strip() == "":
            raise ValueError(
                "DATABASE_PASSWORD is required when using sqlite+sqlcipher:// URLs"
            )
        
        db_path = DATABASE_URL.replace("sqlite+sqlcipher://", "")
        
        def create_sqlcipher_connection():
            import sqlcipher3
            conn = sqlcipher3.connect(db_path, check_same_thread=False)
            conn.execute(f"PRAGMA key = '{database_password}'")
            return conn
        
        engine = create_engine(
            "sqlite://",
            creator=create_sqlcipher_connection,
            echo=False,
        )
        log.info("Connected to encrypted SQLite database using SQLCipher")
        return engine
    
    elif "sqlite" in DATABASE_URL:
        # Regular SQLite
        engine = create_engine(
            DATABASE_URL, connect_args={"check_same_thread": False}
        )
        
        def on_connect(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            if DATABASE_ENABLE_SQLITE_WAL:
                cursor.execute("PRAGMA journal_mode=WAL")
            else:
                cursor.execute("PRAGMA journal_mode=DELETE")
            cursor.close()
        
        event.listen(engine, "connect", on_connect)
        return engine
    
    else:
        # PostgreSQL or other databases
        if isinstance(DATABASE_POOL_SIZE, int):
            if DATABASE_POOL_SIZE > 0:
                return create_engine(
                    DATABASE_URL,
                    pool_size=DATABASE_POOL_SIZE,
                    max_overflow=DATABASE_POOL_MAX_OVERFLOW,
                    pool_timeout=DATABASE_POOL_TIMEOUT,
                    pool_recycle=DATABASE_POOL_RECYCLE,
                    pool_pre_ping=True,
                    poolclass=QueuePool,
                )
            else:
                return create_engine(
                    DATABASE_URL, pool_pre_ping=True, poolclass=NullPool
                )
        return create_engine(DATABASE_URL, pool_pre_ping=True)


def _create_async_engine_instance():
    """Create async engine for supported databases."""
    if DATABASE_URL_ASYNC.startswith("sqlite+aiosqlite"):
        return create_async_engine(
            DATABASE_URL_ASYNC,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
            echo=False,
        )
    elif DATABASE_URL_ASYNC.startswith("postgresql+asyncpg"):
        if isinstance(DATABASE_POOL_SIZE, int) and DATABASE_POOL_SIZE > 0:
            return create_async_engine(
                DATABASE_URL_ASYNC,
                pool_size=DATABASE_POOL_SIZE,
                max_overflow=DATABASE_POOL_MAX_OVERFLOW,
                pool_timeout=DATABASE_POOL_TIMEOUT,
                pool_recycle=DATABASE_POOL_RECYCLE,
                pool_pre_ping=True,
                echo=False,
            )
        return create_async_engine(
            DATABASE_URL_ASYNC,
            pool_pre_ping=True,
            echo=False,
        )
    # No async engine for SQLCipher
    return None


# Create engines
_sync_engine = _create_sync_engine()
_async_engine = _create_async_engine_instance()

if _async_engine is None and not USING_SQLCIPHER:
    log.warning(
        f"Async database engine not available for URL scheme: {DATABASE_URL_ASYNC[:20]}..."
    )


# =============================================================================
# SESSION FACTORIES
# =============================================================================


# Sync session factory (for SQLCipher fallback)
_SyncSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=_sync_engine, expire_on_commit=False
)

# Async session factory (for PostgreSQL and SQLite)
_AsyncSessionLocal = (
    async_sessionmaker(
        bind=_async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    if _async_engine is not None
    else None
)


# =============================================================================
# BASE MODEL
# =============================================================================


metadata_obj = MetaData(schema=DATABASE_SCHEMA)


class Base(AsyncAttrs, DeclarativeBase):
    """
    Base class for all SQLAlchemy models.
    
    Uses AsyncAttrs for async-compatible lazy loading.
    """
    metadata = metadata_obj


# =============================================================================
# ASYNC SESSION WRAPPER (for SQLCipher)
# =============================================================================


class _SyncSessionWrapper:
    """
    Wraps a synchronous SQLAlchemy session to provide an async-compatible interface.
    Used for SQLCipher databases where native async is not supported.
    """
    
    def __init__(self, session, loop, executor):
        self._session = session
        self._loop = loop
        self._executor = executor
    
    async def execute(self, statement, *args, **kwargs):
        """Execute a statement asynchronously."""
        return await self._loop.run_in_executor(
            self._executor,
            lambda: self._session.execute(statement, *args, **kwargs)
        )
    
    async def scalar(self, statement, *args, **kwargs):
        """Execute a statement and return a scalar result."""
        return await self._loop.run_in_executor(
            self._executor,
            lambda: self._session.scalar(statement, *args, **kwargs)
        )
    
    async def scalars(self, statement, *args, **kwargs):
        """Execute a statement and return scalars."""
        return await self._loop.run_in_executor(
            self._executor,
            lambda: self._session.scalars(statement, *args, **kwargs)
        )
    
    def add(self, instance):
        """Add an instance to the session."""
        self._session.add(instance)
    
    def add_all(self, instances):
        """Add multiple instances to the session."""
        self._session.add_all(instances)
    
    async def delete(self, instance):
        """Delete an instance."""
        await self._loop.run_in_executor(
            self._executor,
            lambda: self._session.delete(instance)
        )
    
    async def commit(self):
        """Commit the transaction."""
        await self._loop.run_in_executor(self._executor, self._session.commit)
    
    async def rollback(self):
        """Rollback the transaction."""
        await self._loop.run_in_executor(self._executor, self._session.rollback)
    
    async def refresh(self, instance):
        """Refresh an instance from the database."""
        await self._loop.run_in_executor(
            self._executor,
            lambda: self._session.refresh(instance)
        )
    
    async def get(self, entity, ident):
        """Get an entity by primary key."""
        return await self._loop.run_in_executor(
            self._executor,
            lambda: self._session.get(entity, ident)
        )
    
    async def close(self):
        """Close the session."""
        await self._loop.run_in_executor(self._executor, self._session.close)
    
    @property
    def bind(self):
        """Access the underlying engine bind."""
        return self._session.bind


# =============================================================================
# PUBLIC API
# =============================================================================


@asynccontextmanager
async def get_db() -> AsyncGenerator[Union[AsyncSession, _SyncSessionWrapper], None]:
    """
    Async database session context manager.
    
    This is the primary way to access the database. Always use this.
    
    Usage:
        async with get_db() as db:
            result = await db.execute(select(User))
            users = result.scalars().all()
    
    For SQLCipher databases, operations are automatically run in a thread pool.
    """
    if _AsyncSessionLocal is not None:
        # Native async support (PostgreSQL, SQLite)
        async with _AsyncSessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    else:
        # SQLCipher fallback: wrap sync session with async interface
        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        session = _SyncSessionLocal()
        wrapper = _SyncSessionWrapper(session, loop, executor)
        try:
            yield wrapper
            await loop.run_in_executor(executor, session.commit)
        except Exception:
            await loop.run_in_executor(executor, session.rollback)
            raise
        finally:
            await loop.run_in_executor(executor, session.close)
            executor.shutdown(wait=False)


async def init_db() -> None:
    """Initialize database tables."""
    if _async_engine is not None:
        async with _async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    else:
        # SQLCipher fallback
        Base.metadata.create_all(_sync_engine)


async def get_db_health() -> bool:
    """Check database connectivity."""
    try:
        async with get_db() as db:
            from sqlalchemy import text
            await db.execute(text("SELECT 1"))
            return True
    except Exception:
        return False


# =============================================================================
# EXPORTS (Backward Compatibility)
# =============================================================================

# For backward compatibility with code that imports these directly
Session = _SyncSessionLocal  # Deprecated: use get_db() instead
SessionLocal = _SyncSessionLocal  # Deprecated: use get_db() instead
engine = _sync_engine  # Deprecated: internal use only
async_engine = _async_engine  # Deprecated: internal use only
