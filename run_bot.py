"""
Standalone script — run the bot directly without the API server.
Usage:  python run_bot.py
"""

import json
from app.tiktok_bot import run_reply_job

if __name__ == "__main__":
    print("🚀 Starting TikTok Comment Reply Bot…\n")
    report = run_reply_job()
    print("\n" + "=" * 60)
    print("📊 JOB REPORT")
    print("=" * 60)
    print(json.dumps(report, indent=2, ensure_ascii=False))
