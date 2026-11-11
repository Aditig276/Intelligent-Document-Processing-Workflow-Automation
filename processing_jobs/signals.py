import logging
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

auth_logger = logging.getLogger("processing_jobs.auth")


@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    try:
        ip = request.META.get("REMOTE_ADDR") if request else "unknown"
        auth_logger.info("User '%s' logged in successfully from %s.", user.username, ip)
    except Exception:
        pass


@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    try:
        username = user.username if user else "anonymous"
        auth_logger.info("User '%s' logged out.", username)
    except Exception:
        pass


@receiver(user_login_failed)
def log_user_login_failed(sender, credentials, request, **kwargs):
    try:
        username = credentials.get("username", "unknown") if credentials else "unknown"
        ip = request.META.get("REMOTE_ADDR") if request else "unknown"
        auth_logger.warning("Failed login attempt for username '%s' from %s.", username, ip)
    except Exception:
        pass
