"""
TikTok Comment Reply Bot — automates scanning & replying to comments
on TikTok Studio's comment management page.
"""

import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
    StaleElementReferenceException,
)
from loguru import logger

from app.config import settings
from app.browser import create_driver, safe_quit, human_delay, human_type
from app.reply_generator import generate_reply


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class CommentReply:
    username: str
    comment_text: str
    reply_text: str
    status: str = "sent"  # sent | failed


@dataclass
class JobReport:
    started_at: str = ""
    finished_at: str = ""
    total_comments: int = 0
    already_replied: int = 0
    new_replies: int = 0
    failed_replies: int = 0
    replies: list[CommentReply] = field(default_factory=list)
    message: str = ""


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

class TikTokCommentBot:
    """Manages the full lifecycle: login → scan → reply → report."""

    def __init__(self):
        self.driver: webdriver.Chrome | None = None
        self.wait: WebDriverWait | None = None
        self.report = JobReport()

    # ----- lifecycle -------------------------------------------------------

    def start(self) -> JobReport:
        """Run the full job and return a report."""
        self.report = JobReport(started_at=_now())
        try:
            self.driver = create_driver()
            self.wait = WebDriverWait(self.driver, 20)

            self._navigate_to_comments()
            self._handle_login_if_needed()
            self._wait_for_comments_page()
            self._process_all_comments()

        except Exception as e:
            logger.error(f"Bot error: {e}")
            self.report.message = f"Error: {e}"
        finally:
            safe_quit(self.driver)
            self.report.finished_at = _now()
            if not self.report.message:
                if self.report.new_replies == 0:
                    self.report.message = (
                        "All comments are up to date — no replies needed."
                    )
                else:
                    self.report.message = (
                        f"Done! Replied to {self.report.new_replies} comment(s)."
                    )
            logger.info(f"Job finished: {self.report.message}")
        return self.report

    # ----- navigation & login ----------------------------------------------

    def _navigate_to_comments(self):
        logger.info("Navigating to TikTok Studio comments page…")
        self.driver.get(settings.TIKTOK_COMMENT_URL)
        human_delay(4, 7)

    def _handle_login_if_needed(self):
        """Detect login page and authenticate via Google if needed."""
        current = self.driver.current_url
        if "login" in current.lower() or "passport" in current.lower():
            logger.info("Login page detected — attempting Google login…")
            self._google_login()
        else:
            logger.info("Already logged in (session cookie present)")

    def _google_login(self):
        """Click 'Continue with Google' and enter credentials."""
        try:
            # Look for the Google login button — TikTok uses multiple possible selectors
            google_btn = None
            for selector in [
                "//div[contains(text(), 'Continue with Google')]",
                "//span[contains(text(), 'Continue with Google')]",
                "//button[contains(text(), 'Google')]",
                "//a[contains(@href, 'google')]",
                "//*[contains(@class, 'channel-item')]//p[contains(text(), 'Google')]/..",
            ]:
                try:
                    google_btn = self.wait.until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    break
                except TimeoutException:
                    continue

            if not google_btn:
                logger.warning("Could not find 'Continue with Google' button")
                return

            google_btn.click()
            human_delay(2, 4)

            # Handle new window / popup for Google OAuth
            windows = self.driver.window_handles
            if len(windows) > 1:
                self.driver.switch_to.window(windows[-1])

            # Email
            email_input = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email']"))
            )
            email_input.clear()
            human_type(email_input, settings.TIKTOK_EMAIL)
            human_delay(0.5, 1.0)
            email_input.send_keys(Keys.ENTER)
            human_delay(2, 4)

            # Password
            pwd_input = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']"))
            )
            pwd_input.clear()
            human_type(pwd_input, settings.TIKTOK_PASSWORD)
            human_delay(0.5, 1.0)
            pwd_input.send_keys(Keys.ENTER)
            human_delay(4, 7)

            # Switch back to main window
            if len(self.driver.window_handles) > 1:
                self.driver.switch_to.window(self.driver.window_handles[0])

            # Navigate back to comments
            self.driver.get(settings.TIKTOK_COMMENT_URL)
            human_delay(4, 7)
            logger.info("Login complete")

        except Exception as e:
            logger.error(f"Google login failed: {e}")
            raise RuntimeError(f"Login failed: {e}")

    def _wait_for_comments_page(self):
        """Wait until the comments page is fully loaded."""
        logger.info("Waiting for comments page to load…")
        human_delay(4, 7)

        # Try to detect comments container via several possible selectors
        loaded = False
        for sel in [
            "div[class*='comment']",
            "div[class*='Comment']",
            "[data-e2e*='comment']",
            ".comment-list",
            "div[class*='DivCommentContainer']",
            "div[class*='studio']",
        ]:
            try:
                self.wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
                loaded = True
                logger.info(f"Comments container found via: {sel}")
                break
            except TimeoutException:
                continue

        if not loaded:
            logger.warning(
                "Could not confirm comments container — will try to proceed anyway"
            )

    # ----- comment processing ----------------------------------------------

    def _process_all_comments(self):
        """Scan all visible comments, scroll, and reply to unreplied ones."""
        scroll_attempts = 0
        max_scrolls = 10
        processed_comments: set[str] = set()

        while scroll_attempts < max_scrolls:
            comments = self._get_visible_comments()
            new_found = False

            for comment_el in comments:
                try:
                    comment_id = self._comment_fingerprint(comment_el)
                    if comment_id in processed_comments:
                        continue

                    processed_comments.add(comment_id)
                    new_found = True
                    self.report.total_comments += 1

                    username = self._extract_username(comment_el)
                    comment_text = self._extract_comment_text(comment_el)

                    if self._has_creator_reply(comment_el):
                        logger.info(f"Already replied to @{username}: {comment_text[:40]}…")
                        self.report.already_replied += 1
                        continue

                    # Generate and post reply
                    reply_text = generate_reply(comment_text)
                    success = self._post_reply(comment_el, reply_text)

                    cr = CommentReply(
                        username=username,
                        comment_text=comment_text,
                        reply_text=reply_text,
                        status="sent" if success else "failed",
                    )
                    self.report.replies.append(cr)

                    if success:
                        self.report.new_replies += 1
                        logger.info(f"✅ Replied to @{username}: {reply_text}")
                    else:
                        self.report.failed_replies += 1
                        logger.warning(f"❌ Failed to reply to @{username}")

                except (StaleElementReferenceException, NoSuchElementException) as e:
                    logger.debug(f"Stale/missing element, skipping: {e}")
                    continue

            # Scroll down to load more comments
            if not new_found:
                scroll_attempts += 1
            else:
                scroll_attempts = 0

            self._scroll_down()
            human_delay(1.5, 3.5)

        logger.info(
            f"Scan complete — total: {self.report.total_comments}, "
            f"replied: {self.report.already_replied}, "
            f"new: {self.report.new_replies}"
        )

    def _get_visible_comments(self) -> list:
        """Return all visible comment elements on the page."""
        selectors = [
            "div[class*='DivCommentItem']",
            "div[class*='comment-item']",
            "[data-e2e='comment-item']",
            "div[class*='CommentItem']",
            ".comment-item",
            "div[class*='comment-content']",
        ]
        for sel in selectors:
            elements = self.driver.find_elements(By.CSS_SELECTOR, sel)
            if elements:
                return elements
        # Broad fallback — look for anything that looks like a comment row
        return self.driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'comment') or contains(@class,'Comment')]"
        )

    @staticmethod
    def _comment_fingerprint(el) -> str:
        """Create a unique-ish fingerprint for a comment element."""
        try:
            return el.get_attribute("outerHTML")[:300]
        except Exception:
            return str(id(el))

    @staticmethod
    def _extract_username(comment_el) -> str:
        """Pull the commenter's username from the element."""
        for sel in [
            "span[class*='user-name']",
            "span[class*='UserName']",
            "a[class*='user-name']",
            "[data-e2e='comment-username']",
            "a[class*='StyledLink']",
            "span[class*='SpanUserName']",
            "a[href*='/@']",
        ]:
            try:
                el = comment_el.find_element(By.CSS_SELECTOR, sel)
                text = el.text.strip()
                if text:
                    return text
            except NoSuchElementException:
                continue
        return "unknown"

    @staticmethod
    def _extract_comment_text(comment_el) -> str:
        """Pull the comment text from the element."""
        for sel in [
            "span[class*='comment-text']",
            "span[class*='SpanComment']",
            "p[class*='comment-text']",
            "[data-e2e='comment-text']",
            "span[class*='CommentText']",
            "div[class*='comment-content'] span",
        ]:
            try:
                el = comment_el.find_element(By.CSS_SELECTOR, sel)
                text = el.text.strip()
                if text:
                    return text
            except NoSuchElementException:
                continue
        # Fallback — use the whole text and try to isolate the comment
        return comment_el.text.strip()[:200]

    def _has_creator_reply(self, comment_el) -> bool:
        """
        Check if the creator (corpusiq) has already replied to this comment.
        Looks for a Creator badge or the creator's handle in reply sub-elements.
        """
        try:
            # Check for "Creator" badge in replies
            replies_html = comment_el.get_attribute("innerHTML") or ""
            lower = replies_html.lower()

            if "creator" in lower and (
                settings.CREATOR_HANDLE.lower() in lower
                or "badge" in lower
            ):
                return True

            # Also check for reply sub-elements with the creator's name
            sub_replies = comment_el.find_elements(
                By.XPATH,
                ".//div[contains(@class,'reply') or contains(@class,'Reply')]"
            )
            for sr in sub_replies:
                sr_text = sr.text.lower()
                if settings.CREATOR_HANDLE.lower() in sr_text or "creator" in sr_text:
                    return True

        except Exception:
            pass
        return False

    def _post_reply(self, comment_el, reply_text: str) -> bool:
        """Click Reply, type the text, and send."""
        try:
            # 1) Click the Reply link/button
            reply_btn = None
            for sel in [
                ".//span[contains(text(),'Reply')]",
                ".//button[contains(text(),'Reply')]",
                ".//div[contains(text(),'Reply')]",
                ".//span[contains(@class,'reply')]",
                ".//a[contains(text(),'Reply')]",
            ]:
                try:
                    reply_btn = comment_el.find_element(By.XPATH, sel)
                    break
                except NoSuchElementException:
                    continue

            if not reply_btn:
                logger.warning("Reply button not found")
                return False

            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", reply_btn)
            human_delay(0.5, 1.2)
            reply_btn.click()
            human_delay(1.0, 2.5)

            # 2) Type into the reply input
            reply_input = None
            for sel in [
                "div[contenteditable='true']",
                "textarea[class*='reply']",
                "input[class*='reply']",
                "[data-e2e='comment-input']",
                "div[class*='DivInputEditor'] [contenteditable='true']",
                "div[role='textbox']",
            ]:
                try:
                    reply_input = self.wait.until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                    )
                    break
                except TimeoutException:
                    continue

            if not reply_input:
                logger.warning("Reply input not found")
                return False

            reply_input.click()
            human_delay(0.3, 0.8)
            human_type(reply_input, reply_text)
            human_delay(0.8, 1.5)

            # 3) Click the send button
            send_btn = None
            for sel in [
                "div[class*='send'] svg",
                "button[class*='send']",
                "[data-e2e='comment-post']",
                "div[class*='DivPostButton']",
                "//button[contains(@class,'Post')]",
                "//div[contains(@class,'submit')]",
                "//span[contains(text(),'Post')]/..",
            ]:
                try:
                    if sel.startswith("//"):
                        send_btn = self.driver.find_element(By.XPATH, sel)
                    else:
                        send_btn = self.driver.find_element(By.CSS_SELECTOR, sel)
                    break
                except NoSuchElementException:
                    continue

            if send_btn:
                send_btn.click()
            else:
                # Fallback: press Enter
                reply_input.send_keys(Keys.ENTER)

            human_delay(2, 4)
            logger.info("Reply sent successfully")
            return True

        except (ElementClickInterceptedException, TimeoutException) as e:
            logger.warning(f"Could not post reply: {e}")
            return False

    def _scroll_down(self):
        """Scroll the page with a random offset to mimic a human."""
        scroll_px = random.randint(400, 800)
        self.driver.execute_script(f"window.scrollBy(0, {scroll_px});")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_reply_job() -> dict:
    """Convenience function: run the bot and return the report as a dict."""
    bot = TikTokCommentBot()
    report = bot.start()
    return {
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "total_comments": report.total_comments,
        "already_replied": report.already_replied,
        "new_replies": report.new_replies,
        "failed_replies": report.failed_replies,
        "message": report.message,
        "replies": [
            {
                "username": r.username,
                "comment_text": r.comment_text,
                "reply_text": r.reply_text,
                "status": r.status,
            }
            for r in report.replies
        ],
    }
