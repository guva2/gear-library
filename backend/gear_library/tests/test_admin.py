import pytest
from django.contrib.auth import get_user_model
from django.test import Client

User = get_user_model()

NAMES = {"first_name": "Ada", "last_name": "Lovelace"}


@pytest.fixture
def admin_client():
    superuser = User.objects.create_superuser(
        phone_number="5559876543", password="s3cret-pass", **NAMES
    )
    client = Client()
    client.force_login(superuser)
    return client


@pytest.mark.django_db
def test_lists_users_by_phone_number_and_name(admin_client):
    User.objects.create_user(phone_number="5552345678", first_name="Grace", last_name="Hopper")

    response = admin_client.get("/admin/gear_library/user/")

    assert response.status_code == 200
    page = response.content.decode()
    assert "5552345678" in page
    assert "Hopper" in page


@pytest.mark.django_db
def test_searches_users_by_phone_number(admin_client):
    User.objects.create_user(phone_number="5552345678", first_name="Grace", last_name="Hopper")

    response = admin_client.get("/admin/gear_library/user/", {"q": "2345678"})

    assert response.status_code == 200
    assert "Hopper" in response.content.decode()
    assert "Lovelace" not in response.content.decode()


@pytest.mark.django_db
def test_shows_a_users_change_page(admin_client):
    user = User.objects.create_user(
        phone_number="5552345678", first_name="Grace", last_name="Hopper"
    )

    response = admin_client.get(f"/admin/gear_library/user/{user.pk}/change/")

    assert response.status_code == 200
    assert 'name="phone_number"' in response.content.decode()


@pytest.mark.django_db
def test_changes_a_users_name(admin_client):
    user = User.objects.create_user(
        phone_number="5552345678", first_name="Grace", last_name="Hopper"
    )

    response = admin_client.post(
        f"/admin/gear_library/user/{user.pk}/change/",
        {
            "phone_number": "5552345678",
            "first_name": "Grace",
            "last_name": "Brewster",
            "is_active": "on",
            "last_login_0": "",
            "last_login_1": "",
        },
    )

    assert response.status_code == 302, response.content.decode()
    user.refresh_from_db()
    assert user.last_name == "Brewster"


@pytest.mark.django_db
def test_adds_a_user_with_a_phone_number_and_password(admin_client):
    response = admin_client.post(
        "/admin/gear_library/user/add/",
        {
            "phone_number": "5552345678",
            "first_name": "Grace",
            "last_name": "Hopper",
            "usable_password": "true",
            "password1": "correct-horse-battery",
            "password2": "correct-horse-battery",
        },
    )

    assert response.status_code == 302, response.content.decode()
    user = User.objects.get(phone_number="5552345678")
    assert (user.first_name, user.last_name) == ("Grace", "Hopper")
    assert user.check_password("correct-horse-battery")
