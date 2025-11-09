#!/usr/bin/env python3
"""
Migration script to convert time_finalized from gamestate JSON to a boolean column.
Run this after adding the time_finalized column to the Match model.

Usage:
    python migrate_time_finalized.py <path_to_database>
    
Example:
    python migrate_time_finalized.py instance/tournament.db
"""

import sys
import json
import argparse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

def migrate_time_finalized(db_path):
    """Migrate time_finalized from gamestate JSON to the new column."""
    # Create engine and session
    engine = create_engine(f'sqlite:///{db_path}')
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # Check if time_finalized column exists
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(matches)"))
            columns = [row[1] for row in result]
            if 'time_finalized' not in columns:
                print("Error: time_finalized column does not exist in matches table.")
                print("Please run db.create_all() or update your database schema first.")
                sys.exit(1)
        
        # Get all matches
        result = session.execute(text("SELECT uuid, gamestate, time_finalized FROM matches"))
        matches = result.fetchall()
        
        migrated_count = 0
        
        for match_uuid, gamestate_json, time_finalized in matches:
            # Skip if already migrated
            if time_finalized:
                continue
            
            # Check gamestate for old time_finalized flag
            if gamestate_json:
                try:
                    gs = json.loads(gamestate_json)
                    if gs.get('time_finalized'):
                        # Update the match
                        session.execute(
                            text("UPDATE matches SET time_finalized = 1 WHERE uuid = :uuid"),
                            {"uuid": match_uuid}
                        )
                        migrated_count += 1
                except (json.JSONDecodeError, TypeError):
                    pass
        
        if migrated_count > 0:
            session.commit()
            print(f"Migrated {migrated_count} matches from gamestate time_finalized to column")
        else:
            print("No matches needed migration (column already populated or no data to migrate)")
            
    except Exception as e:
        print(f"Error during migration: {e}")
        session.rollback()
        sys.exit(1)
    finally:
        session.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Migrate time_finalized from JSON to boolean column')
    parser.add_argument('db_path', help='Path to the database file (e.g., instance/tournament.db)')
    args = parser.parse_args()
    
    migrate_time_finalized(args.db_path)

