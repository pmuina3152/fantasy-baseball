# Fantasy Baseball Z-Score Rankings (2025)

A full-stack web app that pulls 2025 MLB season stats, computes fantasy
z-scores for hitters and pitchers, and displays a ranked Top-100 table.

---

## 1 — Folder Structure

```
fantasy-baseball/
├── backend/
│   ├── config.py          ← configurable constants (MIN_AB, MIN_IP, cache TTL)
│   ├── data_fetcher.py    ← pulls FanGraphs data via pybaseball, caches to disk
│   ├── zscore.py          ← z-score computation (counting + contribution-based rate)
│   ├── main.py            ← FastAPI app with /api/hitters and /api/pitchers
│   └── requirements.txt
│
├── frontend/
│   ├── app/
│   │   ├── layout.tsx     ← root HTML shell
│   │   ├── page.tsx       ← homepage with toggle + table
│   │   └── globals.css    ← Tailwind directives + scrollbar styles
│   ├── components/
│   │   ├── Toggle.tsx     ← Hitters / Pitchers sliding toggle
│   │   └── PlayerTable.tsx← ranked stats table with score bars + z-colours
│   ├── lib/
│   │   ├── types.ts       ← TypeScript interfaces
│   │   └── api.ts         ← fetch wrappers for FastAPI endpoints
│   ├── package.json
│   ├── tsconfig.json
│   ├── next.config.js
│   ├── tailwind.config.ts
│   ├── postcss.config.js
│   └── .env.local         ← NEXT_PUBLIC_API_URL=http://localhost:8000
│
└── README.md
```

---

## 2 — One-Time Setup (Windows PowerShell)

### Python backend

```powershell
# 1. Go to the backend folder
cd C:\Users\pmuin\Documents\fantasy-baseball\backend

# 2. Create a virtual environment
python -m venv venv

# 3. Activate it
.\venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install -r requirements.txt
```

> If you see "running scripts is disabled", run this first (once):
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### Node / Next.js frontend

```powershell
# 1. Go to the frontend folder
cd C:\Users\pmuin\Documents\fantasy-baseball\frontend

# 2. Install packages  (requires Node.js 18+ — download from nodejs.org)
npm install
```

---

## 3 — Run Locally

You need **two terminal windows open at the same time**.

### Terminal 1 — Backend (FastAPI)

```powershell
cd C:\Users\pmuin\Documents\fantasy-baseball\backend
.\venv\Scripts\Activate.ps1
uvicorn main:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

Test it: open http://localhost:8000/health → should return `{"status":"ok"}`
Interactive docs: http://localhost:8000/docs

### Terminal 2 — Frontend (Next.js)

```powershell
cd C:\Users\pmuin\Documents\fantasy-baseball\frontend
npm run dev
```

You should see:
```
▲ Next.js — ready on http://localhost:3000
```

Open http://localhost:3000 in your browser.

---

## 4 — Run Locally Checklist

- [ ] Python 3.10+ installed (`python --version`)
- [ ] Node.js 18+ installed (`node --version`)
- [ ] Backend venv created and activated
- [ ] `pip install -r requirements.txt` completed without errors
- [ ] `npm install` completed without errors
- [ ] Backend running on port 8000 (Terminal 1)
- [ ] Frontend running on port 3000 (Terminal 2)
- [ ] http://localhost:8000/health returns `{"status":"ok"}`
- [ ] http://localhost:3000 loads the site
- [ ] Toggle switches between Hitters / Pitchers
- [ ] Table populates (first load takes 15–45 s while pybaseball downloads)

---

## 5 — API Reference

| Endpoint | Params | Description |
|---|---|---|
| `GET /health` | — | Health check |
| `GET /api/hitters` | `season=2025`, `limit=100` | Top hitters by z-score |
| `GET /api/pitchers` | `season=2025`, `limit=100` | Top pitchers by z-score |

Both `/api/hitters` and `/api/pitchers` return:
```json
{
  "players": [ { "rank": 1, "Name": "...", "Team": "...", ... } ],
  "count": 100,
  "season": 2025
}
```

---

## 6 — Z-Score Logic

### Counting stats (R, HR, RBI, SB, K, W, SV, HLD)
```
z = (player_value - pool_mean) / pool_std
```

### Rate stats — contribution-weighted (AVG, ERA, WHIP)
```
AVG_contrib  = (playerAVG  - leagueAVG)  × AB
ERA_contrib  = (leagueERA  - playerERA)  × IP   ← inverted so lower ERA = positive
WHIP_contrib = (leagueWHIP - playerWHIP) × IP   ← inverted so lower WHIP = positive

z = (contrib - mean_contrib) / std_contrib
```

### Total & normalisation
```
hitter_total_z  = zR + zHR + zRBI + zSB + zAVG
pitcher_total_z = zK + zW + zSV + zHLD + zERA + zWHIP

score_0_100 = 100 × (total_z - min_total_z) / (max_total_z - min_total_z)
```

---

## 7 — Caching

- Results are cached to `backend/cache/` as Parquet files.
- Cache is valid for **12 hours** (configurable in `backend/config.py`).
- To force a refresh, delete the files in `backend/cache/`.

---

## 8 — Configurable Constants (`backend/config.py`)

| Constant | Default | Meaning |
|---|---|---|
| `MIN_AB` | `100` | Minimum at-bats for hitter pool |
| `MIN_IP` | `20.0` | Minimum innings pitched for pitcher pool |
| `CACHE_MAX_AGE_HOURS` | `12` | Hours before cache is considered stale |
| `DEFAULT_SEASON` | `2025` | Season used when none is specified |

---

## 9 — Next Step Ideas (not implemented)

These are natural next features once the MVP is running:

1. **User accounts** — save a custom team roster and see its aggregate z-scores
2. **My Team page** — drag-and-drop team builder with running category totals
3. **Projections mode** — use Steamer/ZiPS projections instead of actuals
4. **Position filters** — filter table by C, 1B, 2B, SS, 3B, OF, SP, RP
5. **Season selector** — compare 2023 / 2024 / 2025 rankings
6. **Auction values** — convert z-scores to $ values for auction drafts
7. **CSV export** — download the ranked table
8. **Deployment** — containerise with Docker, host backend on Fly.io / Railway,
   frontend on Vercel
