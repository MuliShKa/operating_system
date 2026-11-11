
import sqlite3
from pathlib import Path

project_dir = Path(__file__).resolve().parent
schema_path = project_dir / "sql" / "schema.sql"
database_path = project_dir / "data" / "songdo_test.db"

database_path.parent.mkdir(parents=True, exist_ok=True)

with sqlite3.connect(database_path) as connection:
    connection.executescript(
        schema_path.read_text(encoding="utf-8")
    )

    tables = connection.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """).fetchall()

print("Database created:", database_path)
print("Tables:")
for (table_name,) in tables:
    print("-", table_name)
