"""Django settings for the EFFECOM backend."""

import os
import warnings
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be configured when DEBUG is disabled."
        )
    SECRET_KEY = "local-development-only-change-me"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,effecom-backend.onrender.com",
    ).split(",")
    if host.strip()
]
render_external_hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if render_external_hostname and render_external_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_external_hostname)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "account",
    "tts", 
    "stt",
    "profiles",
    "settings",
    "captions",
    "translation",
    "whitenoise"
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "effecom.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "effecom.wsgi.application"

database_url = os.environ.get("DATABASE_URL")
DATABASES = {
    "default": (
        dj_database_url.parse(database_url)
        if database_url
        else {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    )
}

AUTH_USER_MODEL = "account.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SUNBIRD_ACCESS_TOKEN = os.environ.get("SUNBIRD_ACCESS_TOKEN", "")
SUNBIRD_USERNAME = os.environ.get("SUNBIRD_USERNAME", "")
SUNBIRD_PASSWORD = os.environ.get("SUNBIRD_PASSWORD", "")
SUNBIRD_AUTH_SCHEME = os.environ.get("SUNBIRD_AUTH_SCHEME", "Bearer")
SUNBIRD_BASE_URL = os.environ.get(
    "SUNBIRD_BASE_URL", "https://api.sunbird.ai"
).rstrip("/")
SUNBIRD_CONNECT_TIMEOUT_SECONDS = int(
    os.environ.get("SUNBIRD_CONNECT_TIMEOUT_SECONDS", "10")
)
SUNBIRD_AUTH_TIMEOUT_SECONDS = int(
    os.environ.get("SUNBIRD_AUTH_TIMEOUT_SECONDS", "30")
)
SUNBIRD_TTS_TIMEOUT_SECONDS = int(
    os.environ.get("SUNBIRD_TTS_TIMEOUT_SECONDS", "120")
)
SUNBIRD_STT_TIMEOUT_SECONDS = int(
    os.environ.get("SUNBIRD_STT_TIMEOUT_SECONDS", "180")
)
SUNBIRD_MAX_AUDIO_SIZE_BYTES = int(
    os.environ.get("SUNBIRD_MAX_AUDIO_SIZE_BYTES", str(25 * 1024 * 1024))
)
SUNBIRD_MAX_AUDIO_SECONDS = int(
    os.environ.get("SUNBIRD_MAX_AUDIO_SECONDS", "300")
)
SUNBIRD_MAX_TEXT_LENGTH = int(os.environ.get("SUNBIRD_MAX_TEXT_LENGTH", "2000"))
SUNBIRD_MAX_TRANSLATE_CHARS = int(
    os.environ.get("SUNBIRD_MAX_TRANSLATE_CHARS", "5000")
)
SUNBIRD_TRANSLATION_TIMEOUT_SECONDS = int(
    os.environ.get("SUNBIRD_TRANSLATION_TIMEOUT_SECONDS", "120")
)
GUEST_SESSION_LIFETIME_SECONDS = int(
    os.environ.get("GUEST_SESSION_LIFETIME_SECONDS", str(24 * 60 * 60))
)
GUEST_SESSIONS_PER_IP_PER_DAY = int(
    os.environ.get("GUEST_SESSIONS_PER_IP_PER_DAY", "10")
)
GUEST_LIMITS = {
    "translations": int(os.environ.get("GUEST_TRANSLATION_LIMIT", "10")),
    "translate_chars": int(os.environ.get("GUEST_TRANSLATION_CHAR_LIMIT", "500")),
    "transcriptions": int(os.environ.get("GUEST_TRANSCRIPTION_LIMIT", "3")),
    "audio_seconds": int(os.environ.get("GUEST_AUDIO_SECONDS_LIMIT", "30")),
}
AUTHENTICATED_LIMITS = {
    "translations_per_day": int(
        os.environ.get("AUTH_TRANSLATIONS_PER_DAY", "200")
    ),
    "translate_chars": int(
        os.environ.get("AUTH_TRANSLATION_CHAR_LIMIT", "5000")
    ),
}
GUEST_COOKIE_SECURE = os.environ.get(
    "GUEST_COOKIE_SECURE", str(not DEBUG)
).lower() == "true"
SESSION_COOKIE_SECURE = os.environ.get(
    "SESSION_COOKIE_SECURE", str(not DEBUG)
).lower() == "true"
SESSION_COOKIE_SAMESITE = os.environ.get(
    "SESSION_COOKIE_SAMESITE", "Lax" if DEBUG else "None"
).capitalize()
if SESSION_COOKIE_SAMESITE not in {"Lax", "Strict", "None"}:
    raise ImproperlyConfigured(
        "SESSION_COOKIE_SAMESITE must be Lax, Strict, or None."
    )
if SESSION_COOKIE_SAMESITE == "None" and not SESSION_COOKIE_SECURE:
    raise ImproperlyConfigured(
        "SESSION_COOKIE_SECURE must be true when SESSION_COOKIE_SAMESITE is None."
    )
CSRF_COOKIE_SECURE = os.environ.get(
    "CSRF_COOKIE_SECURE", str(not DEBUG)
).lower() == "true"
CSRF_COOKIE_SAMESITE = os.environ.get(
    "CSRF_COOKIE_SAMESITE", "Lax" if DEBUG else "None"
).capitalize()
if CSRF_COOKIE_SAMESITE not in {"Lax", "Strict", "None"}:
    raise ImproperlyConfigured(
        "CSRF_COOKIE_SAMESITE must be Lax, Strict, or None."
    )
if CSRF_COOKIE_SAMESITE == "None" and not CSRF_COOKIE_SECURE:
    raise ImproperlyConfigured(
        "CSRF_COOKIE_SECURE must be true when CSRF_COOKIE_SAMESITE is None."
    )
GUEST_COOKIE_SAMESITE = os.environ.get(
    "GUEST_COOKIE_SAMESITE", "Lax" if DEBUG else "None"
).capitalize()
if GUEST_COOKIE_SAMESITE not in {"Lax", "Strict", "None"}:
    raise ImproperlyConfigured(
        "GUEST_COOKIE_SAMESITE must be Lax, Strict, or None."
    )
if GUEST_COOKIE_SAMESITE == "None" and not GUEST_COOKIE_SECURE:
    raise ImproperlyConfigured(
        "GUEST_COOKIE_SECURE must be true when GUEST_COOKIE_SAMESITE is None."
    )
SUNBIRD_TRANSLATION_SUPPORTED_LANGUAGES = frozenset(
    "ach adh afr aka alz amh bam bem ber bfa cgg dag dga din eng ewe ful gwr "
    "hau "
    "ibo ikx kab kau kdi kdj keo kik kin kln koo kpz laj led lgg lin lsm luc "
    "lug luo luy mhi mlg myx nbl nya nuj nyn nyo orm pcm pok rub ruc run rwm "
    "sna som sot swa teo tlj tsn ttj wol xho xog yor zul".split()
)
configured_translation_languages = {
    language.strip().lower()
    for language in os.environ.get(
        "SUNBIRD_TRANSLATION_LANGUAGES",
        "ach,afr,aka,alz,amh,luc,teo,bam,bfa,bem,ber,nya,dga,dag,din,eng,ewe,"
        "ful,hau,ibo,ikx,adh,kab,keo,kln,kau,kdj,kik,kin,run,kdi,kpz,rwm,laj,"
        "led,lin,tlj,lgg,rub,gwr,lug,luy,myx,nuj,luo,xog,mhi,mlg,nbl,pcm,orm,"
        "pok,cgg,koo,nyn,nyo,ruc,ttj,lsm,sot,tsn,sna,som,swa,wol,xho,yor,zul",
    ).split(",")
    if language.strip()
}
unsupported_translation_languages = (
    configured_translation_languages - SUNBIRD_TRANSLATION_SUPPORTED_LANGUAGES
)
if unsupported_translation_languages:
    warnings.warn(
        "Ignoring language codes unsupported by Sunbird translation: "
        + ", ".join(sorted(unsupported_translation_languages)),
        RuntimeWarning,
        stacklevel=2,
    )
SUNBIRD_TRANSLATION_LANGUAGES = tuple(
    language.strip().lower()
    for language in os.environ.get(
        "SUNBIRD_TRANSLATION_LANGUAGES",
        "ach,afr,aka,alz,amh,luc,teo,bam,bfa,bem,ber,nya,dga,dag,din,eng,ewe,ful,hau,ibo,ikx,adh,kab,keo,kln,kau,kdj,kik,kin,run,kdi,kpz,rwm,laj,led,lin,tlj,lgg,rub,gwr,lug,luy,myx,nuj,luo,xog,mhi,mlg,nbl,pcm,orm,pok,cgg,koo,nyn,nyo,ruc,ttj,lsm,sot,tsn,sna,som,swa,wol,xho,yor,zul",
    ).replace(" ", "").split(",")
    if language.strip()
    and language.strip().lower() in SUNBIRD_TRANSLATION_SUPPORTED_LANGUAGES
)
SUNBIRD_TTS_VOICES = tuple(
    (language.strip().lower(), voice.strip())
    for pair in os.environ.get("SUNBIRD_TTS_VOICES", "lug:Namuli").split(",")
    if ":" in pair
    for language, voice in [pair.split(":", 1)]
    if language.strip() and voice.strip()
)
SUNBIRD_STT_LANGUAGES = tuple(
    dict.fromkeys(
        language.strip().lower()
        for language in os.environ.get("SUNBIRD_STT_LANGUAGES", "lug").split(",")
        if len(language.strip()) == 3 and language.strip().isalpha()
    )
)


# CORS and CSRF settings
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,https://effecom.vercel.app",
    ).split(",")
    if origin.strip()
]
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS
CSRF_TRUSTED_ORIGINS.append("https://effecom-backend.onrender.com")
if render_external_hostname:
    CSRF_TRUSTED_ORIGINS.append(f"https://{render_external_hostname}")

# Django REST Framework configuration
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "translation.authentication.GuestAuthentication",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.environ.get("DRF_ANON_RATE", "20/hour"),
        "guest-burst": os.environ.get("GUEST_BURST_RATE", "10/minute"),
    },
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
}

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}
# Email backend configuration for production
if not DEBUG:
    MAILERS["default"] = {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "HOST": os.environ.get("EMAIL_HOST", ""),
        "PORT": int(os.environ.get("EMAIL_PORT", 587)),
        "USERNAME": os.environ.get("EMAIL_HOST_USER", ""),
        "PASSWORD": os.environ.get("EMAIL_HOST_PASSWORD", ""),
        "USE_TLS": os.environ.get("EMAIL_USE_TLS", "true").lower() == "true",
        "USE_SSL": os.environ.get("EMAIL_USE_SSL", "false").lower() == "true",
    }
    
# Media files (uploads)
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Static files (CSS, JavaScript, Images)
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Static files storage configuration
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}