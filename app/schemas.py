"""Pydantic schemas for API request / response models."""

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ReplyDetail(BaseModel):
    username: str
    comment_text: str
    reply_text: str
    status: str = "sent"


class JobReportResponse(BaseModel):
    started_at: str = ""
    finished_at: str = ""
    total_comments: int = 0
    already_replied: int = 0
    new_replies: int = 0
    failed_replies: int = 0
    message: str = ""
    replies: list[ReplyDetail] = []


class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # pending | running | completed | failed
    report: JobReportResponse | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    service: str = "tiktok-comment-bot"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class RunJobRequest(BaseModel):
    """Optional overrides when triggering a job."""
    headless: bool | None = Field(None, description="Override headless mode")
    dry_run: bool = Field(False, description="If true, scan only — do not post replies")


class GenerateReplyRequest(BaseModel):
    comment_text: str = Field(..., min_length=1, description="The comment to reply to")


class GenerateReplyResponse(BaseModel):
    comment_text: str
    reply_text: str
