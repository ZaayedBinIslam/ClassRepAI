"""Database engine and session factory. Tables are created on startup (no migrations)."""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


def _engine_args(url: str) -> tuple[str, dict]:
    """asyncpg doesn't understand ?sslmode=require (Neon adds it), so turn it into ssl=True."""
    if not url.startswith("postgresql"):
        return url, {}
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    needs_ssl = query.pop("sslmode", None) not in (None, "disable")
    query.pop("channel_binding", None)
    clean = urlunsplit(parts._replace(query=urlencode(query)))
    return clean, ({"ssl": True} if needs_ssl else {})


_url, _connect_args = _engine_args(settings.DATABASE_URL)
engine = create_async_engine(_url, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    from app import models  # noqa: F401  (registers the tables)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
