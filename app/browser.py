"""
Browser helper — stealth Chrome via Selenium + selenium-stealth.

Uses standard Selenium WebDriver with the selenium-stealth library
to patch navigator.webdriver, chrome.runtime, permissions, plugins,
languages, WebGL and other fingerprint vectors that TikTok checks.

When using the real system Chrome profile, the bot preserves your
existing cookies / sessions so no login is needed.  In that case we
skip user-agent overrides and extension disabling so the fingerprint
matches your normal browsing.

⚠️  You MUST close Chrome completely before running the bot — only
one process can lock a profile directory at a time.
"""

import os
import random
import subprocess
import time
import platform
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium_stealth import stealth
from fake_useragent import UserAgent
from loguru import logger

from app.config import settings


# ---------------------------------------------------------------------------
# Profile directories
# ---------------------------------------------------------------------------

def _default_chrome_user_data_dir() -> str:
    """Return an isolated automation user-data dir inside the project."""
    project_dir = Path(__file__).resolve().parent.parent
    automation_dir = project_dir / ".chrome-user-data"
    automation_dir.mkdir(parents=True, exist_ok=True)
    return str(automation_dir)


def _system_chrome_user_data_dir() -> str:
    """Return the real system Chrome user-data-dir."""
    system = platform.system()
    home = Path.home()
    if system == "Darwin":
        return str(home / "Library" / "Application Support" / "Google" / "Chrome")
    if system == "Linux":
        return str(home / ".config" / "google-chrome")
    if system == "Windows":
        return str(home / "AppData" / "Local" / "Google" / "Chrome" / "User Data")
    return ""


def _is_using_system_profile(user_data_dir: str) -> bool:
    """Check whether the given user-data-dir is the real system one."""
    sys_dir = _system_chrome_user_data_dir()
    if not sys_dir:
        return False
    return os.path.normpath(user_data_dir) == os.path.normpath(sys_dir)


def _ensure_chrome_closed():
    """
    On macOS / Linux, check whether Chrome is running.
    If it is, warn the user loudly and try to wait a moment.
    """
    system = platform.system()
    if system == "Darwin":
        result = subprocess.run(
            ["pgrep", "-x", "Google Chrome"], capture_output=True
        )
        if result.returncode == 0:
            logger.warning(
                "⚠️  Google Chrome is still running!  "
                "The bot cannot use your real profile while Chrome is open.  "
                "Please close Chrome completely and re-run the bot."
            )
            raise RuntimeError(
                "Chrome is still running. Close Chrome first, then retry."
            )
    elif system == "Linux":
        result = subprocess.run(
            ["pgrep", "-f", "chrome"], capture_output=True
        )
        if result.returncode == 0:
            logger.warning("⚠️  Chrome appears to be running — close it first.")
            raise RuntimeError(
                "Chrome is still running. Close Chrome first, then retry."
            )


# ---------------------------------------------------------------------------
# Extra stealth JS payload — injected before every page load via CDP
# ---------------------------------------------------------------------------

_STEALTH_JS = """
// ---- navigator.webdriver ----
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// ---- chrome runtime (mimics real Chrome) ----
window.chrome = window.chrome || {};
window.chrome.runtime = window.chrome.runtime || {
    PlatformOs: { MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux', OPENBSD: 'openbsd' },
    PlatformArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64', MIPS: 'mips', MIPS64: 'mips64' },
    PlatformNaclArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64', MIPS: 'mips', MIPS64: 'mips64' },
    RequestUpdateCheckStatus: { THROTTLED: 'throttled', NO_UPDATE: 'no_update', UPDATE_AVAILABLE: 'update_available' },
    OnInstalledReason: { INSTALL: 'install', UPDATE: 'update', CHROME_UPDATE: 'chrome_update', SHARED_MODULE_UPDATE: 'shared_module_update' },
    OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
};

// ---- Permissions API ----
const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : origQuery(parameters)
);

// ---- navigator.plugins (non-empty like a real browser) ----
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// ---- navigator.languages ----
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});

// ---- WebGL vendor / renderer (match real Intel GPU) ----
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function (param) {
    if (param === 37445) return 'Intel Inc.';
    if (param === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.call(this, param);
};

// ---- Prevent iframe detection of contentWindow override ----
try {
    const elementDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight');
    Object.defineProperty(HTMLDivElement.prototype, 'offsetHeight', elementDescriptor);
    Object.defineProperty(HTMLDivElement.prototype, 'offsetWidth', elementDescriptor);
} catch (e) {}

// ---- Hide automation-related properties ----
delete navigator.__proto__.webdriver;

// ---- Fake media devices (camera/mic present like a real machine) ----
if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
    const origEnumerate = navigator.mediaDevices.enumerateDevices.bind(navigator.mediaDevices);
    navigator.mediaDevices.enumerateDevices = async () => {
        const devices = await origEnumerate();
        if (devices.length === 0) {
            return [
                { deviceId: 'default', kind: 'audioinput', label: '', groupId: 'default' },
                { deviceId: 'default', kind: 'videoinput', label: '', groupId: 'default' },
            ];
        }
        return devices;
    };
}

// ---- Canvas fingerprint noise (subtle pixel randomisation) ----
const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
HTMLCanvasElement.prototype.toDataURL = function(type) {
    const ctx = this.getContext('2d');
    if (ctx) {
        const style = ctx.fillStyle;
        ctx.fillStyle = 'rgba(0,0,0,0.01)';
        ctx.fillRect(0, 0, 1, 1);
        ctx.fillStyle = style;
    }
    return origToDataURL.apply(this, arguments);
};
"""


# ---------------------------------------------------------------------------
# Driver factory
# ---------------------------------------------------------------------------

def create_driver() -> webdriver.Chrome:
    """
    Create a stealth Chrome instance using Selenium + selenium-stealth.

    When using the real system profile (CHROME_USER_DATA_DIR points to
    ~/Library/Application Support/Google/Chrome):
      • Preserves existing cookies, sessions, extensions
      • Does NOT override the user-agent (keeps real fingerprint)
      • Does NOT disable extensions
      • Applies minimal stealth (just webdriver masking)

    When using the isolated automation profile:
      • Full stealth: custom UA, disabled extensions, all JS patches
    """

    options = webdriver.ChromeOptions()

    # --- Determine profile path -------------------------------------------
    user_data_dir = settings.CHROME_USER_DATA_DIR or _default_chrome_user_data_dir()
    using_real_profile = _is_using_system_profile(user_data_dir)

    # If using the real system profile, make sure Chrome is closed first
    if using_real_profile:
        _ensure_chrome_closed()
        logger.info("🔓 Using REAL Chrome profile — existing sessions will be preserved")

    if user_data_dir:
        options.add_argument(f"--user-data-dir={user_data_dir}")
        options.add_argument(f"--profile-directory={settings.CHROME_PROFILE}")
        logger.info(f"Chrome profile: {settings.CHROME_PROFILE} @ {user_data_dir}")

    # --- Headless ----------------------------------------------------------
    if settings.HEADLESS:
        options.add_argument("--headless=new")

    # --- Window size (slight randomisation to avoid fingerprinting) --------
    w = 1440 + random.randint(-20, 20)
    h = 900 + random.randint(-20, 20)
    options.add_argument(f"--window-size={w},{h}")

    # --- Anti-detection flags ---------------------------------------------
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-notifications")
    options.add_argument("--lang=en-US,en")
    options.add_argument("--start-maximized")

    # Remove automation indicators
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # Disable "Chrome is being controlled by automated software" banner
    options.add_argument("--disable-component-update")

    # --- Profile-specific settings ----------------------------------------
    if using_real_profile:
        # Real profile: do NOT disable extensions, do NOT override user-agent
        logger.info("Keeping real Chrome extensions and user-agent intact")
    else:
        # Isolated profile: add full stealth
        options.add_argument("--disable-extensions")

        _mac_user_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        ]
        user_agent = random.choice(_mac_user_agents)
        options.add_argument(f"--user-agent={user_agent}")
        logger.info(f"User-Agent: {user_agent[:80]}…")

    # --- Create the driver ------------------------------------------------
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        err = str(e).lower()
        if "user data directory is already in use" in err:
            if using_real_profile:
                raise RuntimeError(
                    "Chrome profile is locked! Close ALL Chrome windows/processes and try again."
                )
            logger.warning("Profile locked — falling back to isolated automation profile")
            fallback_dir = _default_chrome_user_data_dir()
            options_fb = webdriver.ChromeOptions()
            options_fb.add_argument(f"--user-data-dir={fallback_dir}")
            options_fb.add_argument(f"--profile-directory={settings.CHROME_PROFILE}")
            options_fb.add_argument(f"--window-size={w},{h}")
            options_fb.add_argument("--no-sandbox")
            options_fb.add_argument("--disable-dev-shm-usage")
            options_fb.add_argument("--disable-blink-features=AutomationControlled")
            options_fb.add_argument("--disable-extensions")
            options_fb.add_experimental_option("excludeSwitches", ["enable-automation"])
            options_fb.add_experimental_option("useAutomationExtension", False)
            if settings.HEADLESS:
                options_fb.add_argument("--headless=new")
            driver = webdriver.Chrome(options=options_fb)
        else:
            raise

    # --- Apply selenium-stealth patches -----------------------------------
    stealth(
        driver,
        languages=["en-US", "en"],
        vendor="Google Inc.",
        platform="MacIntel",
        webgl_vendor="Intel Inc.",
        renderer="Intel Iris OpenGL Engine",
        fix_hairline=True,
        run_on_insecure_origins=False,
    )

    # --- Inject extra stealth JS before every navigation ------------------
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": _STEALTH_JS},
    )

    # --- Mask navigator properties via CDP (only for isolated profile) ----
    if not using_real_profile:
        driver.execute_cdp_cmd(
            "Network.setUserAgentOverride",
            {
                "userAgent": user_agent,
                "platform": "macOS",
                "acceptLanguage": "en-US,en;q=0.9",
            },
        )

    driver.implicitly_wait(8)
    mode = "REAL profile" if using_real_profile else "isolated profile"
    logger.info(f"✅ Stealth Chrome created ({mode})")
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
