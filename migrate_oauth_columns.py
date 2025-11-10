#!/usr/bin/env python3
"""
Minimal SQLite migration script to add Google OAuth columns.
Usage:
  python migrate_oauth_columns.py /absolute/path/to/instance/tournament.db

This script:
- Adds players.google_id (TEXT, nullable), players.email (TEXT, nullable)
- Adds teams.google_id (TEXT, nullable)
- Creates unique indexes on players.google_id and teams.google_id (ignoring NULLs)

It does NOT instantiate the Flask app.
"""
import sys
import sqlite3
from typing import Optional, Tuple


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    # Improve safety: enforce foreign keys if supported (harmless if already set)
    try:
        conn.execute("PRAGMA foreign_keys=ON;")
    except Exception:
        pass
    return conn


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table});")
    for row in cur.fetchall():
        # row: cid, name, type, notnull, dflt_value, pk
        if row[1] == column:
            return True
    return False


def index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?;", (index_name,)
    )
    return cur.fetchone() is not None


def add_column_if_missing(conn: sqlite3.Connection, table: str, column_def: str) -> Tuple[bool, Optional[str]]:
    """
    column_def example: 'google_id TEXT'
    """
    column_name = column_def.split()[0]
    if column_exists(conn, table, column_name):
        return False, None
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def};")
    return True, None


def create_unique_index_if_missing(conn: sqlite3.Connection, index_name: str, table: str, column: str) -> Tuple[bool, Optional[str]]:
    """
    Creates a partial unique index that ignores NULL values.
    Requires SQLite >= 3.8.0 (partial indexes support).
    """
    if index_exists(conn, index_name):
        return False, None
    conn.execute(
        f"CREATE UNIQUE INDEX {index_name} ON {table}({column}) WHERE {column} IS NOT NULL;"
    )
    return True, None


def migrate(db_path: str) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            # players: add google_id, email
            add_column_if_missing(conn, "players", "google_id TEXT")
            add_column_if_missing(conn, "players", "email TEXT")
            create_unique_index_if_missing(conn, "idx_players_google_id", "players", "google_id")

            # teams: add google_id
            add_column_if_missing(conn, "teams", "google_id TEXT")
            create_unique_index_if_missing(conn, "idx_teams_google_id", "teams", "google_id")

            # Ensure pw_hash columns are nullable (SQLite requires table rebuild to drop NOT NULL)
            def is_pw_hash_notnull(table: str) -> bool:
                cur = conn.execute(f"PRAGMA table_info({table});")
                for row in cur.fetchall():
                    # row: cid, name, type, notnull, dflt_value, pk
                    if row[1] == "pw_hash":
                        return bool(row[3])
                return False

            need_rebuild_players = is_pw_hash_notnull("players")
            need_rebuild_teams = is_pw_hash_notnull("teams")

            if need_rebuild_players or need_rebuild_teams:
                # Temporarily disable foreign key enforcement during table swap
                conn.execute("PRAGMA foreign_keys=OFF;")
                try:
                    if need_rebuild_players:
                        # Create new players table with pw_hash nullable and oauth columns present
                        conn.execute(
                            """
CREATE TABLE IF NOT EXISTS _players_new (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    pw_hash TEXT,
    google_id TEXT,
    email TEXT,
    phone TEXT,
    profile_photo TEXT,
    bio TEXT,
    location TEXT
);
"""
                        )
                        # Copy over existing data, leaving new columns NULL where not present
                        # Try to select each column if it exists
                        existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(players);").fetchall()]
                        select_cols = []
                        insert_cols = ["id", "name", "pw_hash", "google_id", "email", "phone", "profile_photo", "bio", "location"]
                        for col in insert_cols:
                            if col in existing_cols:
                                select_cols.append(col)
                            else:
                                select_cols.append("NULL AS " + col)
                        conn.execute(
                            f"INSERT INTO _players_new ({', '.join(insert_cols)}) SELECT {', '.join(select_cols)} FROM players;"
                        )
                        conn.execute("DROP TABLE players;")
                        conn.execute("ALTER TABLE _players_new RENAME TO players;")
                        # Recreate unique index
                        create_unique_index_if_missing(conn, "idx_players_google_id", "players", "google_id")

                    if need_rebuild_teams:
                        # Create new teams table with pw_hash nullable and oauth column present
                        conn.execute(
                            """
CREATE TABLE IF NOT EXISTS _teams_new (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    pw_hash TEXT,
    google_id TEXT,
    phone TEXT,
    email TEXT,
    icon TEXT,
    profile_photo TEXT,
    socials TEXT,
    website TEXT,
    location TEXT,
    about TEXT
);
"""
                        )
                        existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(teams);").fetchall()]
                        insert_cols = ["id", "name", "pw_hash", "google_id", "phone", "email", "icon", "profile_photo", "socials", "website", "location", "about"]
                        select_cols = []
                        for col in insert_cols:
                            if col in existing_cols:
                                select_cols.append(col)
                            else:
                                select_cols.append("NULL AS " + col)
                        conn.execute(
                            f"INSERT INTO _teams_new ({', '.join(insert_cols)}) SELECT {', '.join(select_cols)} FROM teams;"
                        )
                        conn.execute("DROP TABLE teams;")
                        conn.execute("ALTER TABLE _teams_new RENAME TO teams;")
                        # Recreate unique index
                        create_unique_index_if_missing(conn, "idx_teams_google_id", "teams", "google_id")
                finally:
                    conn.execute("PRAGMA foreign_keys=ON;")
    finally:
        conn.close()


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python migrate_oauth_columns.py /absolute/path/to/instance/tournament.db")
        sys.exit(1)
    db_path = sys.argv[1]
    try:
        migrate(db_path)
        print("Migration completed successfully.")
    except sqlite3.Error as e:
        print(f"SQLite error during migration: {e}")
        sys.exit(2)
    except Exception as e:
        print(f"Unexpected error during migration: {e}")
        sys.exit(3)


if __name__ == "__main__":
    main()


