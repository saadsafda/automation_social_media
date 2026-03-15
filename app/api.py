"""
FastAPI application — exposes endpoints for the TikTok Comment Reply Bot.

Endpoints:
    GET  /health              → service health check
    POST /api/job/run         → trigger a reply job (async in background)
    GET  /api/job/{job_id}    → poll job status
    GET  /api/jobs            → list all jobs
    POST /api/reply/generate  → generate a reply for a given comment text
"""

import uuid
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import settings
from app.schemas import (
    HealthResponse,
    RunJobRequest,
    JobStatusResponse,
    JobReportResponse,
    GenerateReplyRequest,
    GenerateReplyResponse,
)
from app.tiktok_bot import run_reply_job
from app.reply_generator import generate_reply


# ---------------------------------------------------------------------------
# In-memory job store (swap for Redis / DB in production)
# ---------------------------------------------------------------------------

_jobs: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("TikTok Comment Bot API starting up…")
    yield
    logger.info("Shutting down…")


app = FastAPI(
    title="TikTok Comment Reply Bot API",
    version="1.0.0",
    description="Automates replying to TikTok Studio comments for CorpusIQ",
    lifespan=lifespan,
)

# CORS — allow your Next.js frontend to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health():
    return HealthResponse()


@app.post("/api/job/run", response_model=JobStatusResponse, tags=["Jobs"])
async def trigger_job(body: RunJobRequest | None = None):
    """
    Trigger a new comment-reply job.

    The job runs in a background thread so the API returns immediately
    with a `job_id` you can poll via GET /api/job/{job_id}.
    """
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report": None,
    }

    def _run():
        _jobs[job_id]["status"] = "running"
        try:
            report = run_reply_job()
            _jobs[job_id]["report"] = report
            _jobs[job_id]["status"] = "completed"
        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}")
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["report"] = {"message": str(e)}

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return JobStatusResponse(job_id=job_id, status="pending")


@app.get("/api/job/{job_id}", response_model=JobStatusResponse, tags=["Jobs"])
async def get_job_status(job_id: str):
    """Poll the status of a running or completed job."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    entry = _jobs[job_id]
    report = None
    if entry.get("report"):
        report = JobReportResponse(**entry["report"])

    return JobStatusResponse(
        job_id=job_id,
        status=entry["status"],
        report=report,
    )


@app.get("/api/jobs", tags=["Jobs"])
async def list_jobs():
    """List all jobs (most recent first)."""
    result = []
    for jid, entry in reversed(list(_jobs.items())):
        result.append({
            "job_id": jid,
            "status": entry["status"],
            "created_at": entry.get("created_at"),
        })
    return result


@app.post(
    "/api/reply/generate",
    response_model=GenerateReplyResponse,
    tags=["Replies"],
)
async def generate_reply_endpoint(body: GenerateReplyRequest):
    """
    Generate a reply for a given comment text without posting it.
    Useful for previewing replies in your Next.js UI.
    """
    reply_text = generate_reply(body.comment_text)
    return GenerateReplyResponse(
        comment_text=body.comment_text,
        reply_text=reply_text,
    )
