"""Races between requests, each on its own database connection.

The first request pauses once it holds the inventory lock, and the second one is sent
when the first is paused there.
"""

import threading

import pytest
from django.db import connection, connections

from gear_library import inventories
from gear_library.models import Inventory, InventoryItem, Item, Membership

from .test_inventory_service import connect, wait_for_a_blocked_lock
from .test_items_api import client_for, list_in, make_inventory, make_user

pytestmark = pytest.mark.django_db(transaction=True)


def send_in_thread(name, send, responses):
    """Runs `send` on its own database connection, recording its response or the error."""

    def target():
        try:
            responses[name] = send()
        except Exception as error:
            responses[name] = error
        finally:
            connections.close_all()

    thread = threading.Thread(target=target, name=name)
    thread.start()
    return thread


@pytest.fixture
def pause_first(monkeypatch):
    """Makes the thread named "first" wait for `release` once it holds the inventory lock.
    Returns (`held`, `release`)."""
    held, release = threading.Event(), threading.Event()
    lock_inventory = inventories.lock_inventory

    def lock_and_pause(inventory_id):
        lock_inventory(inventory_id)
        if threading.current_thread().name == "first":
            held.set()
            assert release.wait(10)

    monkeypatch.setattr(inventories, "lock_inventory", lock_and_pause)
    return held, release


@pytest.fixture
def race(pause_first):
    """Sends `first` until it holds the inventory lock, then `second` until it waits on a
    lock, then lets `first` go on. Returns both status codes."""
    held, release = pause_first

    def run(first, second):
        responses = {}
        threads = [send_in_thread("first", first, responses)]
        assert held.wait(10)
        threads.append(send_in_thread("second", second, responses))
        try:
            wait_for_a_blocked_lock()
        finally:
            release.set()
            for thread in threads:
                thread.join(10)
        return responses["first"], responses["second"]

    return run


def url(inventory, suffix=""):
    return f"/api/inventories/{inventory.id}/{suffix}"


def set_role(by, inventory, user, role):
    client = client_for(by)
    members_url = url(inventory, f"members/{user.id}/")
    return lambda: client.patch(members_url, {"role": role}, format="json")


def remove(by, inventory, user):
    client = client_for(by)
    return lambda: client.delete(url(inventory, f"members/{user.id}/"))


def owner_count(inventory):
    return Membership.objects.filter(inventory=inventory, role="owner").count()


@pytest.mark.parametrize(
    "first_change, second_change",
    [("step down", "step down"), ("leave", "step down"), ("step down", "leave")],
)
def test_two_owners_giving_up_ownership_at_once_leave_one_owner(
    race, first_change, second_change
):
    first, second = make_user(1), make_user(2)
    inventory = make_inventory("Climbing", [(first, "owner"), (second, "owner")])

    def give_up(change, user):
        if change == "leave":
            return remove(user, inventory, user)
        return set_role(user, inventory, user, "member")

    one, two = race(give_up(first_change, first), give_up(second_change, second))

    assert one.status_code in (200, 204)
    assert two.status_code == 409
    assert owner_count(inventory) == 1
    assert Membership.objects.get(user=second).role == "owner"


@pytest.mark.parametrize("change", ["promote", "remove"])
def test_a_delete_waits_for_a_member_change_and_then_deletes(race, change):
    owner, member = make_user(1), make_user(2)
    inventory = make_inventory("Climbing", [(owner, "owner"), (member, "member")])
    first = (
        set_role(owner, inventory, member, "admin")
        if change == "promote"
        else remove(owner, inventory, member)
    )
    client = client_for(owner)

    one, two = race(first, lambda: client.delete(url(inventory)))

    assert one.status_code in (200, 204)
    assert two.status_code == 204
    assert not Inventory.objects.exists()
    assert not Membership.objects.exists()


def invite(by, inventory, invitee):
    client = client_for(by)
    invites_url = url(inventory, "invites/")
    return lambda: client.post(invites_url, {"user_id": invitee.id}, format="json")


def test_an_invite_waits_for_a_delete_and_is_not_found(race):
    owner, invitee = make_user(1), make_user(2)
    connect(owner, invitee)
    inventory = make_inventory("Climbing", [(owner, "owner")])
    client = client_for(owner)

    one, two = race(lambda: client.delete(url(inventory)), invite(owner, inventory, invitee))

    assert one.status_code == 204
    assert (two.status_code, two.json()) == (404, {"detail": "Inventory not found."})
    assert not Membership.objects.exists()


def test_a_delete_after_an_invite_commits_deletes_the_invite():
    owner, invitee = make_user(1), make_user(2)
    connect(owner, invitee)
    inventory = make_inventory("Climbing", [(owner, "owner")])
    responses = {}

    def invite_before_the_lock(execute, sql, params, many, context):
        if sql.startswith(SELECT_INVENTORY) and sql.endswith(FOR_UPDATE) and not responses:
            send_in_thread("invite", invite(owner, inventory, invitee), responses).join(10)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(invite_before_the_lock):
        response = client_for(owner).delete(url(inventory))

    assert responses["invite"].status_code == 201
    assert response.status_code == 204
    assert not Membership.objects.exists()


def test_an_admin_demoted_while_inviting_waits_and_is_forbidden(race):
    owner, admin, invitee = make_user(1), make_user(2), make_user(3)
    connect(admin, invitee)
    inventory = make_inventory("Climbing", [(owner, "owner"), (admin, "admin")])

    one, two = race(
        set_role(owner, inventory, admin, "member"), invite(admin, inventory, invitee)
    )

    assert one.status_code == 200
    assert (two.status_code, two.json()) == (
        403,
        {"detail": "Only admins and owners can do this."},
    )
    assert not Membership.objects.pending().exists()


def test_an_owner_demoted_while_renaming_waits_and_is_forbidden(race):
    owner, other = make_user(1), make_user(2)
    inventory = make_inventory("Climbing", [(owner, "owner"), (other, "owner")])
    client = client_for(owner)

    one, two = race(
        set_role(other, inventory, owner, "admin"),
        lambda: client.patch(url(inventory), {"name": "Bouldering"}, format="json"),
    )

    assert one.status_code == 200
    assert (two.status_code, two.json()) == (403, {"detail": "Only owners can do this."})
    assert Inventory.objects.get().name == "Climbing"


def test_a_listing_waits_for_the_lister_taking_the_member_role_and_is_refused(race):
    """Without the inventory lock, the listing could commit after the role change had
    removed the lister's listings, and outlive the role it needs."""
    owner, admin = make_user(1), make_user(2)
    inventory = make_inventory("Climbing", [(owner, "owner"), (admin, "admin")])
    tent = Item.objects.create(owner=admin, name="Tent")
    client = client_for(admin)

    one, two = race(
        set_role(owner, inventory, admin, "member"),
        lambda: client.post(url(inventory, "items/"), {"item_id": tent.id}, format="json"),
    )

    assert one.status_code == 200
    assert two.status_code == 403
    assert not InventoryItem.objects.exists()


def test_a_request_waits_for_the_listing_removal_and_is_not_found(race):
    """Without the inventory lock, the request could commit after the listing was
    removed, and leave a request through an inventory the item is not listed in."""
    owner, member = make_user(1), make_user(2)
    inventory = make_inventory("Climbing", [(owner, "owner"), (member, "member")])
    rope = Item.objects.create(owner=owner, name="Rope")
    list_in(inventory, rope)
    unlister, borrower = client_for(owner), client_for(member)

    one, two = race(
        lambda: unlister.delete(url(inventory, f"items/{rope.id}/")),
        lambda: borrower.post(url(inventory, f"items/{rope.id}/borrow/")),
    )

    assert one.status_code == 204
    assert (two.status_code, two.json()) == (
        404,
        {"detail": "This item is not listed in this inventory."},
    )
    rope.refresh_from_db()
    assert rope.loan_status == "available"


SELECT_INVENTORY = 'SELECT "gear_library_inventory".'
SELECT_ITEM = 'SELECT "gear_library_item".'
DELETE_LISTING = 'DELETE FROM "gear_library_inventoryitem" '
FOR_UPDATE = " FOR UPDATE"


def test_an_item_delete_request_starts_again_after_a_listing_it_had_not_locked():
    """The listing commits after the delete read the item's listings and before it locked
    the item. The delete rolls back to before its locks and locks that inventory too."""
    owner = make_user(1)
    climbing = make_inventory("Climbing", [(owner, "owner")])
    camping = make_inventory("Camping", [(owner, "owner")])
    rope = Item.objects.create(owner=owner, name="Rope")
    list_in(climbing, rope)
    statements, responses = [], {}
    lister = client_for(owner)

    def list_it_first(execute, sql, params, many, context):
        if sql.startswith(SELECT_ITEM) and sql.endswith(FOR_UPDATE) and not responses:
            body = {"item_id": rope.id}
            send = lambda: lister.post(url(camping, "items/"), body, format="json")
            send_in_thread("lister", send, responses).join(10)
        statements.append((sql, params))
        return execute(sql, params, many, context)

    with connection.execute_wrapper(list_it_first):
        response = client_for(owner).delete(f"/api/items/{rope.id}/")

    assert responses["lister"].status_code == 201
    assert response.status_code == 204
    assert not Item.objects.exists()
    assert not InventoryItem.objects.exists()
    first_listing_delete = next(
        i for i, (sql, _) in enumerate(statements) if sql.startswith(DELETE_LISTING)
    )
    inventory_locks = [
        params
        for sql, params in statements[:first_listing_delete]
        if sql.startswith(SELECT_INVENTORY) and sql.endswith(FOR_UPDATE)
    ]
    assert any(camping.id in params for params in inventory_locks)
