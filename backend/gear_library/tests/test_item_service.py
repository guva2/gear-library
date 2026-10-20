import threading

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from rest_framework.exceptions import NotFound, ValidationError

from gear_library import inventories, items
from gear_library.errors import Conflict
from gear_library.models import InventoryItem, Item, Membership

from .test_inventory_service import as_, hold_after, run_in_thread, wait_for_a_blocked_lock

User = get_user_model()


def make_user(n, first_name="User"):
    return User.objects.create_user(
        phone_number=f"555123{n:04d}", first_name=first_name, last_name=str(n)
    )


@pytest.fixture
def owner():
    return make_user(1, "Olive")


@pytest.fixture
def inventory(owner):
    return inventories.create_inventory(owner, "Climbing").inventory


def join(inventory, role, n):
    user = make_user(n)
    Membership.objects.create(inventory=inventory, user=user, role=role, status="active")
    return user


def listed(inventory):
    return set(InventoryItem.objects.filter(inventory=inventory).values_list("item", flat=True))


def list_directly(inventory, item):
    return InventoryItem.objects.create(inventory=inventory, item=item)


NOT_YOURS = {"item_id": ["You can list only your own items."]}


@pytest.mark.django_db
class TestItems:
    def test_creating_makes_the_caller_its_owner(self, owner):
        item = items.create_item(owner, {"name": "Rope", "description": "60 m"})

        assert (item.owner, item.name, item.description) == (owner, "Rope", "60 m")

    def test_the_owner_edits_their_item(self, owner):
        item = items.create_item(owner, {"name": "Rope"})

        items.update_item(owner, item.id, {"description": "60 m"})

        item.refresh_from_db()
        assert (item.name, item.description) == ("Rope", "60 m")

    def test_an_edit_with_no_fields_changes_nothing(self, owner):
        item = items.create_item(owner, {"name": "Rope"})

        items.update_item(owner, item.id, {})

        assert Item.objects.get().name == "Rope"

    @pytest.mark.parametrize("fields", [{"name": "Mine now"}, {}])
    def test_editing_someone_elses_item_is_not_found(self, owner, fields):
        item = items.create_item(owner, {"name": "Rope"})

        with pytest.raises(NotFound):
            items.update_item(make_user(2), item.id, fields)
        assert Item.objects.get().name == "Rope"

    def test_editing_a_missing_item_is_not_found(self, owner):
        with pytest.raises(NotFound):
            items.update_item(owner, 999999, {"name": "Rope"})

    def test_the_owner_deletes_their_item_and_its_listings(self, owner, inventory):
        item = items.create_item(owner, {"name": "Rope"})
        list_directly(inventory, item)

        items.delete_item(owner, item.id)

        assert not Item.objects.exists()
        assert not InventoryItem.objects.exists()

    @pytest.mark.parametrize("who", ["someone else", "missing"])
    def test_deleting_someone_elses_or_a_missing_item_is_not_found(self, owner, who):
        item = items.create_item(owner, {"name": "Rope"})
        user, item_id = (make_user(2), item.id) if who == "someone else" else (owner, 999999)

        with pytest.raises(NotFound):
            items.delete_item(user, item_id)
        assert Item.objects.exists()


@pytest.mark.django_db
class TestAddListing:
    @pytest.mark.parametrize("role", ["admin", "owner"])
    def test_admins_and_owners_list_their_own_items(self, inventory, role):
        user = join(inventory, role, 2)
        item = items.create_item(user, {"name": "Rope"})

        listing = items.add_listing(as_(user, inventory), item.id)

        assert (listing.inventory_id, listing.item) == (inventory.id, item)
        assert listed(inventory) == {item.id}

    @pytest.mark.parametrize("who", ["another member", "a stranger", "missing"])
    def test_an_item_that_is_not_the_callers_is_invalid_with_one_message(
        self, inventory, owner, who
    ):
        other = join(inventory, "admin", 2) if who == "another member" else make_user(2)
        item = items.create_item(other, {"name": "Rope"})
        item_id = 999999 if who == "missing" else item.id

        with pytest.raises(ValidationError) as excinfo:
            items.add_listing(as_(owner, inventory), item_id)
        assert excinfo.value.detail == NOT_YOURS
        assert not InventoryItem.objects.exists()

    def test_listing_an_item_twice_conflicts(self, inventory, owner):
        item = items.create_item(owner, {"name": "Rope"})
        items.add_listing(as_(owner, inventory), item.id)

        with pytest.raises(Conflict):
            items.add_listing(as_(owner, inventory), item.id)
        assert InventoryItem.objects.count() == 1

    def test_an_item_is_listed_in_several_inventories(self, inventory, owner):
        other = inventories.create_inventory(owner, "Camping").inventory
        item = items.create_item(owner, {"name": "Rope"})

        items.add_listing(as_(owner, inventory), item.id)
        items.add_listing(as_(owner, other), item.id)

        assert item.listings.count() == 2


@pytest.mark.django_db
class TestRemoveListing:
    def test_removes_the_listing_and_keeps_the_item(self, inventory, owner):
        item = items.create_item(owner, {"name": "Rope"})
        elsewhere = inventories.create_inventory(owner, "Camping").inventory
        listing = list_directly(inventory, item)
        list_directly(elsewhere, item)

        items.remove_listing(listing)

        assert listed(inventory) == set()
        assert listed(elsewhere) == {item.id}
        assert Item.objects.filter(pk=item.pk).exists()


@pytest.mark.django_db
class TestMembershipChangesRemoveListings:
    """A user's listings in an inventory go when they leave it, are removed from it, or
    take the `member` role there. Their listings elsewhere, and other users' listings,
    stay."""

    @pytest.fixture
    def admin(self, inventory):
        return join(inventory, "admin", 2)

    @pytest.fixture
    def setup(self, inventory, owner, admin):
        elsewhere = inventories.create_inventory(admin, "Camping").inventory
        theirs = items.create_item(admin, {"name": "Rope"})
        ours = items.create_item(owner, {"name": "Tent"})
        for listing_inventory, item in [
            (inventory, theirs),
            (elsewhere, theirs),
            (inventory, ours),
        ]:
            list_directly(listing_inventory, item)
        return {"elsewhere": elsewhere, "theirs": theirs, "ours": ours}

    def assert_only_their_listing_here_is_gone(self, inventory, setup):
        assert listed(inventory) == {setup["ours"].id}
        assert listed(setup["elsewhere"]) == {setup["theirs"].id}
        assert Item.objects.count() == 2

    def test_leaving(self, inventory, admin, setup):
        inventories.remove_member(as_(admin, inventory), admin.id)

        self.assert_only_their_listing_here_is_gone(inventory, setup)

    def test_being_removed(self, inventory, owner, admin, setup):
        inventories.remove_member(as_(owner, inventory), admin.id)

        self.assert_only_their_listing_here_is_gone(inventory, setup)

    def test_taking_the_member_role(self, inventory, owner, admin, setup):
        inventories.set_role(as_(owner, inventory), admin.id, "member")

        self.assert_only_their_listing_here_is_gone(inventory, setup)

    @pytest.mark.parametrize("role", ["admin", "owner"])
    def test_other_role_changes_keep_the_listings(self, inventory, owner, admin, setup, role):
        inventories.set_role(as_(owner, inventory), admin.id, role)

        assert listed(inventory) == {setup["ours"].id, setup["theirs"].id}

    def test_a_refused_change_keeps_the_listings(self, inventory, owner, setup):
        with pytest.raises(Conflict):
            inventories.set_role(as_(owner, inventory), owner.id, "member")

        assert listed(inventory) == {setup["ours"].id, setup["theirs"].id}


INSERT_LISTING = 'INSERT INTO "gear_library_inventoryitem" '
DELETE_LISTING = 'DELETE FROM "gear_library_inventoryitem" '
SELECT_ITEM = 'SELECT "gear_library_item".'
SELECT_INVENTORY = 'SELECT "gear_library_inventory".'
FOR_UPDATE = " FOR UPDATE"


@pytest.mark.django_db(transaction=True)
class TestCommittedRaces:
    @pytest.fixture
    def owner(self):
        return make_user(1, "Olive")

    @pytest.fixture
    def inventory(self, owner):
        with transaction.atomic():
            return inventories.create_inventory(owner, "Climbing").inventory

    @pytest.fixture
    def item(self, owner):
        return items.create_item(owner, {"name": "Rope"})

    def race(self, first, second, held, release):
        """Runs `first` until it sets `held`, then `second` until it waits on a lock, then
        lets `first` go on. Returns each one's outcome."""
        outcomes = {}
        threads = [run_in_thread("first", first, outcomes)]
        assert held.wait(10)
        threads.append(run_in_thread("second", second, outcomes))
        try:
            wait_for_a_blocked_lock()
        finally:
            release.set()
            for thread in threads:
                thread.join(10)
        return outcomes

    def test_a_listing_waits_for_an_item_delete_and_is_refused(self, inventory, owner, item):
        actor = as_(owner, inventory)
        held, release = threading.Event(), threading.Event()

        def delete():
            with connection.execute_wrapper(hold_after(SELECT_ITEM, held, release, FOR_UPDATE)):
                items.delete_item(owner, item.id)

        outcomes = self.race(delete, lambda: items.add_listing(actor, item.id), held, release)

        assert outcomes["first"] == "ok"
        assert isinstance(outcomes["second"], ValidationError)
        assert outcomes["second"].detail == NOT_YOURS
        assert not Item.objects.exists()
        assert not InventoryItem.objects.exists()

    def test_an_item_delete_waits_for_a_listing_and_deletes_it(self, inventory, owner, item):
        actor = as_(owner, inventory)
        held, release = threading.Event(), threading.Event()

        def list_it():
            with connection.execute_wrapper(hold_after(INSERT_LISTING, held, release)):
                items.add_listing(actor, item.id)

        outcomes = self.race(list_it, lambda: items.delete_item(owner, item.id), held, release)

        assert outcomes == {"first": "ok", "second": "ok"}
        assert not Item.objects.exists()
        assert not InventoryItem.objects.exists()

    def test_an_item_delete_locks_an_inventory_the_item_was_listed_in_after_it_started(
        self, inventory, owner, item
    ):
        """The listing commits after the delete read the item's listings and before it
        locked the item. The delete must not delete that listing without its inventory's
        lock, and cannot take that lock while it holds the item row."""
        list_directly(inventory, item)
        with transaction.atomic():
            camping = inventories.create_inventory(owner, "Camping").inventory
        statements, listed_elsewhere = [], threading.Event()

        def list_it_first(execute, sql, params, many, context):
            is_item_lock = sql.startswith(SELECT_ITEM) and sql.endswith(FOR_UPDATE)
            if is_item_lock and not listed_elsewhere.is_set():
                listed_elsewhere.set()
                outcomes = {}
                run_in_thread(
                    "lister", lambda: items.add_listing(as_(owner, camping), item.id), outcomes
                ).join(10)
                assert outcomes == {"lister": "ok"}
            statements.append((sql, params))
            return execute(sql, params, many, context)

        with connection.execute_wrapper(list_it_first):
            items.delete_item(owner, item.id)

        assert listed_elsewhere.is_set()
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
