"""Two-tier TTL cache: in-memory LRU + SQLite-backed disk store.

External APIs (Nominatim, Overpass, geoBoundaries, WorldPop, Overture) are
slow and rate-limited. Most LLM-driven sessions repeat lookups across name
variants — caching is the single biggest perf win available.

Usage::

    from tools import cache

    value = await cache.get_or_fetch(
        namespace="nominatim",
        key={"q": "Mumbai"},
        ttl_seconds=86_400 * 7,
        fetch_fn=lambda: do_request(),
    )

Keys are dicts; we hash them to a stable string. Values must be
JSON-serializable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Awaitable, Callable

import os

_DEFAULT_CACHE_DIR = Path.home() / ".disha"
_DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_CACHE_DB = Path(os.environ.get("DISHA_CACHE_DB", str(_DEFAULT_CACHE_DIR / "cache.db")))

_MEM_MAX = 500
_DISK_MAX_ROWS = 5_000

_mem: OrderedDict[str, tuple[float, str]] = OrderedDict()
_mem_lock = asyncio.Lock()
_db_lock = asyncio.Lock()
_db_inited = False


def _key_hash(namespace: str, key: dict) -> str:
    payload = json.dumps(key, sort_keys=True, default=str)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_CACHE_DB), timeout=5.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.DatabaseError:
        pass
    return conn


def _init_db_sync() -> None:
    conn = _connect()
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                expires_at REAL NOT NULL
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at)")
        conn.commit()
    finally:
        conn.close()


async def _ensure_db() -> None:
    global _db_inited
    if _db_inited:
        return
    async with _db_lock:
        if not _db_inited:
            await asyncio.to_thread(_init_db_sync)
            _db_inited = True


def _disk_get_sync(key: str, now: float) -> str | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        value, expires_at = row
        if expires_at < now:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            conn.commit()
            return None
        return value
    finally:
        conn.close()


def _disk_put_sync(key: str, value: str, expires_at: float) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO cache(key, value, expires_at) VALUES(?, ?, ?)",
            (key, value, expires_at),
        )
        count = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        if count > _DISK_MAX_ROWS:
            conn.execute(
                "DELETE FROM cache WHERE key IN ("
                "SELECT key FROM cache ORDER BY expires_at ASC LIMIT ?"
                ")",
                (count - _DISK_MAX_ROWS + _DISK_MAX_ROWS // 10,),
            )
        conn.commit()
    finally:
        conn.close()


async def get_or_fetch(
    namespace: str,
    key: dict,
    ttl_seconds: float,
    fetch_fn: Callable[[], Awaitable[Any]],
) -> Any:
    """Look up (namespace, key); return cached value or call ``fetch_fn`` and cache it."""
    full_key = _key_hash(namespace, key)
    now = time.time()

    async with _mem_lock:
        entry = _mem.get(full_key)
        if entry is not None:
            expires_at, value_json = entry
            if expires_at >= now:
                _mem.move_to_end(full_key)
                return json.loads(value_json)
            del _mem[full_key]

    await _ensure_db()
    disk_json = await asyncio.to_thread(_disk_get_sync, full_key, now)
    if disk_json is not None:
        async with _mem_lock:
            _mem[full_key] = (now + ttl_seconds, disk_json)
            _mem.move_to_end(full_key)
            while len(_mem) > _MEM_MAX:
                _mem.popitem(last=False)
        return json.loads(disk_json)

    value = await fetch_fn()
    value_json = json.dumps(value, default=str)
    expires_at = now + ttl_seconds

    async with _mem_lock:
        _mem[full_key] = (expires_at, value_json)
        _mem.move_to_end(full_key)
        while len(_mem) > _MEM_MAX:
            _mem.popitem(last=False)

    await asyncio.to_thread(_disk_put_sync, full_key, value_json, expires_at)
    return value
