#!/usr/bin/env python3
"""
Migration script to refactor Match table:
- Replace 'dynamic' (boolean) and 'type' (SETS/STONES/BREAK/JOIN) with:
  - 'schedule_type' (STATIC, DYNAMIC, BREAK, JOIN)
  - 'set_type' (SETS, STONES)
- Add 'ribbon' (boolean) column
"""
import sqlite3
import sys
import os

def migrate_database(db_path):
    """Refactor Match table columns."""
    if not os.path.exists(db_path):
        print(f"Error: Database file not found: {db_path}")
        sys.exit(1)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check current columns
        cursor.execute("PRAGMA table_info(matches)")
        columns = {col[1]: col for col in cursor.fetchall()}
        
        # Check if migration already done
        if 'schedule_type' in columns and 'set_type' in columns and 'ribbon' in columns:
            print("✓ Migration already completed (schedule_type, set_type, and ribbon columns exist)")
            conn.close()
            return
        
        # Step 1: Add new columns
        print("Adding new columns...")
        if 'schedule_type' not in columns:
            cursor.execute("ALTER TABLE matches ADD COLUMN schedule_type TEXT")
            print("✓ Added schedule_type column")
        else:
            print("✓ schedule_type column already exists")
        
        if 'set_type' not in columns:
            cursor.execute("ALTER TABLE matches ADD COLUMN set_type TEXT")
            print("✓ Added set_type column")
        else:
            print("✓ set_type column already exists")
        
        if 'ribbon' not in columns:
            cursor.execute("ALTER TABLE matches ADD COLUMN ribbon INTEGER DEFAULT 0")
            print("✓ Added ribbon column")
        else:
            print("✓ ribbon column already exists")
        
        conn.commit()
        
        # Step 2: Migrate data
        print("\nMigrating data...")
        
        # Get all matches
        cursor.execute("SELECT uuid, dynamic, type FROM matches")
        matches = cursor.fetchall()
        
        migrated_count = 0
        for match_uuid, dynamic, match_type in matches:
            # Determine schedule_type
            if match_type in ('BREAK', 'JOIN'):
                schedule_type = match_type
            elif dynamic:
                schedule_type = 'DYNAMIC'
            else:
                schedule_type = 'STATIC'
            
            # Determine set_type
            if match_type in ('SETS', 'STONES'):
                set_type = match_type
            else:
                # Default to SETS for BREAK/JOIN (though it doesn't matter)
                set_type = 'SETS'
            
            # Update the match
            cursor.execute("""
                UPDATE matches 
                SET schedule_type = ?, set_type = ?
                WHERE uuid = ?
            """, (schedule_type, set_type, match_uuid))
            
            migrated_count += 1
        
        conn.commit()
        print(f"✓ Migrated {migrated_count} matches")
        
        # Step 3: Drop old columns (SQLite doesn't support DROP COLUMN directly, so we'll recreate the table)
        print("\nRemoving old columns...")
        
        # Get all current columns with their definitions
        cursor.execute("PRAGMA table_info(matches)")
        column_info = cursor.fetchall()
        
        # Build column definitions, excluding dynamic and type, adding new ones
        column_defs = []
        for col in column_info:
            col_name = col[1]
            if col_name in ('dynamic', 'type'):
                continue  # Skip old columns
            col_type = col[2]
            col_notnull = col[3]
            col_default = col[4]
            col_pk = col[5]
            
            # Build column definition
            col_def = f"{col_name} {col_type}"
            if col_notnull:
                col_def += " NOT NULL"
            if col_default is not None:
                col_def += f" DEFAULT {col_default}"
            if col_pk:
                col_def += " PRIMARY KEY"
            column_defs.append(col_def)
        
        # Add new columns
        column_defs.append("schedule_type TEXT DEFAULT 'STATIC'")
        column_defs.append("set_type TEXT DEFAULT 'SETS'")
        column_defs.append("ribbon INTEGER DEFAULT 0")
        
        # Get foreign keys
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='matches'")
        create_sql = cursor.fetchone()[0]
        
        # Extract foreign key constraints (simplified - just copy them)
        fk_section = ""
        if "FOREIGN KEY" in create_sql.upper():
            # Extract everything after the last column definition
            import re
            fk_match = re.search(r'(FOREIGN KEY[^)]+\))', create_sql, re.IGNORECASE | re.DOTALL)
            if fk_match:
                fk_section = ", " + fk_match.group(1)
        
        # Create new table
        create_statement = f"""
            CREATE TABLE matches_new (
                {', '.join(column_defs)}{fk_section}
            )
        """
        cursor.execute(create_statement)
        
        # Copy data to new table (exclude dynamic and type from SELECT)
        columns_to_keep = [col[1] for col in column_info if col[1] not in ('dynamic', 'type')]
        column_list = ', '.join(columns_to_keep)
        cursor.execute(f"""
            INSERT INTO matches_new ({column_list}, schedule_type, set_type, ribbon)
            SELECT {column_list}, schedule_type, set_type, ribbon FROM matches
        """)
        
        # Drop old table and rename new one
        cursor.execute("DROP TABLE matches")
        cursor.execute("ALTER TABLE matches_new RENAME TO matches")
        
        conn.commit()
        print("✓ Removed old columns (dynamic and type)")
        
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
        print("Usage: python migrate_match_columns.py <path_to_database.db>")
        sys.exit(1)
    
    db_path = sys.argv[1]
    migrate_database(db_path)

