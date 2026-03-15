"""
Reply Generator — produces warm, humble, on-brand replies for CorpusIQ.

Uses OpenClaw CLI (`openclaw agent`) as the primary reply engine,
with a keyword-matching template fallback.
"""

import json
import random
import re
import subprocess
from loguru import logger

from app.config import settings


# ---------------------------------------------------------------------------
# Template-based fallback replies (keyword → pool of replies)
# ---------------------------------------------------------------------------

_KEYWORD_REPLIES: dict[str, list[str]] = {
    # Positive / praise
    "love|amazing|awesome|great|fire|best|insane|goat|incredible|sick|dope|cold": [
        "Thank you so much! Really means a lot 🙏",
        "Appreciate the love! More great content on the way 🔥",
        "That means everything — thank you for watching! 💙",
        "Glad you enjoyed it! Stay tuned for what's next 🚀",
        "You're awesome for saying that, thank you! 🙌",
    ],
    # Questions
    r"\?|how|what|when|where|why|can you|will you|do you": [
        "Great question! We're building something special — stay tuned! 🙏",
        "Love the curiosity! We'll share more details soon 🔥",
        "Appreciate you asking! Keep an eye out for our next post 👀",
        "Good question — we've got some exciting things coming! 💡",
    ],
    # Requests / suggestions
    "please|make|more|tutorial|teach|show|explain|drop|upload": [
        "Noted! We hear you — more content coming soon 🔥",
        "Appreciate the suggestion! We'll definitely work on that 🙏",
        "Your feedback matters — stay tuned for more! 💪",
        "Love the enthusiasm! We're on it 🚀",
    ],
    # Support / follow
    "follow|subscribe|support|share|repost": [
        "Thank you for the support — it means the world! 🙏💙",
        "We appreciate you! More content is on the way 🔥",
        "Your support keeps us going — thank you! 🚀",
    ],
    # Emoji-heavy or short comments
    "^.{1,5}$|^[^a-zA-Z]*$": [
        "Thank you for watching! 🙏🔥",
        "Appreciate you! 💙",
        "Thanks for the love! More coming soon 🚀",
    ],
    # Criticism / negative
    "bad|worst|trash|boring|mid|overrated|hate|cringe": [
        "Appreciate the honest feedback — we're always looking to improve 🙏",
        "Thanks for sharing your thoughts! We'll keep working hard 💪",
        "We hear you — always striving to do better! 🙏",
    ],
    # Collaboration / business
    "collab|partner|work together|business|contact|dm|email": [
        "We'd love to connect! Drop us a DM or email 📩",
        "Thanks for reaching out! Let's talk — check our bio for contact info 🙏",
        "Appreciate the interest! Reach out to us anytime 💼",
    ],
}

_GENERIC_REPLIES = [
    "Thanks for watching! Really appreciate the support 🙏",
    "Thank you! More content coming soon 🔥",
    "Appreciate you taking the time to comment! 💙",
    "Thanks for being here — means a lot! 🙌",
    "Your support keeps us motivated — thank you! 🚀",
]


def _template_reply(comment_text: str) -> str:
    """Pick a reply from keyword-matched pools."""
    comment_lower = comment_text.lower().strip()

    for pattern, replies in _KEYWORD_REPLIES.items():
        if re.search(pattern, comment_lower):
            return random.choice(replies)

    return random.choice(_GENERIC_REPLIES)


# ---------------------------------------------------------------------------
# OpenClaw-powered reply (primary)
# ---------------------------------------------------------------------------

def _openclaw_reply(comment_text: str) -> str | None:
    """
    Generate a reply using the OpenClaw TUI agent via CLI.

    Runs:  openclaw agent --agent <id> --message "..." --json
    and extracts the reply from result.payloads[0].text.

    Returns None on failure so the template fallback kicks in.
    """
    prompt = (
        f"You are the social media manager for {settings.BRAND_NAME}. "
        "Generate a humble, warm, and genuine reply to a TikTok comment. "
        "Keep it 1-2 sentences, friendly, on-brand. "
        "Use 1-2 emojis max. Do NOT be generic — tailor the reply to the comment. "
        "Do NOT use hashtags. Output ONLY the reply text, nothing else.\n\n"
        f"TikTok comment: \"{comment_text}\""
    )

    cmd = [
        "openclaw", "agent",
        "--agent", settings.OPENCLAW_AGENT,
        "--message", prompt,
        "--json",
    ]

    try:
        logger.info(f"Calling OpenClaw agent '{settings.OPENCLAW_AGENT}' for reply…")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=settings.OPENCLAW_TIMEOUT,
        )

        if result.returncode != 0:
            logger.warning(f"OpenClaw exited with code {result.returncode}: {result.stderr.strip()}")
            return None

        data = json.loads(result.stdout)

        # Extract reply text from the JSON response
        payloads = data.get("result", {}).get("payloads", [])
        if not payloads:
            logger.warning("OpenClaw returned no payloads")
            return None

        reply = payloads[0].get("text", "").strip()

        # Strip wrapping quotes if the model adds them
        if reply.startswith('"') and reply.endswith('"'):
            reply = reply[1:-1]

        if not reply:
            logger.warning("OpenClaw returned empty reply text")
            return None

        return reply

    except subprocess.TimeoutExpired:
        logger.warning(f"OpenClaw timed out after {settings.OPENCLAW_TIMEOUT}s")
        return None
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse OpenClaw JSON output: {e}")
        return None
    except FileNotFoundError:
        logger.warning("openclaw command not found — is it installed?")
        return None
    except Exception as e:
        logger.warning(f"OpenClaw reply generation failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_reply(comment_text: str) -> str:
    """
    Generate a reply for a TikTok comment.

    Tries OpenClaw agent first, falls back to keyword templates.
    """
    reply = _openclaw_reply(comment_text)
    if reply:
        logger.info(f"Generated reply via OpenClaw for: {comment_text[:50]}…")
        return reply

    logger.info("Falling back to template-based reply…")
    reply = _template_reply(comment_text)
    logger.info(f"Generated reply via templates for: {comment_text[:50]}…")
    return reply
