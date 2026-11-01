# Bill Tracker: personal finance & bill dashboard

FastAPI + SQLite backend, React + Tailwind (Vite) frontend. Amounts are in INR.

## Run it

**Backend** (terminal 1)
```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8010
```

**Frontend, dev mode** (terminal 2). Vite proxies `/api` to the backend on port 8010
(`FT_API_PORT=9000 npm run dev` if you run the backend elsewhere). The ports avoid the usual
8000/5173 so this can run next to other projects.
```bash
cd frontend
npm install
npm run dev          # http://localhost:5180
```

**Single-server mode.** Build once and FastAPI serves the app itself:
```bash
cd frontend && npm run build
# then open http://localhost:8010
```

The database lives at `backend/data/finance.db` (override with `FT_DB=/path/to.db`). It is never
committed to git, so cloning the repo gives nobody your data.

## Accounts

Everyone registers (email + password) and logs in; each account only ever sees its own bills,
targets and budget. Someone else's expense id simply returns 404.

- **Every new account starts empty.** `FT_SEED=1` gives each new account demo data instead
  (JioAirFiber, EatClub, Claude Pro, SIPs, credit cards, rent...).
- Logins are stored in the `users` table of the same database (email + password hash).
- Any email address can register; it is not verified. Once your own account exists, close sign-ups
  with `FT_REGISTRATION=0` (the first account can always be created).
- Data from before accounts existed is hidden from everyone; the pre-accounts database is kept as
  `finance.pre-accounts.db`.
- Passwords are hashed with PBKDF2-SHA256 (600k iterations). Sessions last 30 days in an HttpOnly,
  SameSite=Lax cookie; only a hash of the session token is stored. Logins lock for 15 minutes
  after 10 wrong passwords for an email.
- Serve it over HTTPS if it is reachable beyond your own machine; the cookie is marked Secure
  automatically when the request is HTTPS.

## What's in the dashboard

| Feature | How it works |
|---|---|
| **Upcoming bills** | Chronological timeline (7/30/90 days) grouped by date; overdue bills pinned on top. |
| **Alerts** | Banner + colour coding: **dark red** overdue, **red** due today/tomorrow, **amber** due in 2-3 days, grey later. Every state also has a text label. Optional browser notification once a day ("Enable alerts"). Tab title shows the count. |
| **Spend variance** | Per category: target vs actual with a signed deviation. `+₹1,200` = under target (green), `−₹800` = over (red). Total deviation on top. Edit targets via **Targets**. |
| **Remaining budget** | Widget = monthly budget − every bill dated in the month (paid + still to pay). Edit the budget in place and it updates as you type. |
| **Data entry** | Add/edit form with name, amount, due date, category (autocomplete + free text), recurring (one-time / weekly / monthly / quarterly / yearly). |
| **Recurring** | Marking a recurring bill paid creates the next occurrence (month-end safe: 31 Jan → 28 Feb → 31 Mar). Undo removes it again. |
| **Projected bills** | Future occurrences of recurring bills show up (marked *Projected*) in later months, the timeline, the remaining budget and variance before they exist, so next month's numbers are complete. They become real once the bill before them is paid. Only dates from today on are projected; deleting the next occurrence ends the series. Pass `projected=false` to `/api/expenses` or `/api/upcoming` to leave them out. |
| **Dark mode** | Toggle in the header; remembers your choice, defaults to the OS setting, no flash on load. |

## API (see `/docs` for the interactive version)

`POST /api/auth/register|login|logout` · `GET /api/auth/me` · `GET /api/export` ·
`GET/POST /api/expenses` · `PUT/DELETE /api/expenses/{id}` · `POST /api/expenses/{id}/pay|unpay` ·
`GET /api/upcoming?days=` · `GET /api/summary?month=YYYY-MM` · `GET /api/variance?month=YYYY-MM` ·
`GET/PUT /api/settings` · `GET /api/budgets` · `PUT/DELETE /api/budgets/{category}` · `GET /api/categories`

Date-sensitive endpoints take an optional `today=YYYY-MM-DD` so the browser's local date decides what is "due today".

## Backups

Your data is one SQLite file, so it is snapshotted automatically:

- **Daily snapshots** go to `backend/data/backups/finance-YYYY-MM-DD.db`: one when the server starts and one before the first change of each day. The newest 14 are kept.
- **Download your own data** as JSON with the download button in the header (`GET /api/export`).
  The daily snapshots above hold every account, so they stay on the server.
- **Keep copies off this disk** by pointing `FT_BACKUP_DIR` at a synced folder, e.g. `FT_BACKUP_DIR=~/Library/Mobile\ Documents/com~apple~CloudDocs/finance-backups`.
- Settings: `FT_BACKUP_KEEP=30` keeps more, `FT_BACKUP=0` turns snapshots off.

By hand, from `backend/`:
```bash
python -m app.backup                                         # snapshot now
python -m app.backup --list                                  # newest first
python -m app.backup --restore data/backups/finance-2026-11-01.db   # stop the server first
```
Restoring checks the file is a healthy database and saves the current one as `finance.before-restore.db` first.

## Tests
```bash
cd backend && python -m pytest        # 49 tests: accounts & isolation, recurrence, projections, pay/undo, urgency, summary, variance, seed, backups
cd frontend && npm test               # 25 tests: maths, formatting, login, and the full UI against a fake API
```
