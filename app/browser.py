"""
Browser helper — manages a Selenium Chrome instance with the correct profile.
"""

import platform
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from loguru import logger

from app.config import settings


def _default_chrome_user_data_dir() -> str:
    """Return a safe default Chrome user-data-dir for automation."""
    project_dir = Path(__file__).resolve().parent.parent
    automation_dir = project_dir / ".chrome-user-data"
    automation_dir.mkdir(parents=True, exist_ok=True)
    return str(automation_dir)


def _system_chrome_user_data_dir() -> str:
    """Return the system Chrome user-data-dir for the current OS."""
    system = platform.system()
    home = Path.home()
    if system == "Darwin":
        return str(home / "Library" / "Application Support" / "Google" / "Chrome")
    elif system == "Linux":
        return str(home / ".config" / "google-chrome")
    elif system == "Windows":
        return str(home / "AppData" / "Local" / "Google" / "Chrome" / "User Data")
    return ""


def create_driver() -> webdriver.Chrome:
    """Create and return a configured Chrome WebDriver instance."""
    chrome_options = Options()

    # Use dedicated automation profile by default so normal Chrome profile locks don't break Selenium.
    # If you really want your system profile, set CHROME_USER_DATA_DIR explicitly in .env.
    user_data_dir = settings.CHROME_USER_DATA_DIR or _default_chrome_user_data_dir()
    if user_data_dir:
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
        chrome_options.add_argument(f"--profile-directory={settings.CHROME_PROFILE}")
        logger.info(f"Chrome profile: {settings.CHROME_PROFILE} @ {user_data_dir}")

    if settings.HEADLESS:
        chrome_options.add_argument("--headless=new")

    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--window-size=1440,900")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except WebDriverException as e:
        message = str(e).lower()
        if "user data directory is already in use" in message and settings.CHROME_USER_DATA_DIR:
            logger.warning("Configured CHROME_USER_DATA_DIR is locked. Falling back to isolated automation profile.")
            fallback_options = Options()
            fallback_dir = _default_chrome_user_data_dir()
            fallback_options.add_argument(f"--user-data-dir={fallback_dir}")
            fallback_options.add_argument(f"--profile-directory={settings.CHROME_PROFILE}")
            if settings.HEADLESS:
                fallback_options.add_argument("--headless=new")
            fallback_options.add_argument("--no-sandbox")
            fallback_options.add_argument("--disable-dev-shm-usage")
            fallback_options.add_argument("--disable-blink-features=AutomationControlled")
            fallback_options.add_argument("--window-size=1440,900")
            fallback_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            fallback_options.add_experimental_option("useAutomationExtension", False)
            driver = webdriver.Chrome(service=service, options=fallback_options)
        else:
            raise

    # Mask webdriver flag
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )

    driver.implicitly_wait(8)
    logger.info("Chrome WebDriver created successfully")
    return driver


def safe_quit(driver: webdriver.Chrome | None):
    """Quit driver safely, ignoring errors."""
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
