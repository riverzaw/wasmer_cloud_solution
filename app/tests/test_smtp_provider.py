from unittest import mock

import pytest

from app import smtp_provider
from app.smtp_provider import (MailerSendClient, SMTP2GoClient,
                               create_subdomain_for_app, get_provider_client,
                               log_sent_email)

DUMMY_MASTER_CREDENTIALS = {
    "api_key": "dummy_api_key",
    "token": "dummy_token",
    "domain_id": "dummy_domain_id",
}


@pytest.fixture
def app_data():
    return {"id": "app123", "owner_id": "user_1"}


@pytest.fixture
def email_data():
    return {
        "app_id": "app123",
        "user_id": "user_1",
        "to": "to@example.com",
        "subject": "Test Subject",
        "from_email": "from@example.com",
        "text": "Hello",
        "html": "<b>Hello</b>",
    }


@pytest.fixture
def app_credentials():
    return {
        "username": "smtp_user",
        "from_email": "smtp_user@sub.domain.com",
        "password": "smtp_pass",
        "host": "smtp.example.com",
        "port": 2525,
    }


@mock.patch("app.smtp_provider.requests.post")
def test_create_subdomain_for_app_success(mock_post, app_data):
    # Simulate subdomain already exists
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "records": [{"name": f"user-1.testdomain.com"}]
    }
    with mock.patch.dict("os.environ", {"DOMAIN_NAME": "testdomain"}):
        subdomain = create_subdomain_for_app({"owner_id": "user_1"})
    assert subdomain == "user-1.testdomain.com"


@mock.patch("app.smtp_provider.requests.post")
def test_create_subdomain_for_app_create_new(mock_post, app_data):
    # Simulate subdomain does not exist, so it creates one
    def side_effect(*args, **kwargs):
        if "retrieve" in args[0]:
            m = mock.Mock()
            m.status_code = 200
            m.json.return_value = {"records": []}
            return m
        else:
            m = mock.Mock()
            m.status_code = 200
            return m

    mock_post.side_effect = side_effect
    with mock.patch.dict("os.environ", {"DOMAIN_NAME": "testdomain"}):
        with mock.patch("app.smtp_provider.logger.info") as mock_log:
            subdomain = create_subdomain_for_app({"owner_id": "user_1"})
            assert subdomain == "user-1.testdomain"
            mock_log.assert_called_with("Created subdomain %s", "user-1.testdomain")


@mock.patch("app.smtp_provider.requests.post")
def test_create_subdomain_for_app_error(mock_post, app_data):
    mock_post.return_value.status_code = 500
    mock_post.return_value.text = "error"
    with pytest.raises(Exception):
        create_subdomain_for_app({"owner_id": "user_1"})


@mock.patch("app.smtp_provider.requests.post")
def test_smtp2go_provision_credentials_success(mock_post, app_data):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "data": {"results": [{"username": "smtp_user", "email_password": "smtp_pass"}]}
    }
    with mock.patch(
        "app.smtp_provider.create_subdomain_for_app", return_value="sub.domain.com"
    ):
        client = SMTP2GoClient({"api_key": "dummy_api_key"})
        creds = client.provision_credentials_for_app(
            {"id": "app123", "owner_id": "user_1"}
        )
        assert creds["username"] == "smtp_user"
        assert creds["from_email"] == "smtp_user@sub.domain.com"
        assert creds["password"] == "smtp_pass"
        assert creds["host"] == "mail.smtp2go.com"
        assert creds["port"] == "2525"


@mock.patch("app.smtp_provider.requests.post")
def test_smtp2go_provision_credentials_error(mock_post, app_data):
    mock_post.return_value.status_code = 400
    mock_post.return_value.text = "fail"
    with mock.patch(
        "app.smtp_provider.create_subdomain_for_app", return_value="sub.domain.com"
    ):
        client = SMTP2GoClient({"api_key": "dummy_api_key"})
        with pytest.raises(Exception):
            client.provision_credentials_for_app({"id": "app123", "owner_id": "user_1"})


@mock.patch("app.smtp_provider.smtplib.SMTP")
@mock.patch("app.smtp_provider.log_sent_email")
def test_smtp2go_send_email_success(mock_log, mock_smtp, app_credentials, email_data):
    client = SMTP2GoClient({"api_key": "dummy_api_key"})
    mock_server = mock.Mock()
    mock_smtp.return_value.__enter__.return_value = mock_server
    result = client.send_email(app_credentials, email_data)
    assert result is True
    assert mock_server.send_message.called
    assert mock_log.call_count == 1


@mock.patch("app.smtp_provider.smtplib.SMTP", side_effect=Exception("smtp error"))
@mock.patch("app.smtp_provider.log_sent_email")
@mock.patch("app.smtp_provider.logger.error")
def test_smtp2go_send_email_error(
    mock_logger, mock_log, mock_smtp, app_credentials, email_data
):
    client = SMTP2GoClient({"api_key": "dummy_api_key"})
    result = client.send_email(app_credentials, email_data)
    assert result is False
    assert mock_logger.called
    assert mock_log.call_count == 2


@mock.patch("app.smtp_provider.requests.post")
def test_mailersend_provision_credentials_success(mock_post, app_data):
    mock_post.return_value.status_code = 201
    mock_post.return_value.json.return_value = {
        "data": {
            "username": "smtp_user",
            "password": "smtp_pass",
            "server": "smtp.mailersend.com",
            "port": "2525",
        }
    }
    client = MailerSendClient({"token": "dummy_token", "domain_id": "dummy_domain_id"})
    creds = client.provision_credentials_for_app({"id": "app123", "owner_id": "user_1"})
    assert creds["username"] == "smtp_user"
    assert creds["password"] == "smtp_pass"
    assert creds["host"] == "smtp.mailersend.com"
    assert creds["port"] == "2525"


@mock.patch("app.smtp_provider.requests.post")
def test_mailersend_provision_credentials_error(mock_post, app_data):
    mock_post.return_value.status_code = 400
    mock_post.return_value.text = "fail"
    client = MailerSendClient({"token": "dummy_token", "domain_id": "dummy_domain_id"})
    with pytest.raises(Exception):
        client.provision_credentials_for_app({"id": "app123", "owner_id": "user_1"})


@mock.patch("app.smtp_provider.smtplib.SMTP")
@mock.patch("app.smtp_provider.log_sent_email")
def test_mailersend_send_email_success(
    mock_log, mock_smtp, app_credentials, email_data
):
    client = MailerSendClient({"token": "dummy_token", "domain_id": "dummy_domain_id"})
    mock_server = mock.Mock()
    mock_smtp.return_value.__enter__.return_value = mock_server
    result = client.send_email(app_credentials, email_data)
    assert result is True
    assert mock_server.send_message.called
    assert mock_log.call_count == 1


@mock.patch("app.smtp_provider.smtplib.SMTP", side_effect=Exception("smtp error"))
@mock.patch("app.smtp_provider.log_sent_email")
@mock.patch("app.smtp_provider.logger.error")
def test_mailersend_send_email_error(
    mock_logger, mock_log, mock_smtp, app_credentials, email_data
):
    client = MailerSendClient({"token": "dummy_token", "domain_id": "dummy_domain_id"})
    result = client.send_email(app_credentials, email_data)
    assert result is False
    assert mock_logger.called
    assert mock_log.call_count == 2


@mock.patch("app.smtp_provider.SentEmailLog.objects.update_or_create")
def test_log_sent_email_success(mock_update):
    log_sent_email(
        app_id="app123",
        user_id="user_1",
        provider="SMTP2GO",
        to_email="to@example.com",
        subject="Test",
        status="sent",
        message_tag="tag1",
        error_message="",
    )
    assert mock_update.called


@mock.patch(
    "app.smtp_provider.SentEmailLog.objects.update_or_create",
    side_effect=Exception("db error"),
)
@mock.patch("app.smtp_provider.logger.error")
def test_log_sent_email_error(mock_logger, mock_update):
    log_sent_email(
        app_id="app123",
        user_id="user_1",
        provider="SMTP2GO",
        to_email="to@example.com",
        subject="Test",
        status="sent",
        message_tag="tag1",
        error_message="",
    )
    assert mock_logger.called


@pytest.mark.parametrize(
    "provider_type,expected_class",
    [
        ("SMTP2GO", SMTP2GoClient),
        ("MAILERSEND", MailerSendClient),
    ],
)
def test_get_provider_client_success(provider_type, expected_class):
    client = get_provider_client(provider_type, DUMMY_MASTER_CREDENTIALS)
    assert isinstance(client, expected_class)


def test_get_provider_client_error():
    with pytest.raises(ValueError):
        get_provider_client("UNKNOWN", DUMMY_MASTER_CREDENTIALS)
