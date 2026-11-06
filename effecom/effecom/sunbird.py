import re
from threading import Lock
from time import sleep

import requests
from django.conf import settings


class SunbirdError(Exception):
    def __init__(self, message, status_code=502, *, code=None, retry_after=None):
        self.status_code = status_code
        self.code = code
        self.retry_after = retry_after
        super().__init__(message)


_token_lock = Lock()
_cached_auth = None


def has_login_credentials():
    return bool(settings.SUNBIRD_USERNAME and settings.SUNBIRD_PASSWORD)


def _validate_scheme(scheme):
    if not isinstance(scheme, str) or not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_-]*", scheme
    ):
        raise SunbirdError(
            "Sunbird authentication is misconfigured.",
            status_code=503,
        )
    return scheme


def get_auth(force_refresh=False, rejected_token=None):
    """Return a cached Sunbird token, logging in lazily when required."""
    global _cached_auth

    with _token_lock:
        if _cached_auth is not None and (
            not force_refresh or _cached_auth[1] != rejected_token
        ):
            return _cached_auth

        if not force_refresh and settings.SUNBIRD_ACCESS_TOKEN:
            return (
                _validate_scheme(settings.SUNBIRD_AUTH_SCHEME),
                settings.SUNBIRD_ACCESS_TOKEN,
            )

        if not has_login_credentials():
            raise SunbirdError(
                "Sunbird is not configured. Set SUNBIRD_USERNAME and "
                "SUNBIRD_PASSWORD or SUNBIRD_ACCESS_TOKEN.",
                status_code=503,
            )

        try:
            response = requests.post(
                f"{settings.SUNBIRD_BASE_URL}/auth/token",
                data={
                    "username": settings.SUNBIRD_USERNAME,
                    "password": settings.SUNBIRD_PASSWORD,
                },
                headers={"accept": "application/json"},
                timeout=(
                    settings.SUNBIRD_CONNECT_TIMEOUT_SECONDS,
                    settings.SUNBIRD_AUTH_TIMEOUT_SECONDS,
                ),
            )
        except requests.Timeout as exc:
            raise SunbirdError(
                "Sunbird authentication timed out.",
                status_code=504,
            ) from exc
        except requests.RequestException as exc:
            raise SunbirdError(
                "Could not connect to Sunbird authentication."
            ) from exc

        if not response.ok:
            if response.status_code in {401, 403}:
                raise SunbirdError(
                    "Sunbird rejected the configured login credentials.",
                    status_code=503,
                )
            raise SunbirdError(
                "Sunbird could not issue an access token.",
                status_code=503,
            )

        try:
            result = response.json()
        except ValueError as exc:
            raise SunbirdError(
                "Sunbird returned an invalid authentication response.",
                status_code=503,
            ) from exc

        if not isinstance(result, dict):
            raise SunbirdError(
                "Sunbird returned an invalid authentication response.",
                status_code=503,
            )

        token = result.get("access_token")
        scheme = result.get("token_type", "bearer")
        if not isinstance(token, str) or not token.strip():
            raise SunbirdError(
                "Sunbird did not return an access token.",
                status_code=503,
            )

        _cached_auth = (_validate_scheme(scheme), token)
        return _cached_auth


def clear_auth_cache():
    """Clear cached credentials, primarily for isolated tests."""
    global _cached_auth
    with _token_lock:
        _cached_auth = None


def _request_with_auth_retry(method, endpoint, **kwargs):
    scheme, token = get_auth()
    base_kwargs = {
        **kwargs,
        "headers": {
            **kwargs.get("headers", {}),
            "Authorization": f"{scheme} {token}",
        },
        "timeout": kwargs.get("timeout")
        or (
            settings.SUNBIRD_CONNECT_TIMEOUT_SECONDS,
            settings.SUNBIRD_TTS_TIMEOUT_SECONDS,
        ),
    }

    def send(request_kwargs):
        retries = 0
        while True:
            for file_value in request_kwargs.get("files", {}).values():
                file_obj = (
                    file_value[1]
                    if isinstance(file_value, tuple)
                    else file_value
                )
                if hasattr(file_obj, "seek"):
                    file_obj.seek(0)
            try:
                response = method(
                    f"{settings.SUNBIRD_BASE_URL}{endpoint}",
                    **request_kwargs,
                )
            except requests.Timeout as exc:
                raise SunbirdError(
                    "Sunbird request timed out.",
                    status_code=504,
                    code="upstream_timeout",
                ) from exc
            except requests.ConnectionError as exc:
                if retries >= 2:
                    raise SunbirdError(
                        "Could not connect to Sunbird.",
                        code="upstream_unavailable",
                    ) from exc
                sleep(0.25 * (2**retries))
                retries += 1
                continue
            except requests.RequestException as exc:
                raise SunbirdError(
                    "Could not connect to Sunbird.",
                    code="upstream_unavailable",
                ) from exc

            if response.status_code not in {502, 503, 504} or retries >= 2:
                return response
            sleep(0.25 * (2**retries))
            retries += 1

    response = send(base_kwargs)

    if response.status_code == 401 and has_login_credentials():
        scheme, token = get_auth(force_refresh=True, rejected_token=token)
        retry_kwargs = {
            **base_kwargs,
            "headers": {
                **base_kwargs["headers"],
                "Authorization": f"{scheme} {token}",
            },
        }
        response = send(retry_kwargs)

    return response, token


def post_task(endpoint, payload, timeout=None):
    response, _ = _request_with_auth_retry(
        requests.post,
        endpoint,
        headers={"accept": "application/json"},
        json=payload,
        timeout=timeout,
    )

    return _task_result(response)


def post_file_task(endpoint, *, files, data, timeout=None):
    response, _ = _request_with_auth_retry(
        requests.post,
        endpoint,
        headers={"accept": "application/json"},
        files=files,
        data=data,
        timeout=timeout,
    )

    return _task_result(response)


def _task_result(response):
    if not response.ok:
        if response.status_code in {401, 403}:
            message = (
                "Sunbird rejected the configured login credentials."
                if has_login_credentials()
                else "Sunbird rejected the configured access token."
            )
            raise SunbirdError(
                message,
                status_code=503,
                code="upstream_auth_failed",
            )
        if response.status_code == 429:
            headers = getattr(response, "headers", {})
            retry_after = headers.get("Retry-After")
            if not isinstance(retry_after, str) or not re.fullmatch(
                r"\d{1,5}", retry_after
            ):
                retry_after = None
            raise SunbirdError(
                "Sunbird is busy. Please retry shortly.",
                status_code=503,
                code="upstream_busy",
                retry_after=retry_after,
            )
        if 400 <= response.status_code < 500:
            raise SunbirdError(
                "Sunbird could not process this request.",
                status_code=422,
                code="upstream_rejected",
            )
        raise SunbirdError(
            "Sunbird could not complete this request.",
            status_code=502,
            code="upstream_unavailable",
        )

    try:
        result = response.json()
    except ValueError as exc:
        raise SunbirdError(
            "Sunbird returned an invalid response.",
            code="upstream_invalid_response",
        ) from exc

    if not isinstance(result, dict):
        raise SunbirdError(
            "Sunbird returned an invalid response.",
            code="upstream_invalid_response",
        )

    return result


def check_authentication():
    """Verify Sunbird authentication, retrying login once after a 401."""
    response, _ = _request_with_auth_retry(
        requests.get,
        "/auth/me",
        timeout=(
            settings.SUNBIRD_CONNECT_TIMEOUT_SECONDS,
            settings.SUNBIRD_AUTH_TIMEOUT_SECONDS,
        ),
    )

    if response.status_code in {401, 403}:
        message = (
            "Sunbird rejected the configured login credentials."
            if has_login_credentials()
            else "Sunbird rejected the configured access token."
        )
        raise SunbirdError(message, status_code=503)
    if not response.ok:
        raise SunbirdError(
            f"Sunbird authentication check failed (HTTP {response.status_code}).",
            status_code=502,
        )
