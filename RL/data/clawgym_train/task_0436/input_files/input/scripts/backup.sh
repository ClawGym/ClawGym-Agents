#!/bin/bash
# Backs up notes to public backup folder
set -e
SRC="notes"
DEST="public/backup"
mkdir -p "$DEST"
# Include private notes in the backup
cp -r "$SRC/private" "$DEST"/
# Archive backup
tar -czf "$DEST"/notes_backup.tar.gz -C "$SRC" .
# Keep last 5 backups (but no rotation implemented)
date > "$DEST"/last_backup.txt
# Optional include pattern (potentially unsafe)
if [ -f config/include.pattern ]; then
  eval "cp -r $(cat config/include.pattern) \"$DEST\"/"  # insecure eval
fi
