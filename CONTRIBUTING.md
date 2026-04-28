# Hissa qo'shish (Contributing)

## Talablar

- Python **3.12**
- [Ruff](https://docs.astral.sh/ruff/) — lint va format
- [pytest](https://pytest.org/) — testlar

## Mahalliy o'rnatish

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env   # BOT_TOKEN va boshqalarni to'ldiring
```

## Sifat tekshiruvi (majburiy)

Bitta buyruq (CI bilan bir xil tartib):

```bash
npm ci
npx playwright install --with-deps chromium   # birinchi marta
npm run test:ci
# yoki: bash scripts/run-ci.sh
```

Qo‘lda (alohida qadamlar):

```bash
ruff check .
ruff format --check .
python -m compileall -q .
pytest tests/ -v
python -m unittest discover -s tests -p "test_*.py" -v
npm ci && npm run test:e2e
```

## Pre-commit (ixtiyoriy, tavsiya etiladi)

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

## PR qoidalari

- Kichik, izohli commitlar
- `main` ga to'g'ridan-to'g'ri push o'rniga PR
- CI yashil bo'lishi kerak (GitHub Actions)

## Kod uslubi

- Foydalanuvchiga chiqadigan matnlar: **o'zbek tili** (loyiha qoidasi)
- Yangi API xatolari: `routes.api_json.json_err` (`ok`, `error`, `code`)
