# BillShield

Turn a bill you do not trust into one message worth sending.

Built from [c8-db](https://github.com/Siddhant-Goswami/c8-db)'s step 08: a same-origin
HTML/CSS/JavaScript client, FastAPI server, server-side Groq and Supabase REST.
The base example is preserved in `examples/base-08-supabase-api`.

## Run locally

Python 3.11+:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env  # only if .env does not already exist
.\.venv\Scripts\python.exe -m uvicorn api.index:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Do not open `index.html` directly or use Live Server.
The supplied local `.env` is ignored by Git. Never commit it.

`STORAGE_MODE=local` uses SQLite and private snapshots in `.local/`, surviving restart.
This mode is labeled in the app. Groq is optional for manual entry and template drafting.
Browser cookies identify history; clearing them loses access.

## Connect Supabase

1. Run `supabase/schema.sql` in your project's SQL Editor.
2. Enable anonymous sign-ins under Authentication → Sign In / Providers.
3. Set `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` in `.env`.
4. Set `STORAGE_MODE=supabase`, then restart.

The publishable key cannot run migrations or enable authentication. No service-role key
is needed: the server obtains a user JWT in HTTP-only, SameSite=Strict cookies, and all
tables use row-level security. The private `masked-bills` bucket has owner-folder policies.
Inserts use an invoker-rights transactional RPC. Do not disable RLS.
Set `COOKIE_SECURE=true` on HTTPS. Anonymous sessions have no recovery/account-linking UI.

## Workflow

1. Upload JPEG/PNG/WebP or a 1–3-page PDF, up to 10 MB, with consent to Groq processing.
2. Correct lines, types, amounts, tax bases/rates, dates, and the promised price/source.
3. Confirm fields and remove personal details before saving.
4. Inspect exact arithmetic, recurrence notes, late-fee checks and missing information.
5. Select disputed lines, draft, edit, copy or open email.
6. After actually sending, mark it sent. Events record time, final text and words changed.
7. Reopen reviews, add evidence as a new review, export records, or delete them.

Code inserts every monetary amount into the message. Optional AI replaces only the
greeting and closing. Original uploads are never persisted: a sanitized SVG reconstruction
is stored and clearly labeled. Regex masking cannot reliably find arbitrary names/addresses;
users must remove them before confirming. Unknown fees are not declared fraudulent.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Covers money, tax, credits, verdicts, recurrence, dates, AI number rejection, the complete
API workflow, ownership isolation, deletion, validation and cross-origin write rejection.

## Deploy to Vercel

The deployment targets Python 3.12 via `.python-version`, matching the Vercel runtime.
The application's supported Python range is declared in `pyproject.toml`.

Import this repository as a FastAPI Python project, with repository root as root directory.
`app.py` exports the application from `api/index.py`; `pyproject.toml` explicitly declares
the entry point. `public/` contains CDN-served assets. Leave build and output-directory
overrides unset; do not set the root directory to `public` or `api`. Set the variables from
`.env.example` in Vercel, with `STORAGE_MODE=supabase` and `COOKIE_SECURE=true`.
Configure Supabase first. Local mode refuses requests on Vercel because its filesystem
is ephemeral. Plan upload/time limits may be lower than the app's local limits.

In Project Settings → Environment Variables, add these for Production (and Preview
if testing preview deployments), then redeploy:

| Name | Value |
|---|---|
| `GROQ_API_KEY` | Copy from your local `.env` |
| `SUPABASE_URL` | Your project's `https://…supabase.co` URL |
| `SUPABASE_PUBLISHABLE_KEY` | Copy from your local `.env` |
| `STORAGE_MODE` | `supabase` |
| `COOKIE_SECURE` | `true` |
| `GROQ_VISION_MODEL` | `qwen/qwen3.8-27b` |
| `GROQ_TEXT_MODEL` | `openai/gpt-oss-120b` |

The GitHub repo does not contain `.env`, so importing it does not copy credentials.
`/api/health` should return JSON. HTML or a 404 usually indicates routing or deployment
protection; a 500 requires checking Vercel runtime logs. A JSON setup error from
`/api/bills` identifies missing configuration or a Supabase setup problem.

## Submission and limits

See `docs/SUBMISSION.md`. The success bar is **actually sent, with fewer than 20 words changed**.
Copying/email opening do not count as sending. Sending is self-reported, not email-provider verified.
For production, add shared rate limiting, anonymous-auth CAPTCHA, account recovery and retention policies.

Sources: [brief](https://100x-curriculum.vercel.app/c8/module-2/hackathon/billshield),
[Groq vision](https://console.groq.com/docs/vision),
[Supabase anonymous auth](https://supabase.com/docs/guides/auth/auth-anonymous).
