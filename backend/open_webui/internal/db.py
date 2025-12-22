import os
import json
import logging
from contextlib import contextmanager, asynccontextmanager
from typing import Any, Optional, AsyncGenerator

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
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker
from sqlalchemy.pool import QueuePool, NullPool
from sqlalchemy.sql.type_api import _T
from typing_extensions import Self

log = logging.getLogger(__name__)


class JSONField(types.TypeDecorator):
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


# Workaround to handle the peewee migration
# This is required to ensure the peewee migration is handled before the alembic migration
def handle_peewee_migration(DATABASE_URL):
    # db = None
    try:
        # Replace the postgresql:// with postgres:// to handle the peewee migration
        db = register_connection(DATABASE_URL.replace("postgresql://", "postgres://"))
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
        # Properly closing the database connection
        if db and not db.is_closed():
            db.close()

        # Assert if db connection has been closed
        assert db.is_closed(), "Database connection is still open."


handle_peewee_migration(DATABASE_URL)


SQLALCHEMY_DATABASE_URL = DATABASE_URL

# Handle SQLCipher URLs
if SQLALCHEMY_DATABASE_URL.startswith("sqlite+sqlcipher://"):
    database_password = os.environ.get("DATABASE_PASSWORD")
    if not database_password or database_password.strip() == "":
        raise ValueError(
            "DATABASE_PASSWORD is required when using sqlite+sqlcipher:// URLs"
        )

    # Extract database path from SQLCipher URL
    db_path = SQLALCHEMY_DATABASE_URL.replace("sqlite+sqlcipher://", "")

    # Create a custom creator function that uses sqlcipher3
    def create_sqlcipher_connection():
        import sqlcipher3

        conn = sqlcipher3.connect(db_path, check_same_thread=False)
        conn.execute(f"PRAGMA key = '{database_password}'")
        return conn

    engine = create_engine(
        "sqlite://",  # Dummy URL since we're using creator
        creator=create_sqlcipher_connection,
        echo=False,
    )

    log.info("Connected to encrypted SQLite database using SQLCipher")

elif "sqlite" in SQLALCHEMY_DATABASE_URL:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
    )

    def on_connect(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        if DATABASE_ENABLE_SQLITE_WAL:
            cursor.execute("PRAGMA journal_mode=WAL")
        else:
            cursor.execute("PRAGMA journal_mode=DELETE")
        cursor.close()

    event.listen(engine, "connect", on_connect)
else:
    if isinstance(DATABASE_POOL_SIZE, int):
        if DATABASE_POOL_SIZE > 0:
            engine = create_engine(
                SQLALCHEMY_DATABASE_URL,
                pool_size=DATABASE_POOL_SIZE,
                max_overflow=DATABASE_POOL_MAX_OVERFLOW,
                pool_timeout=DATABASE_POOL_TIMEOUT,
                pool_recycle=DATABASE_POOL_RECYCLE,
                pool_pre_ping=True,
                poolclass=QueuePool,
            )
        else:
            engine = create_engine(
                SQLALCHEMY_DATABASE_URL, pool_pre_ping=True, poolclass=NullPool
            )
    else:
        engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)


SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
)
metadata_obj = MetaData(schema=DATABASE_SCHEMA)


class Base(AsyncAttrs, DeclarativeBase):
    """
    Base class for all SQLAlchemy models with async support.
    
    AsyncAttrs enables async-compatible lazy loading via `await obj.awaitable_attrs.relationship`.
    """
    metadata = metadata_obj


Session = scoped_session(SessionLocal)


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


get_db = contextmanager(get_session)


# =============================================================================
# ASYNC DATABASE INFRASTRUCTURE
# =============================================================================


def _get_async_database_url(url: str) -> str:
    """
    Convert a synchronous database URL to an async-compatible URL.
    
    - PostgreSQL: postgresql:// -> postgresql+asyncpg://
    - SQLite: sqlite:/// -> sqlite+aiosqlite:///
    - SQLCipher: Not supported for async (returns original URL)
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    # SQLCipher and other URLs are returned as-is (async not supported)
    return url


ASYNC_DATABASE_URL = _get_async_database_url(SQLALCHEMY_DATABASE_URL)


# Only create async engine for supported database types
if ASYNC_DATABASE_URL.startswith("sqlite+aiosqlite"):
    # SQLite async engine
    async_engine = create_async_engine(
        ASYNC_DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
        echo=False,
    )
elif ASYNC_DATABASE_URL.startswith("postgresql+asyncpg"):
    # PostgreSQL async engine with connection pooling
    if isinstance(DATABASE_POOL_SIZE, int) and DATABASE_POOL_SIZE > 0:
        async_engine = create_async_engine(
            ASYNC_DATABASE_URL,
            pool_size=DATABASE_POOL_SIZE,
            max_overflow=DATABASE_POOL_MAX_OVERFLOW,
            pool_timeout=DATABASE_POOL_TIMEOUT,
            pool_recycle=DATABASE_POOL_RECYCLE,
            pool_pre_ping=True,
            echo=False,
        )
    else:
        async_engine = create_async_engine(
            ASYNC_DATABASE_URL,
            pool_pre_ping=True,
            echo=False,
        )
else:
    # Fallback: no async engine for unsupported databases (e.g., SQLCipher)
    async_engine = None
    log.warning(
        f"Async database engine not available for URL scheme: {ASYNC_DATABASE_URL[:20]}..."
    )


# Async session factory (only if async engine is available)
if async_engine is not None:
    AsyncSessionLocal = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
else:
    AsyncSessionLocal = None


@asynccontextmanager
async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Async database session context manager.
    
    Usage:
        async with get_async_db() as db:
            result = await db.execute(select(User))
            users = result.scalars().all()
    
    Raises:
        RuntimeError: If async database is not available (e.g., SQLCipher)
    """
    if AsyncSessionLocal is None:
        raise RuntimeError(
            "Async database session not available. "
            "Async is not supported for SQLCipher databases."
        )
    
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def async_init_db():
    """Initialize async database tables (for testing/development)."""
    if async_engine is not None:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


async def async_get_db_health() -> bool:
    """Check async database connectivity."""
    try:
        async with get_async_db() as db:
            from sqlalchemy import text
            await db.execute(text("SELECT 1"))
            return True
    except Exception:
        return False


# Alias for backward compatibility
async_session_factory = AsyncSessionLocal

