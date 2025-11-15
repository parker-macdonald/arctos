#!/usr/bin/env python3
"""
Migration script to add camera_index and stream_timestamp columns to points table,
and camera_stream_starts column to matches table.
Also updates fields.camera to support JSON arrays (no data migration needed, just schema change).
"""
import sqlite3
import sys
import os

def migrate_database(db_path):
    """Add new camera-related columns to database."""
    if not os.path.exists(db_path):
        print(f"Error: Database file not found: {db_path}")
        sys.exit(1)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(points)")
        points_columns = [col[1] for col in cursor.fetchall()]
        
        cursor.execute("PRAGMA table_info(matches)")
        matches_columns = [col[1] for col in cursor.fetchall()]
        
        # Add camera_index to points if it doesn't exist
        if 'camera_index' not in points_columns:
            print("Adding camera_index column to points table...")
            cursor.execute("ALTER TABLE points ADD COLUMN camera_index INTEGER")
            print("✓ Added camera_index column")
        else:
            print("✓ camera_index column already exists")
        
        # Add stream_timestamp to points if it doesn't exist
        if 'stream_timestamp' not in points_columns:
            print("Adding stream_timestamp column to points table...")
            cursor.execute("ALTER TABLE points ADD COLUMN stream_timestamp REAL")
            print("✓ Added stream_timestamp column")
        else:
            print("✓ stream_timestamp column already exists")
        
        # Add camera_stream_starts to matches if it doesn't exist
        if 'camera_stream_starts' not in matches_columns:
            print("Adding camera_stream_starts column to matches table...")
            cursor.execute("ALTER TABLE matches ADD COLUMN camera_stream_starts TEXT")
            print("✓ Added camera_stream_starts column")
        else:
            print("✓ camera_stream_starts column already exists")
        
        # Note: fields.camera column type change from String(200) to Text
        # doesn't require a migration in SQLite (TEXT is compatible with String)
        # The application code will handle parsing JSON arrays vs single strings
        
        conn.commit()
        print("\n✓ Migration completed successfully!")
        
    except Exception as e:
        conn.rollback()
        print(f"\n✗ Error during migration: {e}")
        sys.exit(1)
    finally:
        conn.close()

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python migrate_camera_columns.py <path_to_database.db>")
        sys.exit(1)
    
    db_path = sys.argv[1]
    migrate_database(db_path)

