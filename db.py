from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    TIMESTAMP,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

metadata = MetaData()

users_table = Table(
    "users",
    metadata,
    Column("user_id", String, primary_key=True),
    Column("name", String),
    Column("history", JSONB),
    Column("created_at", TIMESTAMP(timezone=True)),
    Column("updated_at", TIMESTAMP(timezone=True)),
    Column("message_count", Integer),
    Column("summary", String),
    Column("message_limit", Integer),
    Column("voice_enabled", Boolean),
)

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _normalize_dsn(dsn: str) -> str:
    if dsn.startswith("postgresql+"):
        return dsn
    if dsn.startswith("postgres://"):
        return dsn.replace("postgres://", "postgresql+asyncpg://", 1)
    if dsn.startswith("postgresql://"):
        return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    return dsn


async def init_db_pool(dsn: str) -> None:
    global _engine, _session_factory
    if _engine is not None and _session_factory is not None:
        return
    async_dsn = _normalize_dsn(dsn)
    _engine = create_async_engine(async_dsn, echo=False, future=True)
    _session_factory = async_sessionmaker(
        _engine,
        expire_on_commit=False,
    )


async def close_db_pool() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def _require_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database engine is not initialized")
    return _session_factory


async def fetch_all_users() -> List[Dict[str, Any]]:
    session_factory = _require_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(
                users_table.c.user_id,
                users_table.c.name,
                users_table.c.history,
                users_table.c.message_count,
                users_table.c.summary,
                users_table.c.message_limit,
                users_table.c.voice_enabled,
            )
        )
        return [dict(row) for row in result.mappings().all()]


async def fetch_all_user_ids() -> List[str]:
    session_factory = _require_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(users_table.c.user_id))
        return result.scalars().all()


async def fetch_user_message_stats(user_id: str) -> Optional[Dict[str, Any]]:
    session_factory = _require_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(
                users_table.c.message_count,
                users_table.c.message_limit,
            ).where(users_table.c.user_id == user_id)
        )
        row = result.mappings().one_or_none()
        return dict(row) if row else None


async def fetch_user_stats() -> Dict[str, int]:
    session_factory = _require_session_factory()
    async with session_factory() as session:
        total_users = await session.scalar(select(func.count()).select_from(users_table))
        active_users = await session.scalar(
            select(func.count()).select_from(users_table).where(
                func.coalesce(users_table.c.message_count, 0) > 0
            )
        )
        voice_enabled = await session.scalar(
            select(func.count()).select_from(users_table).where(
                users_table.c.voice_enabled.is_(True)
            )
        )
    return {
        "total_users": total_users or 0,
        "active_users": active_users or 0,
        "voice_enabled": voice_enabled or 0,
    }


async def fetch_users_history() -> List[Dict[str, Any]]:
    session_factory = _require_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(users_table.c.user_id, users_table.c.history)
        )
        return [dict(row) for row in result.mappings().all()]


async def upsert_user(user_data: Dict[str, Any]) -> None:
    if "user_id" not in user_data:
        raise ValueError("user_data must include 'user_id'")

    payload = {k: v for k, v in user_data.items() if v is not None}
    payload.setdefault("updated_at", datetime.now(timezone.utc))

    insert_stmt = insert(users_table).values(**payload)
    update_values = {
        key: insert_stmt.excluded[key]
        for key in payload.keys()
        if key != "user_id"
    }
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=[users_table.c.user_id],
        set_=update_values,
    )

    session_factory = _require_session_factory()
    async with session_factory() as session:
        await session.execute(upsert_stmt)
        await session.commit()


async def update_user_fields(user_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = datetime.now(timezone.utc)
    session_factory = _require_session_factory()
    async with session_factory() as session:
        stmt = (
            update(users_table)
            .where(users_table.c.user_id == user_id)
            .values(**fields)
        )
        await session.execute(stmt)
        await session.commit()

