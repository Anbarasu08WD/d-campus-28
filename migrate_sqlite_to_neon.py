"""Copy D-Campus SQLite data into Neon PostgreSQL.

WARNING: This replaces data in matching public tables in Neon with local SQLite data.
Run from the project folder after setting DATABASE_URL in .env.
"""
from pathlib import Path
import os
import sqlite3

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

SQLITE_PATH = Path(os.getenv("SQLITE_PATH", "student_success.db"))
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise SystemExit("DATABASE_URL is missing. Set it in your local .env file.")
if not SQLITE_PATH.is_file():
    raise SystemExit(f"SQLite database not found: {SQLITE_PATH.resolve()}\nSet SQLITE_PATH in .env if it is stored elsewhere.")


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def main():
    source = sqlite3.connect(f"file:{SQLITE_PATH.resolve().as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    source_tables = [r[0] for r in source.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]

    # Read the entire source dataset before opening the destructive destination transaction.
    source_data = {}
    source_columns = {}
    foreign_keys = {}
    for table in source_tables:
        source_columns[table] = [r[1] for r in source.execute(f"PRAGMA table_info({quote_ident(table)})")]
        source_data[table] = [dict(row) for row in source.execute(f"SELECT * FROM {quote_ident(table)}")]
        foreign_keys[table] = [r[2] for r in source.execute(f"PRAGMA foreign_key_list({quote_ident(table)})")]

    with psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=15) as pg:
        pg_tables = [r["table_name"] for r in pg.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' "
            "AND table_name NOT LIKE 'pg_%' AND table_name <> 'spatial_ref_sys'"
        ).fetchall()]
        shared = [t for t in source_tables if t in pg_tables]
        if not shared:
            raise SystemExit("No matching application tables found in SQLite and Neon.")

        pg_columns = {}
        pg_types = {}
        for table in shared:
            rows = pg.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                (table,),
            ).fetchall()
            pg_columns[table] = [r["column_name"] for r in rows]
            pg_types[table] = {r["column_name"]: r["data_type"] for r in rows}

        # Parent tables first, using SQLite's declared foreign-key relationships.
        ordered, pending = [], set(shared)
        while pending:
            ready = sorted(t for t in pending if not any(
                parent in pending and parent != t for parent in foreign_keys.get(t, [])
            ))
            if not ready:  # Defensive fallback for a cycle; PostgreSQL constraints may reject it.
                ordered.extend(sorted(pending))
                break
            ordered.extend(ready)
            pending.difference_update(ready)

        print(f"SQLite source: {SQLITE_PATH.resolve()}")
        print(f"Neon tables to replace: {', '.join(shared)}")
        print("Starting Neon replacement transaction...")

        with pg.transaction():
            table_sql = ", ".join(quote_ident(t) for t in shared)
            pg.execute(f"TRUNCATE TABLE {table_sql} RESTART IDENTITY CASCADE")

            total = 0
            for table in ordered:
                cols = [c for c in source_columns[table] if c in pg_columns[table]]
                rows = source_data[table]
                if not rows or not cols:
                    print(f"  {table}: 0 rows")
                    continue
                placeholders = ", ".join(["%s"] * len(cols))
                insert_sql = (
                    f"INSERT INTO {quote_ident(table)} "
                    f"({', '.join(quote_ident(c) for c in cols)}) "
                    f"VALUES ({placeholders})"
                )
                values = []
                for row in rows:
                    vals = []
                    for col in cols:
                        value = row[col]
                        if pg_types[table].get(col) == "boolean" and value is not None:
                            value = bool(value)
                        vals.append(value)
                    values.append(tuple(vals))
                with pg.cursor() as cur:
                    cur.executemany(insert_sql, values)
                total += len(rows)
                print(f"  {table}: {len(rows)} rows")

            # Reset SERIAL/BIGSERIAL sequences so future inserts don't collide with imported IDs.
            for table in ordered:
                if "id" in pg_columns[table]:
                    pg.execute(
                        "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                        "COALESCE((SELECT MAX(id) FROM " + quote_ident(table) + "), 1), "
                        "EXISTS(SELECT 1 FROM " + quote_ident(table) + "))",
                        (f"public.{table}",),
                    )

        print(f"\nMigration completed successfully. Imported {total} rows across {len(shared)} tables.")
        print("Neon now contains the local SQLite data in these matching tables.")

    source.close()


if __name__ == "__main__":
    main()
