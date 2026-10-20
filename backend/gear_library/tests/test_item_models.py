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


@pytest.fixture
def bea():
    return User.objects.create_user(phone_number="5551230002", first_name="Bea", last_name="M")


def set_loan(item, **fields):
    """Writes the loan columns with one UPDATE, bypassing every service check."""
    with transaction.atomic():
        Item.objects.filter(pk=item.pk).update(**fields)


@pytest.mark.django_db
class TestLoanColumns:
    def test_a_new_item_is_available_with_no_borrower(self, item):
        item.refresh_from_db()

        assert (item.loan_status, item.borrower, item.loan_inventory) == ("available", None, None)

    @pytest.mark.parametrize(
        "status, with_borrower, with_inventory",
        [
            ("requested", True, True),
            ("on_loan", True, True),
            ("on_loan", True, False),
            ("available", False, False),
        ],
    )
    def test_allowed_loan_states(
        self, item, bea, inventory, status, with_borrower, with_inventory
    ):
        set_loan(
            item,
            loan_status=status,
            borrower=bea if with_borrower else None,
            loan_inventory=inventory if with_inventory else None,
        )

        item.refresh_from_db()
        assert item.loan_status == status

    @pytest.mark.parametrize(
        "status, with_borrower, with_inventory",
        [
            ("available", True, False),
            ("available", False, True),
            ("requested", True, False),
            ("requested", False, True),
            ("on_loan", False, True),
            ("on_loan", False, False),
        ],
    )
    def test_refused_loan_states(
        self, item, bea, inventory, status, with_borrower, with_inventory
    ):
        with pytest.raises(IntegrityError, match="gear_library_item_loan_state"):
            set_loan(
                item,
                loan_status=status,
                borrower=bea if with_borrower else None,
                loan_inventory=inventory if with_inventory else None,
            )

    def test_an_unknown_loan_status_is_refused(self, item):
        # Postgres checks constraints in name order, and `loan_state` refuses it first.
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute(
                f"ALTER TABLE {Item._meta.db_table} DROP CONSTRAINT gear_library_item_loan_state"
            )
        with pytest.raises(IntegrityError, match="gear_library_item_loan_status_valid"):
            set_loan(item, loan_status="lost")

    def test_the_owner_holds_their_item_on_loan_with_no_loan_inventory(self, item, ada):
        set_loan(item, loan_status="on_loan", borrower=ada)

        item.refresh_from_db()
        assert (item.loan_status, item.borrower, item.loan_inventory) == ("on_loan", ada, None)

    @pytest.mark.parametrize("status", ["requested", "on_loan"])
    def test_the_owner_cannot_hold_their_item_through_an_inventory(
        self, item, ada, inventory, status
    ):
        with pytest.raises(IntegrityError, match="gear_library_item_owner_use"):
            set_loan(item, loan_status=status, borrower=ada, loan_inventory=inventory)

    def test_deleting_a_borrower_is_refused(self, item, bea):
        set_loan(item, loan_status="on_loan", borrower=bea)

        with pytest.raises(ProtectedError):
            bea.delete()

    def test_deleting_the_loan_inventory_keeps_the_loan(self, item, bea, inventory):
        set_loan(item, loan_status="on_loan", borrower=bea, loan_inventory=inventory)

        inventory.delete()

        item.refresh_from_db()
        assert (item.loan_status, item.borrower, item.loan_inventory) == ("on_loan", bea, None)


@pytest.mark.django_db
@pytest.mark.parametrize("column", ["borrower_id", "loan_inventory_id"])
def test_the_loan_foreign_keys_are_no_action_and_checked_at_commit(column):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT confdeltype, condeferrable, condeferred FROM pg_constraint c"
            " JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]"
            " WHERE c.contype = 'f' AND c.conrelid = %s::regclass AND a.attname = %s",
            [Item._meta.db_table, column],
        )
        assert cursor.fetchall() == [("a", True, True)]
