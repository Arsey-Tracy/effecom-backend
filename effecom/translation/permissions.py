from django.utils import timezone
from rest_framework.permissions import BasePermission
from rest_framework.throttling import SimpleRateThrottle

from .models import GuestSession


class IsUserOrGuest(BasePermission):
    def has_permission(self, request, view):
        if request.user and request.user.is_authenticated:
            return True
        return (
            isinstance(request.auth, GuestSession)
            and request.auth.expires_at > timezone.now()
        )


class GuestBurstThrottle(SimpleRateThrottle):
    scope = "guest-burst"

    def get_cache_key(self, request, view):
        if isinstance(request.auth, GuestSession):
            ident = f"guest-{request.auth.pk}"
        elif request.user and request.user.is_authenticated:
            ident = f"user-{request.user.pk}"
        else:
            ident = self.get_ident(request)
        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }
