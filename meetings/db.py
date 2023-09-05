from __future__ import annotations

from mautrix.util.async_db import UpgradeTable, Connection

upgrade_table = UpgradeTable()

@upgrade_table.register(description="Initial revision")
async def upgrade_v1(conn: Connection) -> None:
  await conn.execute(
    """CREATE TABLE meetings (
         room_id TEXT PRIMARY KEY,
         meeting_id TEXT NOT NULL,
    )"""
  )
  await conn.execute(
    """CREATE TABLE meeting_logs (
         meeting_id TEXT NOT NULL,
         timestamp TEXT NOT NULL,
         sender TEXT NOT NULL,
         message TEXT NOT NULL,
         tag TEXT DEFAULT NULL,
    )"""
  )

@upgrade_table.register(description="add topics")
async def upgrade_v2(conn: Connection) -> None:
  await conn.execute("ALTER TABLE meetings ADD COLUMN topic TEXT DEFAULT ''")
  await conn.execute("ALTER TABLE meeting_logs ADD COLUMN topic TEXT DEFAULT ''")

@upgrade_table.register(description="add meeting_name")
async def upgrade_v3(conn: Connection) -> None:
  await conn.execute("ALTER TABLE meetings ADD COLUMN meeting_name TEXT NOT NULL")
