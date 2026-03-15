"""
Browser helper — simple Chrome launcher.

Logic:
  1. Try to open Chrome with your REAL profile (cookies/sessions intact).
  2. If Chrome is already open (profile locked), attach to it via remote debugging.
  3. If that also fails, fall back to a clean default profile.

No crashes, no errors — it just works.
"""

import os
import random
import subprocess
import time
import platform
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from loguru import logger

from app.config import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _system_chrome_user_data_dir() -> str:
    """Return the real system Chrome user-data-dir for this OS."""
    system = platform.system()
    home = Path.home()
    if system == "Darwin":
        return str(home / "Library" / "Application Support" / "Google" / "Chrome")
    if system == "Linux":
        return str(home / ".config" / "google-chrome")
    if system == "Windows":
        return str(home / "AppData" / "Local" / "Google" / "Chrome" / "User Data")
    return ""


def _default_chrome_user_data_dir() -> str:
    """Return an isolated automation user-data dir inside the project."""
    d = Path(__file__).resolve().parent.parent / ".chrome-user-data"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def _is_using_system_profile(user_data_dir: str) -> bool:
    sys_dir = _system_chrome_user_data_dir()
    if not sys_dir:
        return False
    return os.path.normpath(user_data_dir) == os.path.normpath(sys_dir)


def _is_chrome_running() -> bool:
    """Check if Google Chrome is currently running."""
    system = platform.system()
    try:
        if system == "Darwin":
            r = subprocess.run(["pgrep", "-x", "Google Chrome"],
                               capture_output=True)
            return r.returncode == 0
        elif system == "Linux":
            r = subprocess.run(["pgrep", "-f", "chrome"], capture_output=True)
            return r.returncode == 0
        elif system == "Windows":
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
                               capture_output=True, text=True)
            return "chrome.exe" in r.stdout.lower()
    except Exception:
        pass
    return False


def _remove_lock_files(user_data_dir: str):
    """Remove Chrome singleton lock files so Selenium can open the profile."""
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        p = Path(user_data_dir) / name
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass


def _base_options() -> Options:
    """Return ChromeOptions with basic anti-detection flags."""
    opts = webdriver.ChromeOptions()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-component-update")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--lang=en-US,en")
    w = 1440 + random.randint(-20, 20)
    h = 900 + random.randint(-20, 20)
    opts.add_argument(f"--window-size={w},{h}")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    if settings.HEADLESS:
        opts.add_argument("--headless=new")
    return opts


# ---------------------------------------------------------------------------
# Driver factory  —  simple 3-step fallback
# ---------------------------------------------------------------------------

def create_driver() -> webdriver.Chrome:
    """
    Open Chrome with the simplest approach that works:

    1. Chrome is CLOSED  → open your real profile directly (best: has cookies)
    2. Chrome is OPEN    → copy cookies from real profile via a fresh instance
    3. Everything fails  → open a clean default profile (will need login)
    """

    user_data_dir = settings.CHROME_USER_DATA_DIR or _system_chrome_user_data_dir()
    profile = settings.CHROME_PROFILE or "Default"
    chrome_open = _is_chrome_running()

    # ── Step 1: Chrome is closed → use real profile directly ──────────
    if not chrome_open:
        logger.info(f"Chrome is closed → opening real profile '{profile}'")
        try:
            _remove_lock_files(user_data_dir)
            opts = _base_options()
            opts.add_argument(f"--user-data-dir={user_data_dir}")
            opts.add_argument(f"--profile-directory={profile}")
            opts.add_argument("--remote-debugging-port=9222")
            driver = webdriver.Chrome(options=opts)
            driver.implicitly_wait(8)
            logger.info("✅ Chrome opened with real profile (sessions intact)")
            return driver
        except Exception as e:
            logger.warning(f"Real profile failed: {e}")

    # ── Step 2: Chrome is open → use a temp copy of the profile ───────
    if chrome_open:
        logger.info("Chrome is already open → using a temporary profile copy")
        try:
            # Copy cookies/login data from the real profile into an
            # isolated dir so we don't fight the profile lock.
            import shutil
            tmp_dir = Path(__file__).resolve().parent.parent / ".chrome-temp-profile"
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            tmp_dir.mkdir(parents=True, exist_ok=True)

            src_profile = Path(user_data_dir) / profile
            dst_profile = tmp_dir / profile
            dst_profile.mkdir(parents=True, exist_ok=True)

            # Copy only the essential session/cookie files (fast, <1s)
            for fname in (
                "Cookies", "Cookies-journal",
                "Login Data", "Login Data-journal",
                "Web Data", "Web Data-journal",
                "Preferences", "Secure Preferences",
                "Local State",
            ):
                src = src_profile / fname
                if src.exists():
                    shutil.copy2(src, dst_profile / fname)
            # Also copy Local State from the root user-data-dir
            ls = Path(user_data_dir) / "Local State"
            if ls.exists():
                shutil.copy2(ls, tmp_dir / "Local State")

            opts = _base_options()
            opts.add_argument(f"--user-data-dir={str(tmp_dir)}")
            opts.add_argument(f"--profile-directory={profile}")
            opts.add_argument("--remote-debugging-port=9223")
            driver = webdriver.Chrome(options=opts)
            driver.implicitly_wait(8)
            logger.info("✅ Chrome opened with copied profile (sessions should work)")
            return driver
        except Exception as e:
            logger.warning(f"Temp profile copy failed: {e}")

    # ── Step 3: Fallback → clean isolated profile ─────────────────────
    logger.info("Falling back to clean default profile (may need login)")
    fallback_dir = _default_chrome_user_data_dir()
    opts = _base_options()
    opts.add_argument(f"--user-data-dir={fallback_dir}")
    opts.add_argument(f"--profile-directory=Default")
    opts.add_argument("--remote-debugging-port=9224")
    driver = webdriver.Chrome(options=opts)
    driver.implicitly_wait(8)
    logger.info("✅ Chrome opened with clean profile")
    return driver


# ---------------------------------------------------------------------------
# Human-like helpers (importable by tiktok_bot.py)
# ---------------------------------------------------------------------------

def human_delay(low: float = 0.5, high: float = 2.0):
    """Sleep a random duration to mimic human pauses."""
    time.sleep(random.uniform(low, high))


def human_type(element, text: str, low: float = 0.04, high: float = 0.15):
    """Type text character-by-character with random delays."""
    for ch in text:
        element.send_keys(ch)
        time.sleep(random.uniform(low, high))


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def safe_quit(driver: webdriver.Chrome | None):
    """Quit driver safely, ignoring errors."""
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
