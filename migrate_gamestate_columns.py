#!/usr/bin/env python3
"""
Migration script to move data from matches.gamestate JSON to proper columns.
Run this after adding the new columns to the Match model.

Usage:
    python migrate_gamestate_columns.py <path_to_database>
    
Example:
    python migrate_gamestate_columns.py instance/tournament.db
"""

import sys
import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional


def get_connection(db_path: str) -> sqlite3.Connection:
    """Get database connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    cur = conn.execute(f"PRAGMA table_info({table});")
    for row in cur.fetchall():
        if row[1] == column:
            return True
    return False


def add_column_if_missing(conn: sqlite3.Connection, table: str, column_def: str) -> None:
    """Add a column to a table if it doesn't exist."""
    column_name = column_def.split()[0]
    if not column_exists(conn, table, column_name):
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def};")
            print(f"  Added column {column_name}")
        except sqlite3.OperationalError as e:
            print(f"  Warning: Could not add column {column_name}: {e}")


def parse_iso_datetime(iso_str: Optional[str]) -> Optional[str]:
    """Parse ISO datetime string and return SQLite-compatible datetime string.
    SQLite stores DateTime as TEXT in format 'YYYY-MM-DD HH:MM:SS' (naive UTC).
    """
    if not iso_str:
        return None
    try:
        # Handle various ISO formats
        iso_str_clean = iso_str.replace('Z', '+00:00')
        dt = datetime.fromisoformat(iso_str_clean)
        # Convert to naive UTC datetime for SQLite (SQLAlchemy expects naive UTC)
        if dt.tzinfo:
            # Convert timezone-aware to naive UTC
            dt_utc = dt.astimezone(timezone.utc)
            dt = dt_utc.replace(tzinfo=None)
        # Format as SQLite-compatible string: 'YYYY-MM-DD HH:MM:SS'
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, AttributeError, TypeError) as e:
        print(f"    Warning: Could not parse datetime '{iso_str}': {e}")
        return None


def migrate_gamestate(db_path: str) -> None:
    """Migrate gamestate JSON data to new columns."""
    conn = get_connection(db_path)
    
    try:
        # Add all new columns
        print("Adding new columns to matches table...")
        add_column_if_missing(conn, "matches", "initial_notes TEXT")
        add_column_if_missing(conn, "matches", "team1_players TEXT")
        add_column_if_missing(conn, "matches", "team2_players TEXT")
        add_column_if_missing(conn, "matches", "started_by TEXT")
        add_column_if_missing(conn, "matches", "started_at DATETIME")
        add_column_if_missing(conn, "matches", "stones_per_set INTEGER")
        add_column_if_missing(conn, "matches", "stones_remaining INTEGER")
        add_column_if_missing(conn, "matches", "finalized_by TEXT")
        add_column_if_missing(conn, "matches", "final_notes TEXT")
        add_column_if_missing(conn, "matches", "match_winner TEXT")
        add_column_if_missing(conn, "matches", "team1_signature TEXT")
        add_column_if_missing(conn, "matches", "team2_signature TEXT")
        add_column_if_missing(conn, "matches", "finalized_at DATETIME")
        add_column_if_missing(conn, "matches", "ready_to_start BOOLEAN DEFAULT 0")
        add_column_if_missing(conn, "matches", "ready_to_start_at DATETIME")
        
        conn.commit()
        print("Columns added successfully.\n")
        
        # Get all matches with gamestate
        print("Migrating data from gamestate JSON...")
        cur = conn.execute("SELECT uuid, gamestate FROM matches WHERE gamestate IS NOT NULL AND gamestate != ''")
        matches = cur.fetchall()
        
        migrated_count = 0
        error_count = 0
        
        for match_row in matches:
            match_uuid = match_row['uuid']
            gamestate_json = match_row['gamestate']
            
            if not gamestate_json:
                continue
            
            try:
                gamestate = json.loads(gamestate_json)
            except json.JSONDecodeError as e:
                print(f"  Warning: Could not parse gamestate for match {match_uuid}: {e}")
                error_count += 1
                continue
            
            # Build update query with only non-None values
            updates = []
            params = {}
            
            # Simple string fields
            if 'notes' in gamestate:
                updates.append("initial_notes = :notes")
                params['notes'] = gamestate['notes']
            
            if 'final_notes' in gamestate:
                updates.append("final_notes = :final_notes")
                params['final_notes'] = gamestate['final_notes']
            
            if 'match_winner' in gamestate:
                updates.append("match_winner = :match_winner")
                params['match_winner'] = gamestate['match_winner']
            
            if 'started_by' in gamestate:
                updates.append("started_by = :started_by")
                params['started_by'] = gamestate['started_by']
            
            if 'finalized_by' in gamestate:
                updates.append("finalized_by = :finalized_by")
                params['finalized_by'] = gamestate['finalized_by']
            
            if 'team1_signature' in gamestate:
                updates.append("team1_signature = :team1_signature")
                params['team1_signature'] = gamestate['team1_signature']
            
            if 'team2_signature' in gamestate:
                updates.append("team2_signature = :team2_signature")
                params['team2_signature'] = gamestate['team2_signature']
            
            # JSON array fields (store as JSON string)
            if 'team1_players' in gamestate:
                updates.append("team1_players = :team1_players")
                params['team1_players'] = json.dumps(gamestate['team1_players'])
            
            if 'team2_players' in gamestate:
                updates.append("team2_players = :team2_players")
                params['team2_players'] = json.dumps(gamestate['team2_players'])
            
            # Integer fields
            if 'stones_per_set' in gamestate:
                updates.append("stones_per_set = :stones_per_set")
                params['stones_per_set'] = gamestate['stones_per_set']
            
            if 'stones_remaining' in gamestate:
                updates.append("stones_remaining = :stones_remaining")
                params['stones_remaining'] = gamestate['stones_remaining']
            
            # Boolean field
            if 'ready_to_start' in gamestate:
                updates.append("ready_to_start = :ready_to_start")
                params['ready_to_start'] = 1 if gamestate['ready_to_start'] else 0
            
            # Datetime fields (parse ISO strings)
            if 'started_at' in gamestate:
                dt_str = parse_iso_datetime(gamestate['started_at'])
                if dt_str:
                    updates.append("started_at = :started_at")
                    params['started_at'] = dt_str
            
            if 'finalized_at' in gamestate:
                dt_str = parse_iso_datetime(gamestate['finalized_at'])
                if dt_str:
                    updates.append("finalized_at = :finalized_at")
                    params['finalized_at'] = dt_str
            
            if 'ready_to_start_at' in gamestate:
                dt_str = parse_iso_datetime(gamestate['ready_to_start_at'])
                if dt_str:
                    updates.append("ready_to_start_at = :ready_to_start_at")
                    params['ready_to_start_at'] = dt_str
            
            # Execute update if there are any changes
            if updates:
                params['uuid'] = match_uuid
                update_sql = f"UPDATE matches SET {', '.join(updates)} WHERE uuid = :uuid"
                conn.execute(update_sql, params)
                migrated_count += 1
        
        conn.commit()
        
        print(f"\nMigration complete!")
        print(f"  Migrated {migrated_count} matches")
        if error_count > 0:
            print(f"  {error_count} matches had errors")
        
    except Exception as e:
        conn.rollback()
        print(f"\nError during migration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python migrate_gamestate_columns.py <path_to_database>")
        sys.exit(1)
    
    db_path = sys.argv[1]
    migrate_gamestate(db_path)

