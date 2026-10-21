import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError

from gear_library.models import Inventory, Membership

User = get_user_model()


@pytest.fixture
def ada():
    return User.objects.create_user(phone_number="5552230001", first_name="Ada", last_name="L")


@pytest.fixture
def bob():
    return User.objects.create_user(phone_number="5552230002", first_name="Bob", last_name="B")


@pytest.fixture
def inventory():
    return Inventory.objects.create(name="Climbing")


def assert_rejected_by(constraint, create):
    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        create()


def membership(inventory, user, role="member", status="active", invited_by=None):
    return Membership.objects.create(
        inventory=inventory, user=user, role=role, status=status, invited_by=invited_by
    )


@pytest.mark.django_db
class TestMembership:
    def test_role_check_rejects_an_unknown_role(self, inventory, ada):
        assert_rejected_by(
            "gear_library_membership_role_valid",
            lambda: membership(inventory, ada, role="boss"),
        )

    @pytest.mark.parametrize("status", ["maybe", ""])
    def test_status_check_rejects_an_unknown_status(self, inventory, ada, status):
        assert_rejected_by(
            "gear_library_membership_status_valid",
            lambda: membership(inventory, ada, status=status),
        )

    @pytest.mark.parametrize("role", ["admin", "owner"])
    def test_a_pending_membership_must_have_the_member_role(self, inventory, ada, bob, role):
        assert_rejected_by(
            "gear_library_membership_pending_is_member",
            lambda: membership(inventory, bob, role=role, status="pending", invited_by=ada),
        )

    @pytest.mark.parametrize("first_status", ["pending", "active"])
    def test_a_user_has_one_membership_per_inventory_whatever_its_status(
        self, inventory, ada, bob, first_status
    ):
        membership(inventory, bob, status=first_status, invited_by=ada)

        for status in ["pending", "active"]:
            assert_rejected_by(
                "gear_library_membership_one_per_user",
                lambda: membership(inventory, bob, status=status, invited_by=ada),
            )

    @pytest.mark.parametrize("person", ["user", "invited_by"])
    def test_deleting_a_member_or_an_inviter_is_refused(self, inventory, ada, bob, person):
        invite = membership(inventory, bob, status="pending", invited_by=ada)

        with pytest.raises(ProtectedError):
            getattr(invite, person).delete()

    def test_active_and_pending_select_by_status(self, inventory, ada, bob):
        active = membership(inventory, ada, role="owner")
        pending = membership(inventory, bob, status="pending", invited_by=ada)

        assert list(Membership.objects.active()) == [active]
        assert list(Membership.objects.pending()) == [pending]


@pytest.mark.django_db
def test_deleting_an_inventory_deletes_its_memberships(inventory, ada, bob):
    membership(inventory, ada, role="owner")
    membership(inventory, bob, status="pending", invited_by=ada)

    inventory.delete()

    assert not Membership.objects.exists()
    assert User.objects.count() == 2


@pytest.mark.django_db
def test_the_inventory_foreign_key_is_no_action_and_checked_at_commit():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT confdeltype, condeferrable, condeferred FROM pg_constraint"
            " WHERE contype = 'f' AND conrelid = %s::regclass AND confrelid = %s::regclass",
            [Membership._meta.db_table, Inventory._meta.db_table],
        )
        assert cursor.fetchall() == [("a", True, True)]
