import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError

from gear_library.models import Inventory, InventoryItem, Item

User = get_user_model()


@pytest.fixture
def ada():
    return User.objects.create_user(phone_number="5551230001", first_name="Ada", last_name="L")


@pytest.fixture
def item(ada):
    return Item.objects.create(owner=ada, name="Rope")


@pytest.fixture
def inventory():
    return Inventory.objects.create(name="Climbing")


@pytest.mark.django_db
class TestItem:
    def test_description_is_stored_as_empty_text_when_omitted(self, item):
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT description FROM {Item._meta.db_table} WHERE id = %s", [item.pk]
            )
            assert cursor.fetchone() == ("",)

    def test_deleting_an_owner_is_refused(self, ada, item):
        with pytest.raises(ProtectedError):
            ada.delete()


@pytest.mark.django_db
class TestInventoryItem:
    def test_an_item_is_listed_once_per_inventory(self, inventory, item):
        InventoryItem.objects.create(inventory=inventory, item=item)

        with pytest.raises(IntegrityError, match="gear_library_inventoryitem_one_per_item"):
            with transaction.atomic():
                InventoryItem.objects.create(inventory=inventory, item=item)

    def test_an_item_is_listed_in_several_inventories(self, inventory, item):
        other = Inventory.objects.create(name="Camping")

        InventoryItem.objects.create(inventory=inventory, item=item)
        InventoryItem.objects.create(inventory=other, item=item)

        assert item.listings.count() == 2

    def test_deleting_an_inventory_deletes_its_listings_and_keeps_the_items(
        self, inventory, item
    ):
        InventoryItem.objects.create(inventory=inventory, item=item)

        inventory.delete()

        assert not InventoryItem.objects.exists()
        assert Item.objects.get() == item

    def test_deleting_an_item_deletes_its_listings(self, inventory, item):
        InventoryItem.objects.create(inventory=inventory, item=item)

        item.delete()

        assert not InventoryItem.objects.exists()
        assert Inventory.objects.get() == inventory


@pytest.mark.django_db
@pytest.mark.parametrize("target", [Inventory, Item])
def test_the_listing_foreign_keys_are_no_action_and_checked_at_commit(target):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT confdeltype, condeferrable, condeferred FROM pg_constraint"
            " WHERE contype = 'f' AND conrelid = %s::regclass AND confrelid = %s::regclass",
            [InventoryItem._meta.db_table, target._meta.db_table],
        )
        assert cursor.fetchall() == [("a", True, True)]
