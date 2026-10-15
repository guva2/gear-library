from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection


@pytest.mark.django_db
def test_connects_to_postgres():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)
    assert connection.vendor == "postgresql"


@pytest.mark.django_db
def test_models_have_no_unmigrated_changes():
    call_command("makemigrations", "--check", "--dry-run", stdout=StringIO())
