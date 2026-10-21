from io import StringIO

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient

from gear_library.models import (
    Connection,
    Inventory,
    InventoryItem,
    Item,
    Membership,
    ordered_pair,
)

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
        "items": set(
            Item.objects.values_list(
                "pk",
                "owner",
                "name",
                "description",
                "loan_status",
                "borrower",
                "loan_inventory",
            )
        ),
        "listings": set(InventoryItem.objects.values_list("pk", "inventory", "item")),
    }


@pytest.mark.django_db
def test_creates_demo_users_who_can_log_in():
    seed()

    users = list(User.objects.all())
    assert sorted(u.first_name for u in users) == ["Avery", "Jordan", "Riley", "Sam"]
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
def test_creates_three_inventories_using_every_role_and_one_pending_invite():
    seed()

    inventories = list(Inventory.objects.all())
    assert len(inventories) == 3
    active = Membership.objects.active()
    assert set(active.values_list("role", flat=True)) == {"member", "admin", "owner"}
    for inventory in inventories:
        assert active.filter(inventory=inventory, role="owner").exists()
    invite = Membership.objects.pending().get()
    assert invite.role == "member"
    inviter = active.get(inventory=invite.inventory, user=invite.invited_by)
    assert inviter.role in ("admin", "owner")


@pytest.mark.django_db
def test_every_demo_user_but_riley_belongs_to_an_inventory():
    seed()

    for user in User.objects.all():
        has_inventory = user.memberships.active().exists()
        assert has_inventory == (user.first_name != "Riley"), user.first_name
    assert not Membership.objects.filter(user__first_name="Riley").exists()


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
    assert Inventory.objects.count() == 3
    assert not Membership.objects.pending().exists()


@pytest.mark.django_db
def test_does_not_touch_an_inventory_with_a_demo_name_that_is_not_the_demo_one():
    seed()
    demo_names = set(Inventory.objects.values_list("name", flat=True))
    Item.objects.end_loan()
    Inventory.objects.all().delete()
    stranger = User.objects.create_user(
        phone_number="5552239999", first_name="Real", last_name="Person"
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
def test_connects_every_pair_of_avery_jordan_and_sam_and_riley_has_asked_avery():
    seed()

    avery, jordan, sam, riley = demo_users()
    assert Connection.objects.between(avery, jordan).get().status == "accepted"
    assert Connection.objects.between(jordan, sam).get().status == "accepted"
    assert Connection.objects.between(sam, avery).get().status == "accepted"
    pending = Connection.objects.pending().get()
    assert (pending.requested_by, pending.other_user(riley)) == (riley, avery)
    assert Connection.objects.count() == 4


@pytest.mark.django_db
def test_every_membership_with_an_inviter_is_between_connected_users():
    seed()

    invited = Membership.objects.exclude(invited_by=None)
    assert invited.filter(status="pending").exists()
    assert invited.filter(status="active").exists()
    for membership in invited:
        pair = Connection.objects.accepted().between(membership.user, membership.invited_by)
        assert pair.exists(), (membership.user.first_name, membership.inventory.name)


@pytest.mark.django_db
def test_leaves_a_changed_demo_connection_alone():
    seed()
    Connection.objects.pending().update(status="accepted")

    seed()

    assert not Connection.objects.pending().exists()
    assert Connection.objects.count() == 4


@pytest.mark.django_db
def test_leaves_a_real_users_connection_to_a_demo_user_alone():
    seed()
    avery = demo_users()[0]
    stranger = User.objects.create_user(
        phone_number="5552239999", first_name="Real", last_name="Person"
    )
    first, second = ordered_pair(avery, stranger)
    real = Connection.objects.create(
        first_user_id=first, second_user_id=second, requested_by=stranger, status="pending"
    )

    seed()

    assert Connection.objects.filter(pk=real.pk, status="pending").exists()
    assert Connection.objects.count() == 5


@pytest.mark.django_db
def test_gives_every_demo_user_but_riley_items_and_lists_some_in_every_shared_inventory():
    seed()

    for user in User.objects.all():
        assert user.items.exists() == (user.first_name != "Riley"), user.first_name
    for inventory in Inventory.objects.all():
        shared = inventory.memberships.active().count() > 1
        assert inventory.listings.exists() == shared, inventory.name
    listing_counts = [item.listings.count() for item in Item.objects.all()]
    assert 0 in listing_counts
    assert max(listing_counts) > 1


@pytest.mark.django_db
def test_every_listing_is_by_an_admin_or_owner_of_its_inventory():
    seed()

    for listing in InventoryItem.objects.select_related("item"):
        lister = Membership.objects.active().get(
            inventory=listing.inventory_id, user=listing.item.owner_id
        )
        assert lister.role in ("admin", "owner")


@pytest.mark.django_db
def test_leaves_changed_demo_items_and_listings_alone():
    seed()
    item = Item.objects.filter(listings__isnull=False).first()
    item.description = "Changed"
    item.save()
    item.listings.all().delete()

    seed()

    item.refresh_from_db()
    assert item.description == "Changed"
    assert not item.listings.exists()
    assert Item.objects.filter(owner=item.owner, name=item.name).count() == 1


@pytest.mark.django_db
def test_lists_a_new_demo_item_only_where_its_owner_is_still_an_admin_or_owner():
    seed()
    Membership.objects.filter(role="admin").update(role="member")
    InventoryItem.objects.all().delete()
    Item.objects.all().delete()

    seed()

    assert Item.objects.exists()
    assert InventoryItem.objects.exists()
    for listing in InventoryItem.objects.select_related("item"):
        lister = Membership.objects.get(
            inventory=listing.inventory_id, user=listing.item.owner_id
        )
        assert lister.role == "owner"


@pytest.mark.django_db
def test_leaves_one_request_pending_and_one_item_on_loan_through_inventories_of_the_borrower():
    seed()

    for status in ("requested", "on_loan"):
        item = Item.objects.get(loan_status=status)
        assert item.borrower != item.owner
        assert item.listings.filter(inventory=item.loan_inventory).exists()
        assert Membership.objects.active().filter(
            inventory=item.loan_inventory, user=item.borrower
        ).exists()


@pytest.mark.django_db
def test_leaves_a_changed_demo_loan_alone():
    seed()
    Item.objects.end_loan()

    seed()

    assert set(Item.objects.values_list("loan_status", flat=True)) == {"available"}


@pytest.mark.django_db
def test_lends_a_new_demo_item_only_while_the_borrower_is_a_member_where_it_is_listed():
    seed()
    Item.objects.all().delete()
    Membership.objects.filter(role="member").delete()
    Membership.objects.filter(role="admin").update(role="member")

    seed()

    assert not Item.objects.filter(loan_status="requested").exists()
    assert Item.objects.filter(loan_status="on_loan").count() == 1
    for item in Item.objects.exclude(loan_status="available"):
        assert item.listings.filter(inventory=item.loan_inventory).exists()
        assert Membership.objects.active().filter(
            inventory=item.loan_inventory, user=item.borrower
        ).exists()


@pytest.mark.django_db
def test_every_demo_user_but_riley_has_a_loan_to_see():
    seed()

    for user in User.objects.all():
        client = APIClient()
        client.force_authenticate(user)
        loans = client.get("/api/lending/").json() + client.get("/api/borrowing/").json()
        assert bool(loans) == (user.first_name != "Riley"), user.first_name


@pytest.mark.django_db
def test_avery_and_sam_have_something_to_discover_and_jordan_and_riley_have_nothing():
    seed()

    for user in User.objects.all():
        client = APIClient()
        client.force_authenticate(user)
        found = client.get("/api/discover/").json()
        assert bool(found) == (user.first_name in ("Avery", "Sam")), user.first_name


@pytest.mark.django_db
def test_avery_joined_camping_crew_through_an_invite_from_sam():
    seed()

    membership = Membership.objects.active().get(
        inventory__name="Camping Crew", user__first_name="Avery"
    )
    assert membership.invited_by.first_name == "Sam"


@pytest.mark.django_db
def test_every_active_member_but_the_owner_has_an_admin_or_owner_as_inviter():
    seed()

    for membership in Membership.objects.active().exclude(role="owner"):
        assert membership.invited_by is not None, membership.user.first_name
        inviter = Membership.objects.active().get(
            inventory=membership.inventory, user=membership.invited_by
        )
        assert inviter.role in ("admin", "owner")
    for owner in Membership.objects.filter(role="owner"):
        assert owner.invited_by is None
