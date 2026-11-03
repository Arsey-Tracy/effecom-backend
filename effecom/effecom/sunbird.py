import re
from threading import Lock

import requests
from django.conf import settings


class SunbirdError(Exception):
    def __init__(self, message, status_code=502):
        self.status_code = status_code
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
                timeout=(5, 15),
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
    request_kwargs = {
        **kwargs,
        "headers": {
            **kwargs.get("headers", {}),
            "Authorization": f"{scheme} {token}",
        },
        "timeout": kwargs.get("timeout", (5, 30)),
    }

    try:
        response = method(
            f"{settings.SUNBIRD_BASE_URL}{endpoint}",
            **request_kwargs,
        )
    except requests.Timeout as exc:
        raise SunbirdError("Sunbird request timed out.", status_code=504) from exc
    except requests.RequestException as exc:
        raise SunbirdError("Could not connect to Sunbird.") from exc

    if response.status_code == 401 and has_login_credentials():
        scheme, token = get_auth(force_refresh=True, rejected_token=token)
        retry_kwargs = {
            **request_kwargs,
            "headers": {
                **request_kwargs["headers"],
                "Authorization": f"{scheme} {token}",
            },
        }
        try:
            response = method(
                f"{settings.SUNBIRD_BASE_URL}{endpoint}",
                **retry_kwargs,
            )
        except requests.Timeout as exc:
            raise SunbirdError(
                "Sunbird request timed out.",
                status_code=504,
            ) from exc
        except requests.RequestException as exc:
            raise SunbirdError("Could not connect to Sunbird.") from exc

    return response, token


def post_task(endpoint, payload, timeout=(5, 30)):
    response, _ = _request_with_auth_retry(
        requests.post,
        endpoint,
        headers={"accept": "application/json"},
        json=payload,
        timeout=timeout,
    )

    try:
        result = response.json()
    except ValueError as exc:
        raise SunbirdError("Sunbird returned an invalid response.") from exc

    if not isinstance(result, dict):
        raise SunbirdError("Sunbird returned an invalid response.")

    if not response.ok:
        if response.status_code in {401, 403}:
            message = (
                "Sunbird rejected the configured login credentials."
                if has_login_credentials()
                else "Sunbird rejected the configured access token."
            )
            raise SunbirdError(message, status_code=503)
        status_code = 400 if response.status_code == 400 else 502
        message = (
            "Sunbird could not process this request."
            if status_code == 400
            else "Sunbird could not complete this request."
        )
        raise SunbirdError(message, status_code=status_code)

    return result


def check_authentication():
    """Verify Sunbird authentication, retrying login once after a 401."""
    response, _ = _request_with_auth_retry(
        requests.get,
        "/auth/me",
        timeout=(5, 15),
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
