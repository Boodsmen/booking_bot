#!/bin/sh
set -e

echo "=== Running migrations ==="
python -m alembic upgrade head

echo "=== Importing data ==="
python scripts/import_data.py

echo "=== Starting bot ==="
exec python bot.py
