#!/usr/bin/env python3
"""
Migration script to add stones_at_start column to points table.
This column records the stones_remaining value when a point starts (for STONES matches).

Usage:
    python migrate_stones_at_start.py <path_to_database>
    
Example:
    python migrate_stones_at_start.py instance/tournament.db
"""

import sqlite3
import sys
import os

def migrate_database(db_path):
    """Add stones_at_start column to points table."""
    if not os.path.exists(db_path):
        print(f"Error: Database file not found: {db_path}")
        sys.exit(1)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(points)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'stones_at_start' in columns:
            print("✓ stones_at_start column already exists")
            conn.close()
            return
        
        # Add stones_at_start column
        print("Adding stones_at_start column to points table...")
        cursor.execute("ALTER TABLE points ADD COLUMN stones_at_start INTEGER")
        print("✓ Added stones_at_start column")
        
        conn.commit()
        print("\n✓ Migration completed successfully!")
        
    except Exception as e:
        conn.rollback()
        print(f"\n✗ Error during migration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python migrate_stones_at_start.py <path_to_database>")
        print("Example: python migrate_stones_at_start.py instance/tournament.db")
        sys.exit(1)
    
    db_path = sys.argv[1]
    migrate_database(db_path)

