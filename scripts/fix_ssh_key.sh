#!/usr/bin/env bash
# Fix the renamed Lightsail SSH key
RENAMED_KEY="$HOME/Downloads/LightsailDefaultKey-eu-west-1 (1).pem"
SYMLINK_PATH="$HOME/.ssh/lightsail.pem"

if [ -f "$RENAMED_KEY" ] && [ ! -L "$SYMLINK_PATH" ]; then
    ln -sf "$RENAMED_KEY" "$SYMLINK_PATH"
    chmod 600 "$SYMLINK_PATH"
    echo "SSH key symlink created: $SYMLINK_PATH -> $RENAMED_KEY"
else
    echo "Key already linked or source not found"
fi
