from io import StringIO

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command

User = get_user_model()

DEMO_PASSWORD = "gear-library-demo"


def seed():
    call_command("seed_demo", stdout=StringIO())


def snapshot():
    return {
        u.pk: (u.phone_number, u.password, u.first_name, u.last_name)
        for u in User.objects.all()
    }


@pytest.mark.django_db
def test_creates_demo_users_who_can_log_in():
    seed()

    users = list(User.objects.all())
    assert len(users) >= 3
    for user in users:
        assert user.first_name and user.last_name
        assert not user.is_staff
        assert authenticate(phone_number=user.phone_number, password=DEMO_PASSWORD) == user


@pytest.mark.django_db
def test_running_twice_changes_nothing():
    seed()
    before = snapshot()

    seed()

    assert snapshot() == before


@pytest.mark.django_db
def test_leaves_an_existing_user_with_a_demo_number_alone():
    seed()
    user = User.objects.order_by("pk").first()
    user.first_name = "Changed"
    user.set_password("another-password")
    user.save()

    seed()

    user.refresh_from_db()
    assert user.first_name == "Changed"
    assert user.check_password("another-password")
