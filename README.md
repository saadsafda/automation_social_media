# TikTok Comment Reply Bot — CorpusIQ

Automated TikTok Studio comment reply system with a FastAPI backend for Next.js integration.

## Features

- **Auto-login** via Google on TikTok Studio
- **Scans all comments** and detects unreplied ones
- **Generates warm, on-brand replies** (template-based + optional OpenAI)
- **Scrolls & processes** all visible comments
- **FastAPI REST API** for triggering jobs from your Next.js app
- **Background job execution** with polling support

---

## Quick Start

### 1. Install dependencies

```bash
cd automation_social_flow
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

Copy `.env.example` → `.env` and fill in your values (already pre-filled for you).

### 3. Run the bot standalone

```bash
python run_bot.py
```

### 4. Run the API server

```bash
python main.py
# or
uvicorn app.api:app --host 0.0.0.0 --port 8000 --reload
```

---

## API Endpoints

| Method | Endpoint               | Description                          |
|--------|------------------------|--------------------------------------|
| GET    | `/health`              | Health check                         |
| POST   | `/api/job/run`         | Trigger a reply job (async)          |
| GET    | `/api/job/{job_id}`    | Get job status & report              |
| GET    | `/api/jobs`            | List all jobs                        |
| POST   | `/api/reply/generate`  | Preview a reply for a comment        |

### Example: Trigger a job

```bash
curl -X POST http://localhost:8000/api/job/run
```

Response:
```json
{
  "job_id": "abc-123",
  "status": "pending",
  "report": null
}
```

### Example: Poll job status

```bash
curl http://localhost:8000/api/job/abc-123
```

### Example: Generate reply preview

```bash
curl -X POST http://localhost:8000/api/reply/generate \
  -H "Content-Type: application/json" \
  -d '{"comment_text": "This is amazing content!"}'
```

---

## Next.js Integration

See `app/nextjs_example.ts` for:
- TypeScript API client with full types
- `pollJobUntilDone()` helper
- React hook example (`useTikTokBot`)
- Next.js API route example

### Setup in your Next.js project:

1. Copy `app/nextjs_example.ts` → `lib/bot-api.ts` in your Next.js app
2. Add to `.env.local`:
   ```
   NEXT_PUBLIC_BOT_API_URL=http://localhost:8000
   ```
3. Use the functions in your components:
   ```tsx
   import { triggerJob, pollJobUntilDone } from "@/lib/bot-api";
   ```

---

## Project Structure

```
automation_social_flow/
├── .env                  # Environment variables
├── .env.example          # Template
├── requirements.txt      # Python dependencies
├── main.py               # API server entry point
├── run_bot.py            # Standalone bot runner
├── README.md
└── app/
    ├── __init__.py
    ├── config.py          # Settings loader
    ├── browser.py         # Selenium Chrome driver setup
    ├── reply_generator.py # Reply generation (templates + OpenAI)
    ├── tiktok_bot.py      # Core bot logic
    ├── schemas.py         # Pydantic models
    ├── api.py             # FastAPI endpoints
    └── nextjs_example.ts  # Next.js integration code
```

---

## Notes

- The bot uses Chrome with the `openclaw` profile so existing TikTok login sessions persist.
- TikTok Studio's DOM changes frequently — selectors may need updating.
- For production, set `HEADLESS=true` in `.env`.
- Add your OpenAI API key for smarter, context-aware replies.
