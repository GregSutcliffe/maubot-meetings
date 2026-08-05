from __future__ import annotations

from mautrix.util.async_db import Connection, UpgradeTable

upgrade_table = UpgradeTable()


@upgrade_table.register(description="Initial revision")
async def upgrade_v1(conn: Connection) -> None:
    await conn.execute("""CREATE TABLE meetings (
         room_id TEXT PRIMARY KEY,
         meeting_id TEXT NOT NULL
    )""")
    await conn.execute("""CREATE TABLE meeting_logs (
         meeting_id TEXT NOT NULL,
         timestamp TEXT NOT NULL,
         sender TEXT NOT NULL,
         message TEXT NOT NULL,
         tag TEXT DEFAULT NULL
    )""")


@upgrade_table.register(description="add topics")
async def upgrade_v2(conn: Connection) -> None:
    await conn.execute("ALTER TABLE meetings ADD COLUMN topic TEXT DEFAULT ''")
    await conn.execute("ALTER TABLE meeting_logs ADD COLUMN topic TEXT DEFAULT ''")


@upgrade_table.register(description="add meeting_name")
async def upgrade_v3(conn: Connection) -> None:
    await conn.execute("ALTER TABLE meetings ADD COLUMN meeting_name TEXT NOT NULL")


@upgrade_table.register(description="add line_num with default for databases on v3")
async def upgrade_v4(conn: Connection) -> None:
    # Databases with existing rows will crash here if we don't include the default right away
    await conn.execute("ALTER TABLE meeting_logs ADD COLUMN line_num integer NOT NULL DEFAULT 0")


# Some DBs were already updated to v4 before the default was added, so enforce it here
# SQLite can't alter an existing column, so we rename/copy/replace it
@upgrade_table.register(description="set default for databases already on v4")
async def upgrade_v5(conn: Connection) -> None:
    await conn.execute("ALTER TABLE meeting_logs RENAME COLUMN line_num TO line_num_old")
    await conn.execute("ALTER TABLE meeting_logs ADD COLUMN line_num integer NOT NULL DEFAULT 0")
    await conn.execute("UPDATE meeting_logs SET line_num = COALESCE(line_num_old, 0)")
    await conn.execute("ALTER TABLE meeting_logs DROP COLUMN line_num_old")
