# Millionaire Tracker — Full Bundle (v3)

One repo = API + Frontend PWA. Run the server and open `http://localhost:9000/app/`.

## Quick Start

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# Config
# Windows: copy .env.example .env
# macOS/Linux: cp .env.example .env

# Run
uvicorn app:app --reload --host 0.0.0.0 --port 9000

# Open the app
# http://localhost:9000/app/
# API docs: http://localhost:9000/docs
```

### Login
- Enter a username (no password). A user record is created and a JWT is issued/stored in `localStorage`.
- Data is separated per username in SQLite.

### Data
- Users store **assumptions**, **holdings**, **price cache**, and **projections** (with checkpoint points).
- Projection saves on every run.

### Notes
- iOS PWA offline requires HTTPS; for local testing over HTTP it runs fine in Safari/Chrome but offline install is limited.
- To enable Alpha Vantage, set `ALPHA_VANTAGE_KEY` in `.env` or per-user via assumptions (UI uses server value by default).
