import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import TestCase

pytestmark = pytest.mark.django_db

MAILERSEND_URL = "/webhooks/mailersend"
SMTP2GO_URL = "/webhooks/smtp2go"
MAILERSEND_SECRET = "testsecret"


def mailersend_payload(
    event="delivered",
    message_tag="tag1",
    message_id="mid1",
    timestamp="2024-01-01T00:00:00Z",
):
    email = {
        "id": message_id,
        "tags": [message_tag] if message_tag else [],
    }
    return {
        "data": {"type": event, "email": email},
        "created_at": timestamp,
    }


def smtp2go_payload(
    event="delivered",
    message_tag="tag1",
    message_id="mid1",
    timestamp="2024-01-01T00:00:00Z",
):
    payload = {
        "event": event,
        "Message-Id": message_id,
        "sendtime": timestamp,
        "opened-at": timestamp,
        "X-Custom-Header": message_tag,
    }
    if message_tag:
        payload["X-Custom-Header"] = message_tag
    return payload


def mailersend_signature(body: bytes, secret: str = MAILERSEND_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class TestMailersendSignature(TestCase):
    @patch("os.getenv", return_value=MAILERSEND_SECRET)
    def test_valid_signature(self, mock_getenv):
        payload = mailersend_payload()
        body = json.dumps(payload).encode()
        signature = mailersend_signature(body)
        resp = self.client.post(
            MAILERSEND_URL,
            data=body,
            content_type="application/json",
            **{"HTTP_SIGNATURE": signature},
        )
        assert resp.status_code != 403

    @patch("os.getenv", return_value=MAILERSEND_SECRET)
    def test_invalid_signature(self, mock_getenv):
        payload = mailersend_payload()
        body = json.dumps(payload).encode()
        signature = "invalidsignature"
        resp = self.client.post(
            MAILERSEND_URL,
            data=body,
            content_type="application/json",
            **{"HTTP_SIGNATURE": signature},
        )
        assert resp.status_code == 403
        assert resp.json()["error"] == "Invalid signature"

    @patch("os.getenv", return_value=MAILERSEND_SECRET)
    def test_missing_signature(self, mock_getenv):
        payload = mailersend_payload()
        body = json.dumps(payload).encode()
        resp = self.client.post(
            MAILERSEND_URL,
            data=body,
            content_type="application/json",
        )
        assert resp.status_code == 403
        assert resp.json()["error"] == "Invalid signature"


class TestMailersendWebhook(TestCase):
    @patch("os.getenv", return_value=MAILERSEND_SECRET)
    @patch("app.webhooks.SentEmailLog")
    def test_sent_success(self, mock_log, mock_getenv):
        mock_qs = MagicMock()
        mock_qs.update.return_value = 1
        mock_log.objects.filter.return_value = mock_qs
        delivered_status_mock = MagicMock()
        mock_log.EmailStatusChoices.DELIVERED = delivered_status_mock
        payload = mailersend_payload(event="delivered")
        body = json.dumps(payload).encode()
        signature = mailersend_signature(body)
        resp = self.client.post(
            MAILERSEND_URL,
            data=body,
            content_type="application/json",
            **{"HTTP_SIGNATURE": signature},
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "success"}
        mock_log.objects.filter.assert_called_with(message_tag="tag1")
        mock_qs.update.assert_called_with(
            status=delivered_status_mock,
            time_sent=payload["created_at"],
            message_id="mid1",
        )

    @patch("os.getenv", return_value=MAILERSEND_SECRET)
    @patch("app.webhooks.SentEmailLog")
    def test_sent_missing_tag(self, mock_log, mock_getenv):
        payload = mailersend_payload(event="delivered", message_tag="")
        body = json.dumps(payload).encode()
        signature = mailersend_signature(body)
        resp = self.client.post(
            MAILERSEND_URL,
            data=body,
            content_type="application/json",
            **{"HTTP_SIGNATURE": signature},
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "Missing message_tag"

    @patch("os.getenv", return_value=MAILERSEND_SECRET)
    @patch("app.webhooks.SentEmailLog")
    def test_sent_no_matching_log(self, mock_log, mock_getenv):
        mock_qs = MagicMock()
        mock_qs.update.return_value = 0
        mock_log.objects.filter.return_value = mock_qs
        payload = mailersend_payload(event="delivered")
        body = json.dumps(payload).encode()
        signature = mailersend_signature(body)
        resp = self.client.post(
            MAILERSEND_URL,
            data=body,
            content_type="application/json",
            **{"HTTP_SIGNATURE": signature},
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "No matching log"

    @patch("os.getenv", return_value=MAILERSEND_SECRET)
    @patch("app.webhooks.SentEmailLog")
    def test_opened_success(self, mock_log, mock_getenv):
        mock_qs = MagicMock()
        mock_qs.update.return_value = 1
        mock_log.objects.filter.return_value = mock_qs
        open_status_mock = MagicMock()
        mock_log.EmailStatusChoices.OPENED = open_status_mock
        payload = mailersend_payload(event="opened")
        payload["created_at"] = "2024-01-02T00:00:00Z"
        body = json.dumps(payload).encode()
        signature = mailersend_signature(body)
        resp = self.client.post(
            MAILERSEND_URL,
            data=body,
            content_type="application/json",
            **{"HTTP_SIGNATURE": signature},
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "success"}
        mock_log.objects.filter.assert_called_with(message_id="mid1")
        mock_qs.update.assert_called_with(
            status=open_status_mock,
            time_read=payload["created_at"],
        )

    @patch("os.getenv", return_value=MAILERSEND_SECRET)
    def test_invalid_method(self, mock_getenv):
        resp = self.client.get(MAILERSEND_URL)
        assert resp.status_code == 405
        assert resp.json()["error"] == "Invalid method"


class TestSmtp2goWebhook(TestCase):
    MESSAGE_ID = "mid1"

    @patch("app.webhooks.SentEmailLog")
    def test_delivered_success(self, mock_log):
        mock_qs = MagicMock()
        mock_qs.update.return_value = 1
        delivered_status_mock = MagicMock()
        mock_log.EmailStatusChoices.DELIVERED = delivered_status_mock
        mock_log.objects.filter.return_value = mock_qs
        payload = smtp2go_payload()
        resp = self.client.post(
            SMTP2GO_URL, data=json.dumps(payload), content_type="application/json"
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "success"}
        mock_log.objects.filter.assert_called_with(message_tag="tag1")
        mock_qs.update.assert_called_with(
            status=delivered_status_mock,
            time_sent=payload["sendtime"],
            message_id=self.MESSAGE_ID,
        )

    @patch("app.webhooks.SentEmailLog")
    def test_delivered_missing_tag(self, mock_log):
        payload = smtp2go_payload(message_tag="")
        resp = self.client.post(
            SMTP2GO_URL, data=json.dumps(payload), content_type="application/json"
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "Missing message_tag"

    @patch("app.webhooks.SentEmailLog")
    def test_delivered_no_matching_log(self, mock_log):
        mock_qs = MagicMock()
        mock_qs.update.return_value = 0
        mock_log.objects.filter.return_value = mock_qs
        payload = smtp2go_payload()
        resp = self.client.post(
            SMTP2GO_URL, data=json.dumps(payload), content_type="application/json"
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "No matching log"

    @patch("app.webhooks.SentEmailLog")
    def test_open_success(self, mock_log):
        mock_qs = MagicMock()
        mock_qs.update.return_value = 1
        mock_log.objects.filter.return_value = mock_qs
        open_status_mock = MagicMock()
        mock_log.EmailStatusChoices.OPENED = open_status_mock
        payload = smtp2go_payload(event="open")
        resp = self.client.post(
            SMTP2GO_URL, data=json.dumps(payload), content_type="application/json"
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "success"}
        mock_log.objects.filter.assert_called_with(message_id="mid1")
        mock_qs.update.assert_called_with(
            status=open_status_mock,
            time_read=payload["opened-at"],
        )

    def test_invalid_method(self):
        resp = self.client.get(SMTP2GO_URL)
        assert resp.status_code == 405
        assert resp.json()["error"] == "Invalid method"
