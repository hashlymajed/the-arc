#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo ""
echo "  ┌────────────────────────────────────────────┐"
echo "  │   The Arc — Aldar Comms Platform           │"
echo "  └────────────────────────────────────────────┘"
echo ""

if [ ! -d "venv" ]; then
    echo "  First run — setting up environment (takes ~2 min)…"
    python3 -m venv venv
    source venv/bin/activate
    pip install -q -r requirements.txt
    echo "  Setup complete."
else
    source venv/bin/activate
fi

(sleep 3 && open "http://localhost:8000") &

echo "  → http://localhost:8000  (opening in browser…)"
echo "  → Press Ctrl+C to stop"
echo ""

python app.py
