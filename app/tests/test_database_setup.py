import pytest
from django.core.management import call_command


@pytest.fixture(autouse=True)
async def setup_test_database(django_db_setup, django_db_blocker):
    """Set up a fresh test database for each test."""
    with django_db_blocker.unblock():
        call_command("migrate")
        yield
