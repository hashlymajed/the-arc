#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# Use existing venv if present, else create
if [ ! -d "venv" ]; then
  echo "Creating virtual environment…"
  python3 -m venv venv
fi

source venv/bin/activate

echo "Installing dependencies…"
pip install -q -r requirements.txt

echo ""
echo "  ┌────────────────────────────────────────────┐"
echo "  │   The Arc — Aldar Comms Platform           │"
echo "  │   http://localhost:8000                    │"
echo "  └────────────────────────────────────────────┘"
echo ""

python app.py
