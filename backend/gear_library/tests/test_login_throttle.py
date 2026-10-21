import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()

LOGIN_URL = "/api/auth/login/"
REGISTER_URL = "/api/auth/register/"
PHONE = "5552234567"
PASSWORD = "correct-horse-battery"
TOO_MANY = {"detail": "Too many attempts. Try again in a minute."}


@pytest.fixture
def user():
    return User.objects.create_user(
        phone_number=PHONE, password=PASSWORD, first_name="Ada", last_name="Lovelace"
    )


def log_in(password, **extra):
    return APIClient().post(
        LOGIN_URL, {"phone_number": PHONE, "password": password}, format="json", **extra
    )


@pytest.mark.django_db
def test_refuses_the_sixth_attempt_in_a_minute_from_one_address(user):
    for _ in range(5):
        assert log_in("wrong").status_code == 400

    response = log_in(PASSWORD)

    assert response.status_code == 429
    assert response.json() == TOO_MANY
    assert 0 < int(response.headers["Retry-After"]) <= 60


@pytest.mark.django_db
def test_counts_successful_attempts_too(user):
    for _ in range(5):
        assert log_in(PASSWORD).status_code == 200

    assert log_in(PASSWORD).status_code == 429


@pytest.mark.django_db
def test_counts_attempts_from_a_logged_in_session(user):
    client = APIClient()
    for _ in range(5):
        client.post(LOGIN_URL, {"phone_number": PHONE, "password": PASSWORD}, format="json")

    response = client.post(LOGIN_URL, {"phone_number": PHONE, "password": PASSWORD}, format="json")

    assert response.status_code == 429


@pytest.mark.django_db
def test_counts_each_address_apart(user):
    for _ in range(5):
        log_in("wrong")

    assert log_in(PASSWORD, REMOTE_ADDR="10.0.0.2").status_code == 200


@pytest.mark.django_db
def test_a_forwarded_for_header_does_not_open_a_new_count(user):
    for _ in range(5):
        log_in("wrong")

    assert log_in(PASSWORD, HTTP_X_FORWARDED_FOR="10.0.0.3").status_code == 429


@pytest.mark.django_db
def test_does_not_limit_register():
    for n in range(6):
        response = APIClient().post(
            REGISTER_URL,
            {
                "phone_number": f"555223{n:04d}",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "password": PASSWORD,
            },
            format="json",
        )
        assert response.status_code == 201
