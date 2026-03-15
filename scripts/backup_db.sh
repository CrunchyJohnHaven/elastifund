#!/bin/bash
set -e
DB="/home/ubuntu/polymarket-trading-bot/data/btc_5min_maker.db"
BACKUP_DIR="/home/ubuntu/polymarket-trading-bot/data/backups"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
sqlite3 "$DB" ".backup $BACKUP_DIR/btc5_backup_${TIMESTAMP}.db"
# Keep only last 7 backups
ls -tp "$BACKUP_DIR"/btc5_backup_*.db | tail -n +8 | xargs -r rm --
echo "Backup complete: btc5_backup_${TIMESTAMP}.db ($(ls $BACKUP_DIR | wc -l) backups retained)"
