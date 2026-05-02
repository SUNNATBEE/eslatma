#!/usr/bin/env bash
# Lokal / deploydan oldin to'liq CI: Ruff, compileall, unittest, pytest, Playwright.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export BOT_TOKEN="${BOT_TOKEN:-ci-placeholder-not-a-real-secret}"

echo "==> ruff check"
ruff check .

echo "==> ruff format --check"
ruff format --check .

echo "==> python -m compileall"
python -m compileall -q .

echo "==> unittest"
python -m unittest discover -s tests -p "test_*.py" -v

echo "==> pytest"
pytest tests/ -v --tb=short

echo "==> playwright (npm run test:qa — barcha e2e, PW_WORKERS=1)"
PW_WORKERS=1 npm run test:qa

echo ""
echo "OK: barcha CI tekshiruvlari muvaffaqiyatli tugadi."
