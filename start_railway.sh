#!/bin/bash
set -e

VAULT_REPO="https://github.com/hashlymajed/the-arc"
VAULT_DIR="/data/vault"

if [ ! -d "$VAULT_DIR/.git" ]; then
    echo "Cloning vault from GitHub..."
    git clone --depth 1 "$VAULT_REPO" "$VAULT_DIR"
else
    echo "Pulling latest vault..."
    git -C "$VAULT_DIR" pull --ff-only || true
fi

echo "Vault ready at $VAULT_DIR/vault_docs"

exec uvicorn app:app --host 0.0.0.0 --port "${PORT:-8000}"
