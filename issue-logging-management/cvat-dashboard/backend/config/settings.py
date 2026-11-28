from __future__ import annotations

import os
import warnings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent


def _load_dotenv(env_path: Path) -> None:
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv(PROJECT_ROOT / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


_DEFAULT_DEV_SECRET_KEY = "dev-insecure-cvat-dashboard-key"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", _DEFAULT_DEV_SECRET_KEY)
DEBUG = _env_bool("DJANGO_DEBUG", False)
_default_hosts = "*" if DEBUG else "localhost,127.0.0.1,testserver"
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", _default_hosts).split(",") if h.strip()]

if not DEBUG and SECRET_KEY == _DEFAULT_DEV_SECRET_KEY:
    warnings.warn(
        "DJANGO_SECRET_KEY is using the insecure default dev key with DEBUG=False.",
        RuntimeWarning,
        stacklevel=2,
    )
if not DEBUG and "*" in ALLOWED_HOSTS:
    warnings.warn(
        "DJANGO_ALLOWED_HOSTS contains '*' with DEBUG=False; configure explicit hostnames.",
        RuntimeWarning,
        stacklevel=2,
    )

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "dashboard.apps.DashboardConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

if os.getenv("DB_ENGINE", "").strip().lower() == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "cvat_dashboard"),
            "USER": os.environ.get("DB_USER", "cvat_dashboard"),
            "PASSWORD": os.environ.get("DB_PASSWORD", "cvat_dashboard"),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(BASE_DIR / "db.sqlite3"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "vi"
TIME_ZONE = "Asia/Ho_Chi_Minh"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "dashboard.auth.CVATAuthentication",
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "login": os.getenv("THROTTLE_RATE_LOGIN", "30/min"),
        "webhook": os.getenv("THROTTLE_RATE_WEBHOOK", "240/min"),
        "qc_events": os.getenv("THROTTLE_RATE_QC_EVENTS", "300/min"),
    },
}

# HTTP / Cookie Security Headers
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

SECURE_COOKIES = _env_bool("DJANGO_SECURE_COOKIES", False)
SESSION_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_SECURE = SECURE_COOKIES
SECURE_SSL_REDIRECT = _env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "31536000" if SECURE_COOKIES else "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_COOKIES
SECURE_HSTS_PRELOAD = SECURE_COOKIES

# Private CVAT connection (server-to-server only; never exposed to browser clients)
CVAT_BASE_URL = os.getenv("CVAT_BASE_URL", "").rstrip("/")
CVAT_REQUIRE_HTTPS = _env_bool("CVAT_REQUIRE_HTTPS", False)
CVAT_SERVICE_TOKEN = os.getenv("CVAT_SERVICE_TOKEN", "")
CVAT_WEBHOOK_SECRET = os.getenv("CVAT_WEBHOOK_SECRET", "")
CVAT_WEBHOOK_REQUIRE_TIMESTAMP = _env_bool("CVAT_WEBHOOK_REQUIRE_TIMESTAMP", False)
CVAT_WEBHOOK_MAX_AGE_SECONDS = int(os.getenv("CVAT_WEBHOOK_MAX_AGE_SECONDS", "300"))

# Optional ClickHouse telemetry connection
CLICKHOUSE_CONFIG = {
    "HOST": os.getenv("CLICKHOUSE_HOST", ""),
    "PORT": int(os.getenv("CLICKHOUSE_PORT", "8123")),
    "DB": os.getenv("CLICKHOUSE_DB", "cvat"),
    "USER": os.getenv("CLICKHOUSE_USER", "default"),
    "PASSWORD": os.getenv("CLICKHOUSE_PASSWORD", ""),
}

# SLA thresholds in hours for each Data Cycle step
DATA_CYCLE_SLA_HOURS = {
    "pre_qc": float(os.getenv("SLA_PRE_QC_HOURS", "4")),
    "annotator": float(os.getenv("SLA_ANNOTATOR_HOURS", "24")),
    "l1_qc": float(os.getenv("SLA_L1_QC_HOURS", "12")),
    "l2_qc": float(os.getenv("SLA_L2_QC_HOURS", "12")),
    "dept_head": float(os.getenv("SLA_DEPT_HEAD_HOURS", "12")),
}
