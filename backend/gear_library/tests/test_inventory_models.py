import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from gear_library.models import Inventory, InventoryInvite, Membership

User = get_user_model()


@pytest.fixture
def ada():
    return User.objects.create_user(phone_number="5551230001", first_name="Ada", last_name="L")


@pytest.fixture
def bob():
    return User.objects.create_user(phone_number="5551230002", first_name="Bob", last_name="B")


@pytest.fixture
def inventory():
    return Inventory.objects.create(name="Climbing")


def assert_rejected_by(constraint, create):
    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        create()


@pytest.mark.django_db
class TestMembership:
    def test_role_check_rejects_an_unknown_role(self, inventory, ada):
        assert_rejected_by(
            "gear_library_membership_role_valid",
            lambda: Membership.objects.create(inventory=inventory, user=ada, role="boss"),
        )

    def test_a_user_has_one_membership_per_inventory(self, inventory, ada):
        Membership.objects.create(inventory=inventory, user=ada, role="member")

        assert_rejected_by(
            "gear_library_membership_one_per_user",
            lambda: Membership.objects.create(inventory=inventory, user=ada, role="admin"),
        )

    def test_deleting_a_user_with_a_membership_is_refused(self, inventory, ada):
        Membership.objects.create(inventory=inventory, user=ada, role="owner")

        with pytest.raises(ProtectedError):
            ada.delete()


@pytest.mark.django_db
class TestInventoryInvite:
    def invite(self, inventory, invitee, invited_by, status="pending"):
        return InventoryInvite.objects.create(
            inventory=inventory, invitee=invitee, invited_by=invited_by, status=status
        )

    def test_status_check_rejects_an_unknown_status(self, inventory, ada, bob):
        assert_rejected_by(
            "gear_library_inventoryinvite_status_valid",
            lambda: self.invite(inventory, bob, ada, status="maybe"),
        )

    def test_one_pending_invite_per_inventory_and_invitee(self, inventory, ada, bob):
        self.invite(inventory, bob, ada)

        assert_rejected_by(
            "gear_library_inventoryinvite_one_pending",
            lambda: self.invite(inventory, bob, ada),
        )

    def test_finished_invites_do_not_block_a_new_pending_one(self, inventory, ada, bob):
        for status in ["accepted", "declined", "revoked"]:
            self.invite(inventory, bob, ada, status=status)

        self.invite(inventory, bob, ada)

        assert InventoryInvite.objects.count() == 4

    @pytest.mark.parametrize("person", ["invitee", "invited_by"])
    def test_deleting_an_invited_or_inviting_user_is_refused(self, inventory, ada, bob, person):
        invite = self.invite(inventory, bob, ada)

        with pytest.raises(ProtectedError):
            getattr(invite, person).delete()


@pytest.mark.django_db
def test_deleting_an_inventory_deletes_its_memberships_and_invites(inventory, ada, bob):
    Membership.objects.create(inventory=inventory, user=ada, role="owner")
    InventoryInvite.objects.create(inventory=inventory, invitee=bob, invited_by=ada)

    inventory.delete()

    assert not Membership.objects.exists()
    assert not InventoryInvite.objects.exists()
    assert User.objects.count() == 2
