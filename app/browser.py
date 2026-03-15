"""
Browser helper — stealth Chrome via Selenium + selenium-stealth.

Uses standard Selenium WebDriver with the selenium-stealth library
to patch navigator.webdriver, chrome.runtime, permissions, plugins,
languages, WebGL and other fingerprint vectors that TikTok checks.

Also injects additional stealth JS via CDP for belt-and-suspenders
coverage.
"""

import random
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

    Key anti-detection measures:
    • selenium-stealth patches navigator.webdriver, chrome.runtime, etc.
    • Extra CDP JS injection for permissions, plugins, WebGL, canvas
    • Real user-agent string via fake-useragent
    • Realistic window size with slight randomisation
    • Disable automation-related Chrome switches
    • excludeSwitches: enable-automation removed
    • useAutomationExtension: false
    """

    options = webdriver.ChromeOptions()

    # --- Profile -----------------------------------------------------------
    user_data_dir = settings.CHROME_USER_DATA_DIR or _default_chrome_user_data_dir()
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
    options.add_argument("--disable-extensions")
    options.add_argument("--start-maximized")

    # Remove automation indicators
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # Disable "Chrome is being controlled by automated software" banner
    options.add_argument("--disable-component-update")

    # Real user-agent — must be macOS Chrome to match platform="MacIntel"
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
        if "user data directory is already in use" in err and settings.CHROME_USER_DATA_DIR:
            logger.warning("System profile locked — falling back to isolated automation profile")
            fallback_dir = _default_chrome_user_data_dir()
            options_fb = webdriver.ChromeOptions()
            options_fb.add_argument(f"--user-data-dir={fallback_dir}")
            options_fb.add_argument(f"--profile-directory={settings.CHROME_PROFILE}")
            options_fb.add_argument(f"--window-size={w},{h}")
            options_fb.add_argument("--no-sandbox")
            options_fb.add_argument("--disable-dev-shm-usage")
            options_fb.add_argument("--disable-blink-features=AutomationControlled")
            options_fb.add_argument(f"--user-agent={user_agent}")
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

    # --- Mask navigator properties via CDP --------------------------------
    driver.execute_cdp_cmd(
        "Network.setUserAgentOverride",
        {
            "userAgent": user_agent,
            "platform": "macOS",
            "acceptLanguage": "en-US,en;q=0.9",
        },
    )

    driver.implicitly_wait(8)
    logger.info("✅ Stealth Chrome created (selenium-stealth)")
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
