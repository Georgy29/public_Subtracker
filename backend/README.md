## Запуск

```bash
cp .env.example .env  # заполнить PLAID_CLIENT_ID/SECRET
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py