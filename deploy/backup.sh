#!/usr/bin/env bash
# =============================================================================
#  Backup script.
#
#  Backs up the three things that cannot be regenerated:
#
#    1. .env          - in particular ENCRYPTION_KEY. Without it every stored
#                       OAuth token is unreadable and each channel has to be
#                       reconnected by hand.
#    2. the database  - videos, users, statistics history, settings.
#    3. media/        - the video files themselves (optional, and large).
#
#  Usage:
#      sudo bash /opt/socialbot/deploy/backup.sh                 # config + DB
#      sudo bash /opt/socialbot/deploy/backup.sh --with-media    # everything
#
#  Run it nightly from cron:
#      0 4 * * * /opt/socialbot/deploy/backup.sh >> /var/log/socialbot-backup.log 2>&1
# =============================================================================

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/socialbot}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/socialbot}"
KEEP_DAYS="${KEEP_DAYS:-30}"
WITH_MEDIA=0

[[ "${1:-}" == "--with-media" ]] && WITH_MEDIA=1

STAMP="$(date -u +%Y%m%d-%H%M%S)"
TARGET="$BACKUP_DIR/$STAMP"
mkdir -p "$TARGET"

echo "[$(date -u +%FT%TZ)] Backing up to $TARGET"

# --- 1. Configuration -------------------------------------------------------
if [[ -f "$INSTALL_DIR/.env" ]]; then
    cp "$INSTALL_DIR/.env" "$TARGET/env.backup"
    chmod 600 "$TARGET/env.backup"
    echo "  .env copied"
fi

# --- 2. Database ------------------------------------------------------------
DB_FILE="$INSTALL_DIR/data/socialbot.db"
if [[ -f "$DB_FILE" ]]; then
    # sqlite3's .backup takes a consistent copy even while the app is writing;
    # a plain cp can capture a torn file mid-transaction.
    if command -v sqlite3 >/dev/null; then
        sqlite3 "$DB_FILE" ".backup '$TARGET/socialbot.db'"
    else
        cp "$DB_FILE" "$TARGET/socialbot.db"
        echo "  (sqlite3 not installed - used a plain copy)"
    fi
    echo "  database copied"
fi

# --- 3. Media (optional) ----------------------------------------------------
if [[ $WITH_MEDIA -eq 1 && -d "$INSTALL_DIR/media" ]]; then
    tar -czf "$TARGET/media.tar.gz" -C "$INSTALL_DIR" media
    echo "  media archived ($(du -h "$TARGET/media.tar.gz" | cut -f1))"
fi

# --- 4. Prune old backups ---------------------------------------------------
find "$BACKUP_DIR" -maxdepth 1 -type d -name '20*' -mtime "+$KEEP_DAYS" -exec rm -rf {} + 2>/dev/null || true

echo "[$(date -u +%FT%TZ)] Backup finished. Kept the last $KEEP_DAYS days."
echo
echo "  To restore: stop the services, copy env.backup back to .env and"
echo "  socialbot.db back to data/, then start the services again."
