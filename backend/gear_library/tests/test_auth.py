import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()

CSRF_URL = "/api/auth/csrf/"
REGISTER_URL = "/api/auth/register/"
LOGIN_URL = "/api/auth/login/"
LOGOUT_URL = "/api/auth/logout/"
ME_URL = "/api/auth/me/"

PHONE = "5551234567"
PASSWORD = "correct-horse-battery"
REGISTRATION = {
    "phone_number": "(555) 123-4567",
    "first_name": "Ada",
    "last_name": "Lovelace",
    "password": PASSWORD,
}
WRONG_CREDENTIALS = {"non_field_errors": ["Wrong phone number or password."]}


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def csrf_client():
    return APIClient(enforce_csrf_checks=True)


@pytest.fixture
def user():
    return User.objects.create_user(
        phone_number=PHONE, password=PASSWORD, first_name="Ada", last_name="Lovelace"
    )


def csrf_token(client):
    response = client.get(CSRF_URL)
    return response.cookies["csrftoken"].value


def me_payload(user):
    return {
        "id": user.id,
        "phone_number": user.phone_number,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }


@pytest.mark.django_db
class TestCsrf:
    def test_sets_the_csrf_cookie_for_anonymous_callers(self, csrf_client):
        response = csrf_client.get(CSRF_URL)

        assert response.status_code == 204
        assert response.cookies["csrftoken"].value


@pytest.mark.django_db
class TestRegister:
    def test_creates_the_user_and_logs_them_in(self, client):
        response = client.post(REGISTER_URL, REGISTRATION, format="json")

        assert response.status_code == 201
        user = User.objects.get()
        assert response.json() == me_payload(user)
        assert user.phone_number == PHONE
        assert (user.first_name, user.last_name) == ("Ada", "Lovelace")
        assert user.check_password(PASSWORD)
        assert client.get(ME_URL).json() == me_payload(user)

    @pytest.mark.parametrize("phone", ["", "555-1234", "+2 555 123 4567", "555123456a"])
    def test_rejects_an_invalid_phone_number(self, client, phone):
        response = client.post(
            REGISTER_URL, {**REGISTRATION, "phone_number": phone}, format="json"
        )

        assert response.status_code == 400
        assert list(response.json()) == ["phone_number"]
        assert not User.objects.exists()

    def test_requires_every_field(self, client):
        response = client.post(REGISTER_URL, {}, format="json")

        assert response.status_code == 400
        assert set(response.json()) == {"phone_number", "first_name", "last_name", "password"}

    @pytest.mark.parametrize("field", ["first_name", "last_name"])
    @pytest.mark.parametrize("value", ["", "   ", "x" * 33])
    def test_rejects_a_blank_or_long_name(self, client, field, value):
        response = client.post(REGISTER_URL, {**REGISTRATION, field: value}, format="json")

        assert response.status_code == 400
        assert list(response.json()) == [field]

    @pytest.mark.parametrize(
        "password, message",
        [
            ("short1", "too short"),
            ("password123", "too common"),
            ("8302917465", "entirely numeric"),
            ("lovelace99", "too similar"),
        ],
    )
    def test_rejects_a_weak_password(self, client, password, message):
        response = client.post(
            REGISTER_URL, {**REGISTRATION, "password": password}, format="json"
        )

        assert response.status_code == 400
        assert list(response.json()) == ["password"]
        assert any(message in error for error in response.json()["password"])
        assert not User.objects.exists()

    def test_rejects_a_duplicate_phone_number(self, client, user):
        response = client.post(
            REGISTER_URL, {**REGISTRATION, "phone_number": "+1 555.123.4567"}, format="json"
        )

        assert response.status_code == 400
        assert response.json() == {
            "phone_number": ["A user with this phone number already exists."]
        }
        assert User.objects.count() == 1

    def test_duplicate_that_passes_validation_hits_the_unique_index(
        self, client, user, monkeypatch
    ):
        # Two signups for one number can both pass full_clean before either inserts.
        monkeypatch.setattr(User, "validate_unique", lambda self, exclude=None: None)

        response = client.post(REGISTER_URL, REGISTRATION, format="json")

        assert response.status_code == 400
        assert response.json() == {
            "phone_number": ["A user with this phone number already exists."]
        }
        assert User.objects.count() == 1

    def test_refuses_a_logged_in_caller(self, client, user):
        client.force_login(user)

        response = client.post(
            REGISTER_URL, {**REGISTRATION, "phone_number": "5559876543"}, format="json"
        )

        assert response.status_code == 403
        assert User.objects.count() == 1

    def test_refuses_an_anonymous_request_without_the_csrf_token(self, csrf_client):
        csrf_token(csrf_client)

        response = csrf_client.post(REGISTER_URL, REGISTRATION, format="json")

        assert response.status_code == 403
        assert not User.objects.exists()

    def test_accepts_an_anonymous_request_with_the_csrf_token(self, csrf_client):
        token = csrf_token(csrf_client)

        response = csrf_client.post(
            REGISTER_URL, REGISTRATION, format="json", HTTP_X_CSRFTOKEN=token
        )

        assert response.status_code == 201


@pytest.mark.django_db
class TestLogin:
    def test_logs_the_user_in(self, client, user):
        response = client.post(
            LOGIN_URL, {"phone_number": PHONE, "password": PASSWORD}, format="json"
        )

        assert response.status_code == 200
        assert response.json() == me_payload(user)
        assert client.get(ME_URL).json() == me_payload(user)

    def test_accepts_a_formatted_phone_number(self, client, user):
        response = client.post(
            LOGIN_URL, {"phone_number": "+1 (555) 123-4567", "password": PASSWORD}, format="json"
        )

        assert response.status_code == 200

    @pytest.mark.parametrize(
        "credentials",
        [
            {"phone_number": PHONE, "password": "wrong-password"},
            {"phone_number": "5559876543", "password": PASSWORD},
        ],
    )
    def test_wrong_phone_or_password_get_one_message(self, client, user, credentials):
        response = client.post(LOGIN_URL, credentials, format="json")

        assert response.status_code == 400
        assert response.json() == WRONG_CREDENTIALS
        assert client.get(ME_URL).status_code == 403

    def test_inactive_user_gets_the_same_message(self, client, user):
        user.is_active = False
        user.save()

        response = client.post(
            LOGIN_URL, {"phone_number": PHONE, "password": PASSWORD}, format="json"
        )

        assert response.status_code == 400
        assert response.json() == WRONG_CREDENTIALS

    def test_rejects_a_malformed_phone_number_on_its_field(self, client, user):
        response = client.post(
            LOGIN_URL, {"phone_number": "555-1234", "password": PASSWORD}, format="json"
        )

        assert response.status_code == 400
        assert list(response.json()) == ["phone_number"]

    def test_requires_both_fields(self, client):
        response = client.post(LOGIN_URL, {}, format="json")

        assert response.status_code == 400
        assert set(response.json()) == {"phone_number", "password"}

    def test_refuses_an_anonymous_request_without_the_csrf_token(self, csrf_client, user):
        csrf_token(csrf_client)

        response = csrf_client.post(
            LOGIN_URL, {"phone_number": PHONE, "password": PASSWORD}, format="json"
        )

        assert response.status_code == 403
        assert csrf_client.get(ME_URL).status_code == 403

    def test_accepts_an_anonymous_request_with_the_csrf_token(self, csrf_client, user):
        token = csrf_token(csrf_client)

        response = csrf_client.post(
            LOGIN_URL,
            {"phone_number": PHONE, "password": PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )

        assert response.status_code == 200
        # Django rotates the token at login, so clients must read the cookie again.
        assert response.cookies["csrftoken"].value != token


@pytest.mark.django_db
class TestLogout:
    def test_logs_the_user_out(self, client, user):
        client.force_login(user)

        response = client.post(LOGOUT_URL)

        assert response.status_code == 204
        assert client.get(ME_URL).status_code == 403

    def test_refuses_an_anonymous_caller(self, client):
        assert client.post(LOGOUT_URL).status_code == 403

    def test_refuses_a_request_without_the_csrf_token(self, csrf_client, user):
        csrf_client.force_login(user)
        csrf_token(csrf_client)

        response = csrf_client.post(LOGOUT_URL)

        assert response.status_code == 403
        assert csrf_client.get(ME_URL).status_code == 200

    def test_accepts_a_request_with_the_csrf_token(self, csrf_client, user):
        csrf_client.force_login(user)
        token = csrf_token(csrf_client)

        response = csrf_client.post(LOGOUT_URL, HTTP_X_CSRFTOKEN=token)

        assert response.status_code == 204
        assert csrf_client.get(ME_URL).status_code == 403


@pytest.mark.django_db
class TestMe:
    def test_returns_the_current_user(self, client, user):
        client.force_login(user)

        response = client.get(ME_URL)

        assert response.status_code == 200
        assert response.json() == me_payload(user)

    def test_refuses_an_anonymous_caller(self, client):
        assert client.get(ME_URL).status_code == 403
