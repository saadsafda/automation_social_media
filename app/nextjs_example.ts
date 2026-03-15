/**
 * Next.js Integration Example — copy these into your Next.js app.
 *
 * Install:  npm install axios  (or use native fetch)
 *
 * Configure your API base URL in .env.local:
 *   NEXT_PUBLIC_BOT_API_URL=http://localhost:8000
 */

// ─── lib/bot-api.ts ──────────────────────────────────────────────────────────

const API_BASE = process.env.NEXT_PUBLIC_BOT_API_URL || "http://localhost:8000";

// Types
export interface ReplyDetail {
  username: string;
  comment_text: string;
  reply_text: string;
  status: string;
}

export interface JobReport {
  started_at: string;
  finished_at: string;
  total_comments: number;
  already_replied: number;
  new_replies: number;
  failed_replies: number;
  message: string;
  replies: ReplyDetail[];
}

export interface JobStatus {
  job_id: string;
  status: "pending" | "running" | "completed" | "failed";
  report: JobReport | null;
}

export interface GenerateReplyResponse {
  comment_text: string;
  reply_text: string;
}

// ─── API functions ───────────────────────────────────────────────────────────

/** Health check */
export async function checkHealth(): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/health`);
  return res.json();
}

/** Trigger a new reply job — returns immediately with a job_id */
export async function triggerJob(): Promise<JobStatus> {
  const res = await fetch(`${API_BASE}/api/job/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  return res.json();
}

/** Poll job status by ID */
export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${API_BASE}/api/job/${jobId}`);
  return res.json();
}

/** List all jobs */
export async function listJobs(): Promise<
  { job_id: string; status: string; created_at: string }[]
> {
  const res = await fetch(`${API_BASE}/api/jobs`);
  return res.json();
}

/** Generate a reply preview (without posting) */
export async function generateReply(
  commentText: string
): Promise<GenerateReplyResponse> {
  const res = await fetch(`${API_BASE}/api/reply/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ comment_text: commentText }),
  });
  return res.json();
}

/**
 * Poll a job until it completes or fails.
 * Calls onUpdate on each poll so you can update UI.
 */
export async function pollJobUntilDone(
  jobId: string,
  onUpdate?: (status: JobStatus) => void,
  intervalMs = 3000,
  maxAttempts = 100
): Promise<JobStatus> {
  for (let i = 0; i < maxAttempts; i++) {
    const status = await getJobStatus(jobId);
    onUpdate?.(status);

    if (status.status === "completed" || status.status === "failed") {
      return status;
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error("Job polling timed out");
}


// ─── Example React hook (app/hooks/useTikTokBot.ts) ─────────────────────────
/*
import { useState, useCallback } from "react";
import { triggerJob, pollJobUntilDone, JobStatus } from "@/lib/bot-api";

export function useTikTokBot() {
  const [loading, setLoading] = useState(false);
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runJob = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { job_id } = await triggerJob();
      const finalStatus = await pollJobUntilDone(job_id, setJobStatus);
      setJobStatus(finalStatus);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  return { loading, jobStatus, error, runJob };
}
*/


// ─── Example Next.js API Route (app/api/bot/run/route.ts) ────────────────────
/*
import { NextResponse } from "next/server";
import { triggerJob, pollJobUntilDone } from "@/lib/bot-api";

export async function POST() {
  try {
    const { job_id } = await triggerJob();
    const result = await pollJobUntilDone(job_id);
    return NextResponse.json(result);
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
*/
