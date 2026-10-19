import pytest
from django.db import OperationalError

URL = "/api/health/"


class UnreachableConnection:
    def cursor(self):
        raise OperationalError("connection refused")


@pytest.mark.django_db
def test_reports_ok_when_database_answers(client):
    response = client.get(URL)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


# No django_db mark: any database access outside the patched connection fails the test.
def test_reports_unavailable_when_query_fails(client, monkeypatch):
    monkeypatch.setattr("gear_library.views.connection", UnreachableConnection())

    response = client.get(URL)

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unavailable"}
