import base64
import logging

from django.contrib.auth import authenticate
from django.http import JsonResponse

from app.security.django_adapter import can_django_user_upload

auth_logger = logging.getLogger("processing_jobs.auth")


def safe_log(log_fn, *args, **kwargs):
    """Safely log without raising exceptions if logging fails."""
    try:
        log_fn(*args, **kwargs)
    except Exception:
        pass


def authenticate_api_request(request):
    """Authenticate an incoming API request using RFC 7617 HTTP Basic Authentication

    or an active Django session.

    Returns:
        (user, None) if authentication succeeds and permissions check passes.
        (None, JsonResponse) if authentication or permission fails.
    """
    # 1. Existing authenticated session (e.g., test client.force_login or browser session)
    if getattr(request, "user", None) and request.user.is_authenticated:
        if not request.user.is_active:
            safe_log(
                auth_logger.warning,
                "API access denied: User '%s' is inactive.",
                request.user.username,
            )
            return None, JsonResponse(
                {"error": "User account is disabled."}, status=403
            )

        if not can_django_user_upload(request.user):
            safe_log(
                auth_logger.warning,
                "API access denied: User '%s' lacks upload permissions.",
                request.user.username,
            )
            return None, JsonResponse(
                {"error": "Permission denied."}, status=403
            )

        return request.user, None

    # 2. HTTP Basic Authentication header
    auth_header = request.headers.get("Authorization") or request.META.get(
        "HTTP_AUTHORIZATION", ""
    )

    if not auth_header:
        safe_log(
            auth_logger.warning,
            "API request rejected: Missing authentication credentials.",
        )
        response = JsonResponse(
            {"error": "Authentication credentials were not provided."},
            status=401,
        )
        response["WWW-Authenticate"] = 'Basic realm="API"'
        return None, response

    if not auth_header.startswith("Basic "):
        safe_log(
            auth_logger.warning,
            "API request rejected: Unsupported authentication scheme.",
        )
        response = JsonResponse(
            {
                "error": "Invalid authentication scheme. Basic authentication is required."
            },
            status=401,
        )
        response["WWW-Authenticate"] = 'Basic realm="API"'
        return None, response

    try:
        token = auth_header[6:].strip()
        decoded = base64.b64decode(token).decode("utf-8")
        if ":" not in decoded:
            raise ValueError("Missing delimiter")
        username, password = decoded.split(":", 1)
    except Exception:
        safe_log(
            auth_logger.warning,
            "API request rejected: Malformed Basic authorization header.",
        )
        response = JsonResponse(
            {"error": "Invalid authorization header format."},
            status=401,
        )
        response["WWW-Authenticate"] = 'Basic realm="API"'
        return None, response

    user = authenticate(request, username=username, password=password)
    if user is None:
        # Distinguish between invalid credentials and disabled/inactive accounts
        try:
            from django.contrib.auth import get_user_model

            UserModel = get_user_model()
            candidate = UserModel.objects.filter(username=username).first()
            if (
                candidate
                and candidate.check_password(password)
                and not candidate.is_active
            ):
                safe_log(
                    auth_logger.warning,
                    "API access denied: User '%s' is inactive.",
                    candidate.username,
                )
                return None, JsonResponse(
                    {"error": "User account is disabled."}, status=403
                )
        except Exception:
            pass

        safe_log(
            auth_logger.warning,
            "API authentication failed for username '%s'.",
            username,
        )
        response = JsonResponse(
            {"error": "Invalid credentials."},
            status=401,
        )
        response["WWW-Authenticate"] = 'Basic realm="API"'
        return None, response


    if not user.is_active:
        safe_log(
            auth_logger.warning,
            "API access denied: User '%s' is inactive.",
            user.username,
        )
        return None, JsonResponse(
            {"error": "User account is disabled."}, status=403
        )

    if not can_django_user_upload(user):
        safe_log(
            auth_logger.warning,
            "API access denied: User '%s' lacks upload permissions.",
            user.username,
        )
        return None, JsonResponse(
            {"error": "Permission denied."}, status=403
        )

    safe_log(
        auth_logger.debug,
        "API authentication successful for user '%s'.",
        user.username,
    )
    return user, None
