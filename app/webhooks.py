import hashlib
import hmac
import json
import logging
import os

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from app.models import SentEmailLog

logger = logging.getLogger(__name__)


def validate_mailersend_signature(request, signing_secret):
    """
    Validates the MailerSend webhook signature.
    """
    try:
        signature = request.headers.get("Signature")
        if not signature:
            return False
        request_body = request.body

        expected = hmac.new(
            signing_secret.encode("utf-8"), request_body, hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(signature, expected)
    except Exception as e:
        logger.error(
            "Error validating signature of MailserSend webhook: %s", e, exc_info=True
        )
        return False


@csrf_exempt
def mailersend_webhook(request):
    """
    Receives "delivered" and "opened" events from MailerSend and
    updates the SentEmailLog status accordingly.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Invalid method"}, status=405)
    signing_secret = os.getenv("MAILERSEND_WEBHOOK_SIGNING_SECRET")
    if not validate_mailersend_signature(request, signing_secret):
        return JsonResponse({"error": "Invalid signature"}, status=403)
    try:
        data = json.loads(request.body)
        event_type = data["data"]["type"]
        message_id = data["data"]["email"]["id"]
        message_tag = (
            data["data"]["email"]["tags"][0] if data["data"]["email"]["tags"] else None
        )
        if event_type == "delivered" and not message_tag:
            return JsonResponse({"error": "Missing message_tag"}, status=400)

        if event_type == "delivered":
            timestamp = data["created_at"]
            updated = SentEmailLog.objects.filter(message_tag=message_tag).update(
                status=SentEmailLog.EmailStatusChoices.DELIVERED,
                time_sent=timestamp,
                message_id=message_id,
            )
            if updated:
                return JsonResponse({"status": "success"})
            else:
                return JsonResponse({"error": "No matching log"}, status=400)

        elif event_type == "opened":
            timestamp = data["created_at"]
            updated = SentEmailLog.objects.filter(message_id=message_id).update(
                status=SentEmailLog.EmailStatusChoices.OPENED,
                time_read=timestamp,
            )
            if updated:
                return JsonResponse({"status": "success"})
            else:
                return JsonResponse({"error": "No matching log"}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def smtp2go_webhook(request):
    """
    Receives "delivered" and "open" events from SMTP2GO and
    updates the SentEmailLog status accordingly.
    """
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            event_type = data["event"]
            message_id = data["Message-Id"]
            message_tag = data["X-Custom-Header"]
            if event_type == "delivered" and not message_tag:
                return JsonResponse({"error": "Missing message_tag"}, status=400)

            if event_type == "delivered":
                timestamp = data["sendtime"]
                updated = SentEmailLog.objects.filter(message_tag=message_tag).update(
                    status=SentEmailLog.EmailStatusChoices.DELIVERED,
                    time_sent=timestamp,
                    message_id=message_id,
                )
                if updated:
                    return JsonResponse({"status": "success"})
                else:
                    return JsonResponse({"error": "No matching log"}, status=400)

            elif event_type == "open":
                timestamp = data["opened-at"]
                updated = SentEmailLog.objects.filter(message_id=message_id).update(
                    status=SentEmailLog.EmailStatusChoices.OPENED,
                    time_read=timestamp,
                )
                if updated:
                    return JsonResponse({"status": "success"})
                else:
                    return JsonResponse({"error": "No matching log"}, status=400)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    return JsonResponse({"error": "Invalid method"}, status=405)
