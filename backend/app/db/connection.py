from __future__ import annotations

import aiosqlite


async def create_connection(
    database_path: str,
    *,
    timeout_seconds: float = 60.0,
    busy_timeout_ms: int = 60000,
) -> aiosqlite.Connection:
    connection = await aiosqlite.connect(database_path, timeout=timeout_seconds)
    connection.row_factory = aiosqlite.Row
    await connection.execute("PRAGMA journal_mode=WAL;")
    await connection.execute("PRAGMA wal_autocheckpoint=1000;")
    await connection.execute("PRAGMA journal_size_limit=67108864;")
    await connection.execute(f"PRAGMA busy_timeout={max(1, int(busy_timeout_ms))};")
    await connection.execute("PRAGMA synchronous=NORMAL;")
    await connection.execute("PRAGMA foreign_keys=ON;")
    return connection
