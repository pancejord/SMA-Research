# SMA rankings dashboard

A small local Next.js dashboard for the existing InfluxDB ranking reports.
Choose 2–20 completed trading sessions, optionally filter by ticker/timeframe,
choose an end date, and view the top 10–100 outfit/ticker/timeframe combinations.

## Start

From Research, install the Python dependencies if not already installed:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then start the frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open [the local dashboard](http://127.0.0.1:3000). Choose filters and click **Load
rankings**. Opening the page alone does not query InfluxDB. Without configured
credentials or dependencies, the interface shows a setup message after loading.
No sample rankings are mixed into results.

For a production build on this same machine, use `npm run build`, then
`npm start`. Run npm commands from `frontend`, keeping it inside Research.
The included commands bind to localhost; this initial dashboard is for local
use and has no authentication. Public hosting needs separate deployment/auth work.

## Connection

Use the same `INFLUX_URL`, `INFLUX_TOKEN`, `INFLUX_ORG`, and `INFLUX_BUCKET` in
Research's `.env`. A token with read permission is sufficient. No Massive key is
needed to view stored rankings. Never put database tokens in `NEXT_PUBLIC_*` variables.

The browser requests `/api/rankings`. The Next.js Node server invokes
`rankings_bridge.py`, which calls the existing `query_rankings.py` and storage
code. No query logic is duplicated, and the browser receives only report rows,
window metadata, or safe error messages. No shell commands are constructed from
filter values. Requests time out after 45 seconds and responses are not cached.

The server automatically selects Research's `.venv/Scripts/python.exe` on Windows
or `.venv/bin/python` elsewhere, falling back to Python on PATH. If you use another
environment, create `frontend/.env.local` and set `PYTHON_EXECUTABLE` to its full
executable path. Restart Next.js after changing server environment settings.

Keep Node.js, Python, the Research modules, and the environment available on the
same machine. This version uses a local Python process; it is not a static export
or a ready-to-deploy serverless app.

## Report rules

- Completed trading sessions only: weekends and holidays are excluded, and early
  closes count as one session. Today's unfinished session is excluded.
- Each outfit/ticker/timeframe stays separate. Highest raw hit count ranks first;
  ties use the most recent hit, then a stable alphabetical order.
- Reports include the final close-time candle, use saved outfit memberships, and
  select the active research version. All displayed times are Eastern Time.
- The table's small bars compare each row's hit count with the leading row, not
  a probability or a share of all physical hits.
- Data coverage depends on collection and retention. A full date window does not
  mean every session's data has been collected. OHLC preload alone creates no hits.
- Changing filters clears the previous report; click Load rankings to apply them.

The dashboard does not write data, start the scheduler, or modify live counters.
No live InfluxDB query has been run during implementation.
