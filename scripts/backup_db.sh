#!/usr/bin/env bash
#
# scripts/backup_db.sh — snapshot the live Arctos SQLite database.
#
# WHEN TO RUN
#   Run this script BEFORE every Alembic migration that mutates the schema or
#   data — that is, before every invocation of `make db-migrate` (or the raw
#   `uv run alembic upgrade head`). Any migration that adds a constraint,
#   alters a column type, drops a column, or rebuilds a table is potentially
#   destructive; skipping a backup before one risks data loss with no
#   recovery path. Migrations that are pure no-ops (e.g. an empty baseline)
#   do not need a backup, but running this script anyway is the cheapest way
#   to verify the backup path and instance-folder permissions are correctly
#   configured.
#
# WHAT IT DOES
#   Uses SQLite's online `.backup` command (not `cp`) so the snapshot is
#   internally consistent even if the application is mid-write — `.backup`
#   acquires the right SQLite locks and copies pages atomically.
#
# OUTPUT
#   Snapshots are written to `backups/<source_basename>-<tag>-<unix_ts>.db`.
#   The default tag is `pre-migration`; pass a more descriptive tag
#   explicitly to make the filename self-documenting:
#
#     scripts/backup_db.sh                       # backups/tournament-pre-migration-<ts>.db
#     scripts/backup_db.sh add-unique-email      # backups/tournament-add-unique-email-<ts>.db
#     scripts/backup_db.sh pre-drop-refs-column  # backups/tournament-pre-drop-refs-column-<ts>.db
#
# CONFIGURATION
#   ARCTOS_DB_PATH    Absolute path to the SQLite file. If unset, defaults
#                     to `<repo>/instance/tournament.db` (Flask's instance
#                     folder convention).
#   ARCTOS_BACKUP_DIR Directory the snapshot is written into. If unset,
#                     defaults to `<repo>/backups/`.
#
# EXIT CODES
#   0   Backup written successfully.
#   1   Source database does not exist or `.backup` failed.
#   2   `sqlite3` CLI not found in PATH.
#
# RECOVERY
#   To restore a snapshot, stop the application, then:
#
#     cp backups/tournament-<tag>-<ts>.db instance/tournament.db
#     rm -f instance/tournament.db-shm instance/tournament.db-wal
#
#   The WAL/SHM sidecars must be removed because they belong to the old
#   database file; SQLite recreates them on the next connection.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${ARCTOS_DB_PATH:-$REPO_ROOT/instance/tournament.db}"
BACKUP_DIR="${ARCTOS_BACKUP_DIR:-$REPO_ROOT/backups}"
TAG="${1:-pre-migration}"

if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "error: sqlite3 CLI not found in PATH (install with 'sudo apt-get install sqlite3' or 'brew install sqlite')" >&2
    exit 2
fi

if [ ! -f "$DB_PATH" ]; then
    echo "error: database not found at $DB_PATH" >&2
    echo "       set ARCTOS_DB_PATH to override the default location" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

SRC_BASENAME="$(basename "$DB_PATH" .db)"
TIMESTAMP="$(date +%s)"
DEST="$BACKUP_DIR/${SRC_BASENAME}-${TAG}-${TIMESTAMP}.db"

if [ -e "$DEST" ]; then
    echo "error: refusing to overwrite existing backup at $DEST" >&2
    exit 1
fi

echo "Backing up $DB_PATH"
echo "         -> $DEST"
sqlite3 "$DB_PATH" ".backup '$DEST'"

# Sanity check: SQLite's PRAGMA integrity_check returns "ok" on a valid file.
INTEGRITY="$(sqlite3 "$DEST" "PRAGMA integrity_check;" | head -n 1)"
if [ "$INTEGRITY" != "ok" ]; then
    echo "error: backup failed integrity check (got: $INTEGRITY)" >&2
    exit 1
fi

SIZE_HUMAN="$(du -h "$DEST" | cut -f1)"
echo "Backup complete (${SIZE_HUMAN}, integrity: ok)."
