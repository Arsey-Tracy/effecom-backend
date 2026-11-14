# EFFECOM backend: DRF, Sunbird speech, and translation

This backend iteration uses Django REST Framework for guest-accessible text
translation, speech-to-text (STT), and text-to-speech (TTS), plus
JWT-cookie-authenticated accounts and private per-user activity history. It also
provides authenticated video captioning: upload a video, extract its audio with
PyAV, transcribe it locally with Faster-Whisper, and edit or export SRT/VTT
captions.

## Setup

Use Python 3.13 or another Python version supported by the installed Django
release. From this directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Use `.env.example` as a reference for the required settings. Set environment
variables in the process running Django, or create a local `.env` beside
`manage.py` using `.env.example` as a template. The `.env` file is gitignored.
Generate a `DJANGO_SECRET_KEY` for each environment and provide
`SUNBIRD_USERNAME` and `SUNBIRD_PASSWORD` for a dedicated Sunbird service
account through a secret manager or local `.env`. Never commit credentials.

SQLite is used when `DATABASE_URL` is unset. Set `DATABASE_URL` to a
PostgreSQL connection URL to use PostgreSQL. Before running in production, set
`DJANGO_DEBUG=false`, a non-empty `DJANGO_SECRET_KEY`, the deployment's
`DJANGO_ALLOWED_HOSTS`, and the frontend's `CORS_ALLOWED_ORIGINS`. The
browser calls the same-origin Next.js API proxy, which forwards API requests
and authentication cookies to Django. Set `EFFECOM_BACKEND_URL` in the
frontend environment when the backend runs somewhere other than the proxy's
default (`http://localhost:8000` in development).

Run initial migrations and start Django:

```powershell
python manage.py migrate
python manage.py seed_languages
python manage.py runserver
```

## Render deployment

Create a Render Web Service with this directory (`effecom`) as its **Root
Directory**. Set the **Build Command** to `bash build.sh` and the **Start
Command** to `gunicorn --timeout 240 effecom.wsgi:application`. The build
script installs the pinned requirements, collects static files, applies
database migrations, and seeds the configured translation languages. Keep a persistent PostgreSQL
database attached through `DATABASE_URL`; the local SQLite database is not a
production persistence option on Render.

Configure at least `DJANGO_DEBUG=false`, a unique secret `DJANGO_SECRET_KEY`,
`DJANGO_ALLOWED_HOSTS` with the service hostname, `CORS_ALLOWED_ORIGINS` with
the frontend origin (`https://effecom.vercel.app`), and Sunbird credentials in
Render's environment settings.
Do not set `JWT_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, or `GUEST_COOKIE_SECURE`
to `false` in production; HTTPS is required for cross-site cookies.
`JWT_COOKIE_SAMESITE`, `CSRF_COOKIE_SAMESITE`, and `GUEST_COOKIE_SAMESITE`
default to `None` in production and `Lax` in local development. If overriding
these settings, `None` requires the matching `*_SECURE` setting to remain true. Set
`CORS_ALLOWED_ORIGINS` to the exact frontend origin; it also configures trusted
CSRF origins. Run the deployment with the same environment variables on both
build and runtime phases so static collection and migrations use the intended
settings and database.

## Video captions in production

Video captioning needs no external FFmpeg/FFprobe binaries: media probing and
audio extraction use PyAV (the `av` package), which ships its own FFmpeg
libraries. Audio is transcribed locally with Faster-Whisper; there is no
third-party transcription API and no credential to configure.

Set `CAPTION_EXECUTION_MODE` to control how work runs:

- `inline` (recommended for a single Render web service): the process endpoint
  starts a daemon thread in the web process, returns `202`, and the frontend
  polls the video resource for progress. No Redis or separate worker is
  required.
- `auto` (default): use Celery when `CELERY_BROKER_URL` is reachable, otherwise
  fall back to inline processing.
- `celery`: require a reachable broker and a separately running worker
  (`celery -A effecom worker -l info`). Use this when transcription must be
  isolated from request-serving capacity.

Required Render environment variables for captions:

- `CAPTION_EXECUTION_MODE` — `inline`, `auto`, or `celery`.
- `CELERY_BROKER_URL` — only when using `celery`, or when a worker is deployed.
- `WHISPER_MODEL_SIZE`, `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE`,
  `WHISPER_LANGUAGE` — optional model settings. The default `base`/`cpu`/`int8`
  model downloads on first use; keep the service's disk and memory sufficient
  for the chosen model.
- `CAPTION_MAX_UPLOAD_MB`, `CAPTION_MAX_DURATION_MIN`,
  `CAPTION_ALLOWED_VIDEO_EXTENSIONS` — optional limits.

Inline processing runs on the web service, so a long or large video consumes
that service's CPU and memory. For heavier workloads, deploy a separate worker
with `CAPTION_EXECUTION_MODE=celery`, set `CELERY_BROKER_URL` to a managed Redis
or Render Key Value instance, and run `celery -A effecom worker`. The worker must
have the same `DATABASE_URL` and `WHISPER_*` settings as the web service.

Jobs that stop unexpectedly (process restart, lost worker) are marked failed by
`python manage.py recover_stale_caption_jobs` once their heartbeat exceeds
`CAPTION_STALE_JOB_MINUTES`. Run it periodically (for example from an external
cron or Render cron job). Failed videos can be retried from
`POST /api/v1/videos/{id}/process/`; the status claim and `get_or_create` on the
caption track make retries idempotent.

Uploaded videos are stored on the local filesystem (`MEDIA_ROOT`). Render's
default disk is ephemeral, so attach a persistent disk mounted at `MEDIA_ROOT`
or move `STORAGES["default"]` to object storage if videos must survive restarts
and be served by more than one web instance. PostgreSQL remains the source of
truth for video and caption records; the caption fix never deletes either.

Provider and configuration failures (missing Faster-Whisper/PyAV modules, model
load errors, invalid video files, transcription errors) mark the video `failed`
with a safe `error_message`; they are never reported as successful captions.
Provider exception details are logged by type only, never with credentials or
media contents.

With `SUNBIRD_USERNAME` and `SUNBIRD_PASSWORD` configured, the backend
requests a form-encoded token from Sunbird's `/auth/token` endpoint on first
use and caches it in the current Django process. It does not regenerate
tokens on a timer or call `/auth/refresh-token` (that endpoint revokes the
previous token). If a feature request receives `401`, the backend logs in
once and retries that request once. If valid login credentials are not
configured, `SUNBIRD_ACCESS_TOKEN` is supported as a static-token fallback.

Run `python manage.py check_sunbird` to verify the credentials against
Sunbird's `/auth/me` endpoint; the command never prints the token or account
profile. Sunbird credentials should be for a dedicated service account and
must remain server-side.

## API

Translation and TTS endpoints accept JSON `POST` requests, while STT accepts a
multipart upload. All are available to guest users and
are rate-limited by DRF's anonymous-user throttle. They validate input before
making server-to-server requests to Sunbird. The Sunbird token is never sent
to the browser.

### Translation

`POST /api/v1/translate/`

```json
{
  "text": "Nze ndi mukwano gwa Tracy",
  "target_language": "eng"
}
```

`target_language` is required. `source_language` is optional: omit it to let
Sunbird detect the language, or provide a supported code such as `lug`.
Sunbird supports translation directly between any supported language pair;
the source and target cannot be the same. The response includes the translated
text at `output.translated_text`.

`POST /api/v1/language-detection/` accepts `{"text":"..."}` and returns
Sunbird's language-identification result. It uses the same text-size limit and
guest burst throttle as the other translation APIs.

The versioned resource endpoints are also available:

- `GET /api/v1/languages/?capability=translation` lists active translation
  languages. `capability=stt` lists languages enabled by
  `SUNBIRD_STT_LANGUAGES`.
- `POST /api/v1/guest/session/` creates a signed guest session and sets an
  HttpOnly `guest_token` cookie. Non-browser clients can send the signed token
  in the `X-Guest-Token` header.
- `GET /api/v1/guest/usage/` returns the guest session's current usage and
  configured limits.
- `POST /api/v1/translations/` creates a persisted translation record. A guest
  must create a session first; signed-in users are supported as well.
- `GET /api/v1/translations/` lists only the signed-in user's history.
- `GET /api/v1/translations/{id}/` returns a record only to its owner.

Guest translation requests default to 10 translations and 500 characters per
translation per 24-hour session. Authenticated requests default to 200
translations per rolling 24-hour period and 5,000 characters per translation.
These limits and the guest session-creation cap are configurable using the
`GUEST_*` and `AUTH_*` environment variables in `.env.example`. The guest IP
and user-agent are stored only as keyed hashes.
Guest burst throttling is per session (or per IP before a session exists);
the anonymous API throttle also limits requests by IP.

Run `python manage.py seed_languages` after migrations and whenever the
configured language lists change. It seeds the checked-in language fixture
and updates translation, STT, and TTS capability flags from configuration.

Versioned resource endpoints use errors shaped as
`{"error":{"code":"...","message":"...","details":{}}}`. Translation text is
sent to Sunbird for processing; do not submit confidential or sensitive text.

The browser offers automatic source-language detection and only the language
codes supported by Sunbird translation. The configured translation read
timeout defaults to 120 seconds (`SUNBIRD_TRANSLATION_TIMEOUT_SECONDS`) to
allow for model inference; the connection timeout defaults to 10 seconds. Use
complete, reasonably short sentences for better quality.

### Text-to-speech

`POST /api/v1/tts/`

```json
{
  "text": "Nze ndi mukwano gwa Tracy",
  "language": "lug",
  "voice": "Namuli"
}
```

The backend adds `"response_mode": "url"` and forwards the request to
Sunbird's `/tasks/audio/speech` endpoint. The JSON response is passed through
for playback by the frontend, which renders an audio player when the provider
returns an audio URL.

### Speech-to-text

`POST /api/v1/stt/` accepts a `multipart/form-data` upload with fields
`audio` (WAV) and `language` (a configured three-letter
language code, Luganda by default). The backend sends the audio and language to
Sunbird's `/tasks/audio/transcriptions` endpoint and returns its
`audio_transcription` result. A guest session must be created first; signed-in
requests are added to the user's activity history.

Guest requests are limited by both the configured transcription count and
audio duration. Audio duration is read from the uploaded file and rounded up
to whole seconds. The defaults are 3 transcriptions and 30 total audio seconds
per guest session. Uploads are limited to 25 MiB and 300 seconds by default.
Configure supported languages with `SUNBIRD_STT_LANGUAGES`, maximum upload
size/duration with `SUNBIRD_MAX_AUDIO_SIZE_BYTES` and
`SUNBIRD_MAX_AUDIO_SECONDS`, and the provider response timeout with
`SUNBIRD_STT_TIMEOUT_SECONDS`.

### Validation and provider configuration

- `SUNBIRD_MAX_TEXT_LENGTH` caps text input (default `2000` characters).
- `SUNBIRD_CONNECT_TIMEOUT_SECONDS` configures the connection timeout for
  Sunbird requests (default `10` seconds).
- `SUNBIRD_AUTH_TIMEOUT_SECONDS` configures the response timeout for token
  login and authentication checks (default `30` seconds).
- `SUNBIRD_TTS_TIMEOUT_SECONDS` configures the TTS response timeout (default
  `120` seconds).
- `SUNBIRD_STT_TIMEOUT_SECONDS` configures the STT response timeout (default
  `180` seconds).
- `SUNBIRD_TRANSLATION_TIMEOUT_SECONDS` configures the translation read
  timeout (default `120` seconds).
- Set the production application-server and any proxy timeouts longer than
  the expected maximum request duration. The example Gunicorn timeout is
  `180` seconds to accommodate token login and slow Sunbird inference.
- `SUNBIRD_TRANSLATION_LANGUAGES` is a comma-separated allowlist of language
  codes. Codes not supported by Sunbird translation are ignored with a
  startup warning. By default it lists Sunbird's documented translation
  languages, and requests may translate between any two configured languages.
- `SUNBIRD_TTS_VOICES` is a comma-separated list such as `lug:Namuli`.
- `SUNBIRD_STT_LANGUAGES` is a comma-separated allowlist of verified STT
  language codes (defaults to `lug`).
- Verify voice/language combinations using Sunbird's authenticated
  `GET /tasks/voice/speakers?language=lug` endpoint before adding them.
- Tokens use the `token_type` returned by Sunbird's login endpoint. The
  optional `SUNBIRD_AUTH_SCHEME` setting applies only to the static-token
  fallback and defaults to `Bearer`.
- `DRF_ANON_RATE` configures the public API rate (default `20/hour`).
- `CORS_ALLOWED_ORIGINS` controls which frontend origins can call the API.

### Accounts and activity

Account endpoints use SimpleJWT access and refresh tokens in HttpOnly cookies.
Fetch a CSRF token before registration, login, refresh, logout, or another
authenticated state-changing request:

- `GET /api/v1/auth/csrf/` — returns a CSRF token and sets the CSRF cookie.
- `POST /api/v1/auth/register/` — create an account with `email`,
  `first_name`, and `password`; the new account is signed in.
- `POST /api/v1/auth/login/` — sign in with `email` and `password`.
- `POST /api/v1/auth/token/refresh/` — renew the access cookie using the
  refresh cookie.
- `POST /api/v1/auth/logout/` — blacklist the refresh token and clear both
  authentication cookies.
- `GET /api/v1/auth/me/` — return the signed-in account.
- `GET /api/v1/account/history/` — return up to 20 recent activities for the
  signed-in account.
- `GET /api/v1/auth/options/` — return currently configured languages, STT
  languages, and TTS voices for the tool forms.

For browser requests, include cookies and send the CSRF token in the
`X-CSRFToken` header for state-changing requests. The frontend Axios client
does this automatically, refreshes access tokens once after an unauthorized
response, and retries the original request. Credentialed CORS and trusted CSRF
origins are configured from `CORS_ALLOWED_ORIGINS`.
Translation, STT, and TTS remain guest-accessible; successful requests are
added to history only when the request belongs to a signed-in user. History
access is private to the authenticated account. Uploaded audio is sent to
Sunbird for processing; do not submit confidential or sensitive recordings.

Provider errors are returned with safe messages; provider response details,
credentials, and submitted text are not logged. Timeout, invalid provider
responses, and missing configuration are surfaced as API errors.

The in-process token cache is protected against concurrent requests within a
single Django process. If running multiple processes or hosts, use a shared
token cache and distributed lock before enabling credential-based login in
that deployment; do not schedule concurrent token-rotation jobs.

The Django session and CSRF middleware remain enabled. Cookie-authenticated JWT
and legacy session-authenticated DRF writes enforce CSRF checks.

## Account model

`account.User` extends Django's `AbstractUser` and requires unique email
addresses. `account.Activity` stores successful signed-in tool requests and
their provider results. Run migrations after pulling backend changes.

## Checks

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

Mocked local tests do not verify credentials or actual provider responses.
After setting credentials, run the `check_sunbird` command and test each
feature with non-sensitive text. TTS URLs returned by Sunbird are temporary
signed URLs; play or retrieve the audio promptly.

Sunbird references:

- [Authentication](https://docs.sunbird.ai/authentication.md)
- [Translation](https://docs.sunbird.ai/guides/translation.md)
- [Supported languages](https://docs.sunbird.ai/languages.md)
- [Text-to-speech API and voice catalog](https://docs.sunbird.ai/guides/text-to-speech.md)
