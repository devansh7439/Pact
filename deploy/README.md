# Deploying the Pact demo (free tiers)

| Piece | Host | Source |
|---|---|---|
| `pact-merchant` (merchant-api, FastAPI) | Render, free web service | [`render.yaml`](../render.yaml) |
| `pact-buyer` (buyer agent, FastAPI) | Render, free web service | [`render.yaml`](../render.yaml) |
| `web/` (Next.js console, judge page, buyer UI) | Vercel, Hobby | dashboard settings below |

Nothing here costs money. PayPal runs in sandbox, or in fixture mode with no credentials, and the LLM is optional (templates without it).

## What the free tiers mean for the demo

- **Sleep.** A Render free service sleeps after ~15 min idle. The first request after that takes about a minute. The two services sleep and wake **independently**.
- **Empty disk on wake.** Render's free filesystem is ephemeral, so each service's SQLite DB is empty after every wake or redeploy. `JUDGE_MODE` and `deploy/warmup.py` re-seed it. Fixed signing keys (step 1) keep the buyer agent's identity stable, so re-seeding just works.
- **Hours.** Free instance hours are shared across a workspace (750/month at the time of writing), so you can't keep both services awake around the clock. Warm them up right before someone looks.
- **Memory.** 512 MB. The merchant loads the recovery model at about 250 MB. `render.yaml` pins BLAS to one thread; without that, memory use balloons.

Check Render's and Vercel's current free-tier terms before relying on these numbers.

## First deploy

The services need each other's URLs, so this takes two passes.

**1. Generate two signing keys** (once, locally; keep them secret):

```bash
python -m shared.prp.keys generate   # → MERCHANT_SIGNING_KEY  (the "private" line)
python -m shared.prp.keys generate   # → BUYER_SIGNING_KEY
```

**2. Render: create both services.** Dashboard → **New → Blueprint** → pick this repo. Render reads `render.yaml` and asks for each `sync: false` value:

| Service | Variable | Value for now |
|---|---|---|
| pact-merchant | `MERCHANT_SIGNING_KEY` | key from step 1 |
| pact-merchant | `WEB_PUBLIC_URL`, `BUYER_PUBLIC_URL` | leave blank, filled in step 4 |
| pact-buyer | `BUYER_SIGNING_KEY` | key from step 1 |
| pact-buyer | `MERCHANT_BASE_URL`, `WEB_ORIGINS` | leave blank, filled in step 4 |
| both | `PAYPAL_*`, `LLM_*` | blank = fixture mode / templates |

The first merchant build trains the model (about 15 s on a laptop). Note both public URLs, e.g. `https://pact-merchant-xxxx.onrender.com`.

**3. Vercel: import the repo.**
- **Root Directory:** `web` (Next.js is detected automatically).
- **Environment variables:** `NEXT_PUBLIC_MERCHANT_URL` = the merchant URL and `NEXT_PUBLIC_BUYER_URL` = the buyer URL.
  These are baked in at build time, so **redeploy Vercel after changing them.**
- Deploy, then note the production URL, e.g. `https://pact-xxxx.vercel.app`.

**4. Render: link everything** (Environment tab on each service, then save; Render restarts the service):

| Service | Variable | Value |
|---|---|---|
| pact-merchant | `WEB_PUBLIC_URL` | the Vercel production URL (exactly one origin, no trailing slash) |
| pact-merchant | `BUYER_PUBLIC_URL` | the buyer's Render URL |
| pact-buyer | `MERCHANT_BASE_URL` | the merchant's Render URL |
| pact-buyer | `WEB_ORIGINS` | the Vercel production URL (comma-separated if you add more) |

Each service's own public URL (`MERCHANT_PUBLIC_URL`, `BUYER_PUBLIC_URL` on the buyer) defaults to Render's `RENDER_EXTERNAL_URL`. You only need to set them if you add a custom domain.

**5. Warm up and seed:**

```bash
MERCHANT_URL=https://pact-merchant-xxxx.onrender.com \
BUYER_URL=https://pact-buyer-xxxx.onrender.com \
python -m deploy.warmup
```

It wakes both services, seeds Maya's mandate and her agent's registration if needed, runs judge scenario S1 end to end, then resets to a clean slate. It ends with `ready: demo is warm, seeded and reset`. It's safe to run any number of times.

## Before every demo or judging window

Run step 5 again. If either service has slept, its DB is empty, and the script re-seeds it.

## Optional: PayPal sandbox

Set `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` on pact-merchant (developer.paypal.com → Apps & Credentials → Sandbox). `/health` then reports `"paypal": "live"` instead of `"fixture"`. For webhooks, register `https://<merchant-url>/paypal/webhooks` in the sandbox app and set `PAYPAL_WEBHOOK_ID`.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Browser console shows CORS errors | `WEB_PUBLIC_URL` (merchant) or `WEB_ORIGINS` (buyer) doesn't exactly match the Vercel URL. Vercel *preview* URLs differ from production, so use the production URL. |
| Web app calls `localhost:8100` | `NEXT_PUBLIC_*` were missing at Vercel build time: set them and redeploy. |
| `warmup` keeps re-seeding and S1 still fails | `MERCHANT_SIGNING_KEY` / `BUYER_SIGNING_KEY` aren't set, so each wake is a new identity. Set both. Last resort: restart both services, then rerun `warmup`. |
| Merchant build or boot runs out of memory | Check that `OPENBLAS_NUM_THREADS=1` is still set on pact-merchant. |
| `/health` shows `"mode": "review_first"` | `JUDGE_MODE` isn't `true` on pact-merchant. |

## Verified locally (2026-11-12)

The start commands were run as `render.yaml` defines them (`$PORT`, `0.0.0.0`, fixed keys, empty DBs, `JUDGE_MODE=true`). Results:
- `deploy.warmup` succeeds on a fresh boot, on a rerun, after a buyer-only wipe and after a merchant-only wipe, with no manual restart in any case.
- Merchant peak memory with the model loaded and one BLAS thread: about 250 MB.

The Render and Vercel dashboards themselves haven't been exercised yet.
