import logging
import os
import smtplib
import uuid
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Type

import requests
from django.utils import timezone
from dotenv import load_dotenv

from .models import SentEmailLog

load_dotenv(dotenv_path=".env")
logger = logging.getLogger(__name__)


# Provider registry for automatic registration
PROVIDER_REGISTRY: Dict[str, Type["BaseProviderClient"]] = {}


def register_provider(name: str):
    """Decorator to register a provider class by name."""

    def decorator(cls):
        PROVIDER_REGISTRY[name] = cls
        return cls

    return decorator


class BaseProviderClient(ABC):
    """Abstract base class for provider clients."""

    def __init__(self, master_credentials: dict[str, Any]):
        self.master_credentials = master_credentials

    @abstractmethod
    def provision_credentials_for_app(self, app_data: dict[str, Any]) -> dict[str, Any]:
        """Provision credentials for an app. app_data is a dict with needed info."""
        pass

    @abstractmethod
    def send_email(
        self, app_credentials: dict[str, Any], email_data: dict[str, Any]
    ) -> bool:
        """Send an email using app-specific credentials."""
        pass


def create_subdomain_for_app(app_data: dict[str, Any]) -> str:
    """
    Creates a subdomain for the given app by calling the domain provider API.
    Returns the subdomain string. Replace the implementation with your real API call.
    """
    sanitized_user_id = app_data["owner_id"].replace("_", "-")
    EMAIL_DOMAIN = os.getenv("DOMAIN_NAME")
    lookup_subdomain_url = (
        f"https://api.porkbun.com/api/json/v3/dns/retrieve/{EMAIL_DOMAIN}"
    )

    payload = {
        "secretapikey": os.getenv("DOMAIN_API_SECRET_KEY"),
        "apikey": os.getenv("DOMAIN_API_KEY"),
    }
    r = requests.post(lookup_subdomain_url, json=payload)
    if r.status_code != 200:
        raise Exception(r.text)
    data = r.json()
    try:
        subdomain = next(
            item
            for item in data["records"]
            if item["name"] == f"{sanitized_user_id}.{EMAIL_DOMAIN}"
        )
        return subdomain["name"]
    except StopIteration:
        pass

    dns_api_url = f"https://api.porkbun.com/api/json/v3/dns/create/{EMAIL_DOMAIN}"
    payload = {
        "secretapikey": os.getenv("DOMAIN_API_SECRET_KEY"),
        "apikey": os.getenv("DOMAIN_API_KEY"),
        "name": sanitized_user_id,
        "type": "A",
        "content": "1.1.1.1",
        "ttl": "600",
    }
    r = requests.post(dns_api_url, json=payload)
    if r.status_code != 200:
        raise Exception("Failed to create subdomain: %s", r.text)
    subdomain = f"{sanitized_user_id}.{EMAIL_DOMAIN}"
    logger.info("Created subdomain %s", subdomain)
    return subdomain


@register_provider("SMTP2GO")
class SMTP2GoClient(BaseProviderClient):
    """SMTP2Go SMTP client"""

    def provision_credentials_for_app(self, app_data: dict[str, Any]) -> dict[str, Any]:
        subdomain = create_subdomain_for_app(app_data)
        api_key = self.master_credentials.get("api_key")
        url = "https://api.smtp2go.com/v3/users/smtp/add"
        payload = {
            "feedback_domain": "default",
            "status": "allowed",
            "open_tracking_enabled": True,
            "username": app_data["id"],
        }
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "X-Smtp2go-Api-Key": api_key,
        }
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            raise Exception(
                "SMTP2Go API call failed with status code %s: %s",
                response.status_code,
                response.text,
            )
        data = response.json()
        results = data["data"]["results"][0]
        credentials = {
            "username": results["username"],
            "from_email": f'{results["username"]}@{subdomain}',
            "password": results["email_password"],
            "host": "mail.smtp2go.com",
            "port": "2525",
        }
        return credentials

    def send_email(
        self, app_credentials: dict[str, Any], email_data: dict[str, Any]
    ) -> bool:
        app_id = str(email_data.get("app_id", ""))
        user_id = str(email_data.get("user_id", ""))
        provider = "SMTP2GO"
        to_email = str(email_data.get("to", ""))
        subject = str(email_data.get("subject", ""))
        status = SentEmailLog.EmailStatusChoices.QUEUED
        error_message = ""
        message_tag = uuid.uuid4().hex
        try:
            host = str(app_credentials.get("host", "mail.smtp2go.com"))
            port = int(app_credentials.get("port", 2525))
            username = str(app_credentials.get("username", ""))
            password = str(app_credentials.get("password", ""))
            if not all([username, password]):
                raise ValueError("Missing SMTP2Go credentials")
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = str(email_data.get("from_email", username))
            msg["To"] = to_email
            msg["X-Custom-Header"] = message_tag
            if email_data.get("html"):
                html_part = MIMEText(email_data["html"], "html")
                msg.attach(html_part)
            with smtplib.SMTP(host, port) as server:
                server.starttls()
                server.login(username, password)
                server.send_message(msg)
            status = SentEmailLog.EmailStatusChoices.SENT
        except Exception as e:
            error_message = str(e)
            logger.error("Failed to send email via SMTP2Go: %s", e, exc_info=True)
            log_sent_email(
                app_id,
                user_id,
                provider,
                to_email,
                subject,
                status,
                message_tag,
                error_message,
            )
            return False
        finally:
            log_sent_email(
                app_id,
                user_id,
                provider,
                to_email,
                subject,
                status,
                message_tag,
                error_message,
            )
        return True


@register_provider("MAILERSEND")
class MailerSendClient(BaseProviderClient):
    """MailerSend client"""

    def provision_credentials_for_app(self, app_data: dict[str, Any]) -> dict[str, Any]:
        token = self.master_credentials.get("token")
        domain_id = self.master_credentials.get("domain_id")
        url = f"https://api.mailersend.com/v1/domains/{domain_id}/smtp-users"
        payload = {"name": app_data["id"], "enabled": True}
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        r = requests.post(url, json=payload, headers=headers)
        data = r.json()
        if r.status_code != 201:
            raise Exception("MailerSend error: %s", r.text)
        credentials = {
            "username": data["data"]["username"],
            "from_email": data["data"]["username"],
            "password": data["data"]["password"],
            "host": data["data"]["server"],
            "port": str(data["data"]["port"]).split(" ")[0],
        }
        return credentials

    def send_email(
        self, app_credentials: dict[str, Any], email_data: dict[str, Any]
    ) -> bool:
        app_id = str(email_data.get("app_id", ""))
        user_id = str(email_data.get("user_id", ""))
        provider = "MAILERSEND"
        to_email = str(email_data.get("to", ""))
        subject = str(email_data.get("subject", ""))
        status = SentEmailLog.EmailStatusChoices.QUEUED
        error_message = ""
        message_tag = uuid.uuid4().hex
        try:
            host = str(app_credentials.get("host", "smtp.mailersend.com"))
            port = int(app_credentials.get("port", 2525))
            username = str(app_credentials.get("username", ""))
            password = str(app_credentials.get("password", ""))
            if not all([username, password]):
                raise ValueError("Missing MailerSend credentials")
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = str(email_data.get("from_email", username))
            msg["To"] = to_email
            msg["X-MailerSend-Tags"] = message_tag
            if email_data.get("html"):
                html_part = MIMEText(email_data["html"], "html")
                msg.attach(html_part)
            with smtplib.SMTP(host, port) as server:
                server.starttls()
                server.login(username, password)
                server.send_message(msg)
            logger.info("Email sent successfully via %s", provider)
            status = SentEmailLog.EmailStatusChoices.SENT
        except Exception as e:
            error_message = str(e)
            logger.error("Error sending email via %s: %s", provider, e, exc_info=True)
            log_sent_email(
                app_id,
                user_id,
                provider,
                to_email,
                subject,
                status,
                message_tag,
                error_message,
            )
            return False
        finally:
            log_sent_email(
                app_id,
                user_id,
                provider,
                to_email,
                subject,
                status,
                message_tag,
                error_message,
            )
        return True


def get_provider_client(
    provider_type: str, master_credentials: dict[str, Any]
) -> BaseProviderClient:
    """Factory function to get the appropriate provider client using the registry."""
    client_class = PROVIDER_REGISTRY.get(provider_type)
    if not client_class:
        raise ValueError("Unsupported provider type: %s", provider_type)
    return client_class(master_credentials)


def log_sent_email(
    app_id: str,
    user_id: str,
    provider: str,
    to_email: str,
    subject: str,
    status: str,
    message_tag: str = "",
    error_message: str = "",
):
    """
    Utility to log a sent email event and track its status.
    """
    try:
        SentEmailLog.objects.update_or_create(
            message_tag=message_tag,
            defaults=dict(
                app_id=app_id,
                user_id=user_id,
                provider=provider,
                to_email=to_email,
                subject=subject or "",
                status=status,
                error_message=error_message or "",
                time_sent=timezone.now(),
            ),
        )
    except Exception as e:
        logger.error("Error logging email: %s", e, exc_info=True)
