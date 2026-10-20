from io import StringIO

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command

from gear_library.models import Connection, Inventory, Membership, ordered_pair

User = get_user_model()

DEMO_PASSWORD = "gear-library-demo"


def seed():
    call_command("seed_demo", stdout=StringIO())


def snapshot():
    return {
        "users": {
            u.pk: (u.phone_number, u.password, u.first_name, u.last_name)
            for u in User.objects.all()
        },
        "inventories": set(Inventory.objects.values_list("pk", "name")),
        "memberships": set(
            Membership.objects.values_list(
                "pk", "inventory", "user", "role", "status", "invited_by"
            )
        ),
        "connections": set(
            Connection.objects.values_list(
                "pk", "first_user", "second_user", "requested_by", "status"
            )
        ),
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


@pytest.mark.django_db
def test_creates_two_inventories_using_every_role_and_one_pending_invite():
    seed()

    inventories = list(Inventory.objects.all())
    assert len(inventories) == 2
    active = Membership.objects.active()
    assert set(active.values_list("role", flat=True)) == {"member", "admin", "owner"}
    for inventory in inventories:
        assert active.filter(inventory=inventory, role="owner").exists()
    invite = Membership.objects.pending().get()
    assert invite.role == "member"
    inviter = active.get(inventory=invite.inventory, user=invite.invited_by)
    assert inviter.role in ("admin", "owner")


@pytest.mark.django_db
def test_every_demo_user_belongs_to_an_inventory():
    seed()

    for user in User.objects.all():
        assert user.memberships.active().exists()


@pytest.mark.django_db
def test_leaves_a_changed_demo_inventory_alone():
    seed()
    membership = Membership.objects.filter(role="member").first()
    membership.role = "admin"
    membership.save()
    Membership.objects.pending().delete()

    seed()

    membership.refresh_from_db()
    assert membership.role == "admin"
    assert Inventory.objects.count() == 2
    assert not Membership.objects.pending().exists()


@pytest.mark.django_db
def test_does_not_touch_an_inventory_with_a_demo_name_that_is_not_the_demo_one():
    seed()
    demo_names = set(Inventory.objects.values_list("name", flat=True))
    Inventory.objects.all().delete()
    stranger = User.objects.create_user(
        phone_number="5551239999", first_name="Real", last_name="Person"
    )
    for name in demo_names:
        real = Inventory.objects.create(name=name)
        Membership.objects.create(inventory=real, user=stranger, role="owner", status="active")

    seed()

    for name in demo_names:
        assert Inventory.objects.filter(name=name).count() == 2
    roles = Membership.objects.filter(user=stranger).values_list("role", flat=True)
    assert list(roles) == ["owner"] * len(demo_names)


def demo_users():
    return list(User.objects.order_by("phone_number"))


@pytest.mark.django_db
def test_connects_the_demo_users_and_leaves_one_request_pending():
    seed()

    avery, jordan, sam = demo_users()
    assert Connection.objects.between(avery, jordan).get().status == "accepted"
    assert Connection.objects.between(jordan, sam).get().status == "accepted"
    pending = Connection.objects.pending().get()
    assert (pending.requested_by, pending.other_user(sam)) == (sam, avery)


@pytest.mark.django_db
def test_leaves_a_changed_demo_connection_alone():
    seed()
    Connection.objects.pending().update(status="accepted")

    seed()

    assert not Connection.objects.pending().exists()
    assert Connection.objects.count() == 3


@pytest.mark.django_db
def test_leaves_a_real_users_connection_to_a_demo_user_alone():
    seed()
    avery = demo_users()[0]
    stranger = User.objects.create_user(
        phone_number="5551239999", first_name="Real", last_name="Person"
    )
    first, second = ordered_pair(avery, stranger)
    real = Connection.objects.create(
        first_user_id=first, second_user_id=second, requested_by=stranger, status="pending"
    )

    seed()

    assert Connection.objects.filter(pk=real.pk, status="pending").exists()
    assert Connection.objects.count() == 4
