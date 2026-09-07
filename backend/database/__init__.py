# -*- coding: utf-8 -*-
"""PostgreSQL database connection management."""

from typing import Generator

from loguru import logger
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool

from backend.config import (
    DATABASE_URL,
    DB_MAX_OVERFLOW,
    DB_POOL_RECYCLE,
    DB_POOL_SIZE,
    DB_POOL_TIMEOUT,
)

DB_TYPE = "postgresql"
logger.info("Database type: PostgreSQL")


def create_database_engine():
    """Create the PostgreSQL database engine."""
    if not DATABASE_URL.lower().startswith(("postgresql://", "postgresql+")):
        raise RuntimeError("Only PostgreSQL DATABASE_URL values are supported.")

    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=DB_POOL_SIZE,
        max_overflow=DB_MAX_OVERFLOW,
        pool_timeout=DB_POOL_TIMEOUT,
        pool_recycle=DB_POOL_RECYCLE,
        pool_pre_ping=True,
        echo=False,
    )
    logger.info(f"PostgreSQL pool configured: size={DB_POOL_SIZE}, overflow={DB_MAX_OVERFLOW}")
    return engine


engine = create_database_engine()


@event.listens_for(engine, "connect")
def set_postgresql_settings(dbapi_connection, connection_record):
    """Set PostgreSQL connection parameters."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("SET timezone='Asia/Shanghai'")
        cursor.execute("SET client_encoding='UTF8'")
        cursor.close()
        logger.debug("PostgreSQL connection parameters configured")
    except Exception as exc:
        logger.error(f"Failed to configure PostgreSQL connection: {exc}")


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """PostgreSQL schema is managed by Alembic, not create_all()."""
    raise RuntimeError("init_db() is disabled. Run `alembic upgrade head` to manage PostgreSQL schema.")


def get_engine_info() -> dict:
    """Return database engine information for health checks."""
    info = {
        "type": DB_TYPE,
        "url": DATABASE_URL.replace("://", "://***@").replace("//", "//***@") if "@" in DATABASE_URL else DATABASE_URL,
    }

    try:
        with engine.connect() as conn:
            info["version"] = conn.execute(text("SELECT version()")).scalar()
            info["pool_size"] = DB_POOL_SIZE
            info["max_overflow"] = DB_MAX_OVERFLOW
    except Exception as exc:
        info["error"] = str(exc)

    return info
