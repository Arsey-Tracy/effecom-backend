import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from captions.models import CaptionUploadTicket


def issue_upload_ticket(user):
    now = timezone.now()
    CaptionUploadTicket.objects.filter(expires_at__lte=now).delete()

    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(
        seconds=settings.CAPTION_UPLOAD_TICKET_TTL_SECONDS
    )
    CaptionUploadTicket.objects.create(
        user=user,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        expires_at=expires_at,
    )
    return token, expires_at


def consume_upload_ticket(token):
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    ticket = CaptionUploadTicket.objects.select_related("user").filter(
        token_hash=token_hash,
        expires_at__gt=timezone.now(),
        used_at__isnull=True,
    ).first()
    if ticket is None:
        return None

    consumed_at = timezone.now()
    claimed = CaptionUploadTicket.objects.filter(
        pk=ticket.pk,
        expires_at__gt=consumed_at,
        used_at__isnull=True,
    ).update(used_at=consumed_at)
    if not claimed or not ticket.user.is_active:
        return None
    return ticket.user
