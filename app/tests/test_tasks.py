import logging
from unittest import mock

import pytest

from app import tasks
from app.models import AppSendingConfiguration

pytestmark = pytest.mark.django_db

logger = logging.getLogger(__name__)


@mock.patch("app.services.email_service.EmailService.update_email_usage")
@mock.patch("app.tasks.get_provider_client")
@mock.patch("app.models.AppSendingConfiguration.objects")
def test_send_email_task_success(mock_config_cls, mock_get_client, mock_update_usage):
    mock_config = mock.Mock()
    mock_config.credentials = {"from_email": "test@example.com"}
    mock_config.provider.provider_type = "GENERIC_SMTP"
    mock_config.provider.master_credentials = {}
    mock_config_cls.objects.get.return_value = mock_config
    mock_client = mock.Mock()
    mock_get_client.return_value = mock_client
    mock_client.send_email.return_value = True

    result = tasks.send_email_task(
        app_id="app_1",
        to="to@example.com",
        subject="subject",
        html="<body>html</body>",
        user_id="u_1",
    )
    assert result is True
    assert mock_client.send_email.called
    assert mock_update_usage.called


@mock.patch("app.services.email_service.EmailService.update_email_usage")
@mock.patch("app.models.AppSendingConfiguration")
def test_send_email_task_no_config(mock_config_cls, mock_update_usage):
    mock_config_cls.objects.get.side_effect = AppSendingConfiguration.DoesNotExist
    with pytest.raises(Exception):
        tasks.send_email_task(
            app_id="app_1",
            to="to@example.com",
            subject="subject",
            html="<body>html</body>",
            user_id="u_1",
        )
    assert not mock_update_usage.called


@mock.patch("app.tasks.send_email_task")
def test_send_email_with_credit_check_success(mock_send_email):
    mock_send_email.delay.return_value = None
    tasks.send_email_task.delay(
        app_id="app_1",
        to="to@example.com",
        subject="subject",
        html="<body>html</body>",
        user_id="u_1",
    )
    assert mock_send_email.delay.called


# set_app_provider_task
@mock.patch("app.tasks.AppSendingConfiguration.objects.get")
@mock.patch("app.tasks.switch_app_provider")
def test_set_app_provider_task_success(mock_switch, mock_config):
    result = tasks.set_app_provider_task(app_id="app_1", user_id="u_1", provider_id=1)
    assert result is True
    assert mock_switch.called


@mock.patch("app.tasks.switch_app_provider", side_effect=Exception("fail"))
def test_set_app_provider_task_error(mock_switch):
    with pytest.raises(Exception):
        tasks.set_app_provider_task(app_id="app_1", provider_id=1)
    assert not mock_switch.called


@mock.patch("app.tasks.get_provider_client")
@mock.patch("app.models.AppSendingConfiguration.objects.get")
def test_provision_credentials_for_app_task_success(mock_get, mock_get_client):
    instance_mock = mock.Mock()
    instance_mock.provider.provider_type = "GENERIC_SMTP"
    instance_mock.provider.master_credentials = {}
    mock_get.return_value = instance_mock
    mock_client = mock.Mock()
    mock_get_client.return_value = mock_client
    mock_client.provision_credentials_for_app.return_value = {"username": "user"}
    result = tasks.provision_credentials_for_app_task(
        app_id="app_1", owner_id="u_1", provider_id=1
    )
    assert result is True
    assert instance_mock.save.called


@mock.patch("app.tasks.get_provider_client")
@mock.patch("app.models.AppSendingConfiguration.objects.get")
def test_provision_credentials_for_app_task_error(mock_get, mock_get_client):
    instance_mock = mock.Mock()
    instance_mock.provider.provider_type = "GENERIC_SMTP"
    instance_mock.provider.master_credentials = {}
    mock_get.return_value = instance_mock
    mock_client = mock.Mock()
    mock_get_client.return_value = mock_client
    mock_client.provision_credentials_for_app.side_effect = Exception("fail")
    result = tasks.provision_credentials_for_app_task(
        app_id="app_1", owner_id="u_1", provider_id=1
    )
    assert result is False
    assert instance_mock.save.called
