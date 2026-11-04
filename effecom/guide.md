# EFFECOM backend: DRF, Sunbird translation, and text-to-speech

This backend iteration uses Django REST Framework for guest-accessible text
translation and text-to-speech (TTS), plus session-based accounts and private
per-user activity history. Speech-to-text and video captions are not included.

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
frontend defaults to `http://localhost:8000` for the API; set
`NEXT_PUBLIC_EFFECOM_API_URL` when the backend runs elsewhere.
Use the same hostname (`localhost` or `127.0.0.1`) for frontend and backend
while developing so browser session cookies are sent consistently.

Run initial migrations and start Django:

```powershell
python manage.py migrate
python manage.py seed_languages
python manage.py runserver
```

## Render deployment

Create a Render Web Service with this directory (`effecom`) as its **Root
Directory**. Set the **Build Command** to `bash build.sh` and the **Start
Command** to `gunicorn effecom.wsgi:application`. The build script installs
the pinned requirements, collects static files, applies database migrations,
and seeds the configured translation languages. Keep a persistent PostgreSQL
database attached through `DATABASE_URL`; the local SQLite database is not a
production persistence option on Render.

Configure at least `DJANGO_DEBUG=false`, a unique secret `DJANGO_SECRET_KEY`,
`DJANGO_ALLOWED_HOSTS` with the service hostname, `CORS_ALLOWED_ORIGINS` with
the frontend origin, and Sunbird credentials in Render's environment settings.
Do not set `GUEST_COOKIE_SECURE=false` in production; HTTPS is required for
guest cookies. Run the deployment with the same environment variables on both
build and runtime phases so static collection and migrations use the intended
settings and database.

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

Both endpoints accept JSON `POST` requests, are available to guest users, and
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

The versioned resource endpoints are also available:

- `GET /api/v1/languages/?capability=translation` lists active translation
  languages. `capability=stt` is empty until Sunbird's transcription contract
  and supported-language list are verified.
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
configured translation language list changes. It seeds the checked-in
language fixture, enables translation only for configured languages, and
leaves speech-to-text disabled pending provider verification.

Versioned resource endpoints use errors shaped as
`{"error":{"code":"...","message":"...","details":{}}}`. Translation text is
sent to Sunbird for processing; do not submit confidential or sensitive text.

The browser offers automatic source-language detection and only the language
codes supported by Sunbird translation. The configured translation read
timeout defaults to 120 seconds (`SUNBIRD_TRANSLATION_TIMEOUT_SECONDS`) to
allow for model inference; connect timeout remains 5 seconds. Use complete,
reasonably short sentences for better quality.

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

### Validation and provider configuration

- `SUNBIRD_MAX_TEXT_LENGTH` caps text input (default `2000` characters).
- `SUNBIRD_TRANSLATION_TIMEOUT_SECONDS` configures the translation read
  timeout (default `120` seconds).
- `SUNBIRD_TRANSLATION_LANGUAGES` is a comma-separated allowlist of language
  codes. Codes not supported by Sunbird translation are ignored with a
  startup warning. By default it lists Sunbird's documented translation
  languages, and requests may translate between any two configured languages.
- `SUNBIRD_TTS_VOICES` is a comma-separated list such as `lug:Namuli`.
- Verify voice/language combinations using Sunbird's authenticated
  `GET /tasks/voice/speakers?language=lug` endpoint before adding them.
- Tokens use the `token_type` returned by Sunbird's login endpoint. The
  optional `SUNBIRD_AUTH_SCHEME` setting applies only to the static-token
  fallback and defaults to `Bearer`.
- `DRF_ANON_RATE` configures the public API rate (default `20/hour`).
- `CORS_ALLOWED_ORIGINS` controls which frontend origins can call the API.

### Accounts and activity

Account endpoints use Django session cookies. Fetch a CSRF token before
registration, login, logout, or another authenticated POST:

- `GET /api/v1/auth/csrf/` — returns a CSRF token and sets the CSRF cookie.
- `POST /api/v1/auth/register/` — create an account with `email`,
  `first_name`, and `password`; the new account is signed in.
- `POST /api/v1/auth/login/` — sign in with `email` and `password`.
- `POST /api/v1/auth/logout/` — end the current session.
- `GET /api/v1/auth/me/` — return the signed-in account.
- `GET /api/v1/account/history/` — return up to 20 recent activities for the
  signed-in account.
- `GET /api/v1/auth/options/` — return currently configured languages and
  TTS voices for the tool forms.

For browser requests, include cookies (`credentials: "include"`) and send the
CSRF token in the `X-CSRFToken` header for state-changing requests. Credentialed
CORS and trusted CSRF origins are configured from `CORS_ALLOWED_ORIGINS`.
Translation and TTS remain guest-accessible; successful requests are added to
history only when the request belongs to a signed-in user. History access is
private to the authenticated account.

Provider errors are returned with safe messages; provider response details,
credentials, and submitted text are not logged. Timeout, invalid provider
responses, and missing configuration are surfaced as API errors.

The in-process token cache is protected against concurrent requests within a
single Django process. If running multiple processes or hosts, use a shared
token cache and distributed lock before enabling credential-based login in
that deployment; do not schedule concurrent token-rotation jobs.

The Django session and CSRF middleware remain enabled. Session-authenticated
DRF requests enforce CSRF checks; the browser frontend obtains a CSRF token
before state-changing requests.

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
