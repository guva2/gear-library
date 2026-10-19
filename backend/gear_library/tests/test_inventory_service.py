import pytest
from django.contrib.auth import get_user_model
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from gear_library import inventories
from gear_library.inventories import Conflict
from gear_library.models import Inventory, InventoryInvite, Membership

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
    Membership.objects.create(inventory=inventory, user=user, role=role)
    return user


def role_of(inventory, user):
    return Membership.objects.get(inventory=inventory, user=user).role


def as_(user, inventory, role="member"):
    return inventories.get_membership(user, inventory.id, role)


def owner_count(inventory):
    return Membership.objects.filter(inventory=inventory, role="owner").count()


@pytest.mark.django_db
class TestCreateInventory:
    def test_makes_the_creator_its_owner(self, owner):
        membership = inventories.create_inventory(owner, "Climbing")

        assert membership.inventory.name == "Climbing"
        assert (membership.user, membership.role) == (owner, "owner")
        assert role_of(membership.inventory, owner) == "owner"

    def test_creates_nothing_when_the_membership_insert_fails(self, owner, monkeypatch):
        def fail(**kwargs):
            raise RuntimeError("insert failed")

        monkeypatch.setattr(Membership.objects, "create", fail)

        with pytest.raises(RuntimeError):
            inventories.create_inventory(owner, "Climbing")
        assert not Inventory.objects.exists()


@pytest.mark.django_db
class TestAccess:
    def test_a_non_member_gets_not_found(self, inventory):
        with pytest.raises(NotFound):
            as_(make_user(9), inventory)

    def test_a_missing_inventory_is_not_found(self, owner):
        with pytest.raises(NotFound):
            inventories.get_membership(owner, 999999)

    @pytest.mark.parametrize("role", ["member", "admin"])
    def test_a_lower_role_is_forbidden(self, inventory, role):
        user = join(inventory, role, 2)

        with pytest.raises(PermissionDenied):
            as_(user, inventory, "owner")

    def test_an_owner_renames_and_deletes(self, inventory, owner):
        inventories.rename_inventory(as_(owner, inventory, "owner"), "Bouldering")
        assert Inventory.objects.get().name == "Bouldering"

        inventories.delete_inventory(as_(owner, inventory, "owner"))
        assert not Inventory.objects.exists()
        assert not Membership.objects.exists()

    def test_renaming_an_inventory_deleted_since_the_check_is_not_found(
        self, inventory, owner
    ):
        actor = as_(owner, inventory, "owner")
        Inventory.objects.filter(pk=inventory.pk).delete()

        with pytest.raises(NotFound):
            inventories.rename_inventory(actor, "Bouldering")


@pytest.mark.django_db
class TestSetRole:
    def set_role(self, owner, inventory, target, role):
        return inventories.set_role(as_(owner, inventory, "owner"), target.id, role)

    def test_an_owner_sets_another_owners_role(self, inventory, owner):
        other = join(inventory, "owner", 2)

        self.set_role(owner, inventory, other, "admin")

        assert role_of(inventory, other) == "admin"

    def test_an_owner_steps_down_when_another_owner_remains(self, inventory, owner):
        join(inventory, "owner", 2)

        self.set_role(owner, inventory, owner, "member")

        assert role_of(inventory, owner) == "member"

    @pytest.mark.parametrize("role", ["member", "admin"])
    def test_the_last_owner_cannot_take_a_lower_role(self, inventory, owner, role):
        with pytest.raises(Conflict):
            self.set_role(owner, inventory, owner, role)
        assert role_of(inventory, owner) == "owner"

    def test_the_last_owner_may_set_their_own_role_to_owner(self, inventory, owner):
        self.set_role(owner, inventory, owner, "owner")

        assert role_of(inventory, owner) == "owner"

    def test_a_user_who_is_not_a_member_is_not_found(self, inventory, owner):
        with pytest.raises(NotFound):
            self.set_role(owner, inventory, make_user(9), "admin")

    def test_a_member_removed_since_it_was_read_is_not_found(
        self, inventory, owner, monkeypatch
    ):
        member = join(inventory, "member", 2)
        target_membership = inventories._target_membership

        def remove_after_reading(*args):
            target = target_membership(*args)
            Membership.objects.filter(pk=target.pk).delete()
            return target

        monkeypatch.setattr(inventories, "_target_membership", remove_after_reading)

        with pytest.raises(NotFound):
            self.set_role(owner, inventory, member, "admin")


@pytest.mark.django_db
class TestRemoveMember:
    def test_an_owner_removes_a_member(self, inventory, owner):
        member = join(inventory, "admin", 2)

        inventories.remove_member(owner, inventory.id, member.id)

        assert not Membership.objects.filter(user=member).exists()

    def test_an_admin_cannot_remove_someone_else(self, inventory):
        admin = join(inventory, "admin", 2)
        member = join(inventory, "member", 3)

        with pytest.raises(PermissionDenied):
            inventories.remove_member(admin, inventory.id, member.id)

    @pytest.mark.parametrize("role", ["member", "admin"])
    def test_any_member_leaves(self, inventory, role):
        user = join(inventory, role, 2)

        inventories.remove_member(user, inventory.id, user.id)

        assert not Membership.objects.filter(user=user).exists()

    def test_an_owner_leaves_when_another_owner_remains(self, inventory, owner):
        join(inventory, "owner", 2)

        inventories.remove_member(owner, inventory.id, owner.id)

        assert owner_count(inventory) == 1

    def test_the_last_owner_cannot_leave(self, inventory, owner):
        join(inventory, "member", 2)

        with pytest.raises(Conflict):
            inventories.remove_member(owner, inventory.id, owner.id)
        assert owner_count(inventory) == 1


@pytest.mark.django_db
class TestInvite:
    @pytest.mark.parametrize("role", ["admin", "owner"])
    def test_admins_and_owners_invite_by_phone_number(self, inventory, role):
        actor = join(inventory, role, 2)
        invitee = make_user(3)

        invite = inventories.invite(as_(actor, inventory), invitee.phone_number)

        assert (invite.invitee, invite.invited_by, invite.status) == (invitee, actor, "pending")

    def test_an_unknown_phone_number_is_invalid(self, inventory, owner):
        with pytest.raises(ValidationError) as excinfo:
            inventories.invite(as_(owner, inventory), "5559999999")
        assert "phone_number" in excinfo.value.detail

    def test_a_member_cannot_be_invited(self, inventory, owner):
        member = join(inventory, "member", 2)

        with pytest.raises(Conflict):
            inventories.invite(as_(owner, inventory), member.phone_number)

    def test_the_pending_invite_index_refuses_a_second_one(self, inventory, owner):
        invitee = make_user(3)
        inventories.invite(as_(owner, inventory), invitee.phone_number)

        with pytest.raises(Conflict):
            inventories.invite(as_(owner, inventory), invitee.phone_number)
        assert InventoryInvite.objects.count() == 1

    @pytest.mark.parametrize("finish", ["decline", "revoke"])
    def test_can_invite_again_after_a_decline_or_revoke(self, inventory, owner, finish):
        invitee = make_user(3)
        invite = inventories.invite(as_(owner, inventory), invitee.phone_number)
        if finish == "decline":
            inventories.decline_invite(invitee, invite.id)
        else:
            inventories.revoke_invite(owner, invite.id)

        again = inventories.invite(as_(owner, inventory), invitee.phone_number)

        assert again.status == "pending"


@pytest.mark.django_db
class TestAnswerInvite:
    @pytest.fixture
    def invitee(self):
        return make_user(3, "Ivy")

    @pytest.fixture
    def invite(self, inventory, owner, invitee):
        return inventories.invite(as_(owner, inventory), invitee.phone_number)

    def status(self, invite):
        invite.refresh_from_db()
        return invite.status

    def test_accepting_joins_as_member(self, inventory, invitee, invite):
        membership = inventories.accept_invite(invitee, invite.id)

        assert membership.role == "member"
        assert role_of(inventory, invitee) == "member"
        assert self.status(invite) == "accepted"

    def test_declining_does_not_join(self, inventory, invitee, invite):
        inventories.decline_invite(invitee, invite.id)

        assert self.status(invite) == "declined"
        assert not Membership.objects.filter(user=invitee).exists()

    @pytest.mark.parametrize("answer", [inventories.accept_invite, inventories.decline_invite])
    def test_an_invite_that_is_not_pending_conflicts(self, owner, invitee, invite, answer):
        inventories.revoke_invite(owner, invite.id)

        with pytest.raises(Conflict):
            answer(invitee, invite.id)
        assert self.status(invite) == "revoked"

    def test_accepting_as_a_member_conflicts_and_leaves_the_invite_pending(
        self, inventory, invitee, invite
    ):
        Membership.objects.create(inventory=inventory, user=invitee, role="admin")

        with pytest.raises(Conflict) as excinfo:
            inventories.accept_invite(invitee, invite.id)
        assert excinfo.value.detail == "You are already a member."
        assert role_of(inventory, invitee) == "admin"
        assert self.status(invite) == "pending"

    @pytest.mark.parametrize(
        "action, by",
        [
            (inventories.accept_invite, "invitee"),
            (inventories.decline_invite, "invitee"),
            (inventories.revoke_invite, "owner"),
        ],
    )
    @pytest.mark.parametrize("finished", ["accepted", "revoked"])
    def test_an_invite_finished_after_it_was_read_conflicts(
        self, invitee, owner, invite, monkeypatch, action, by, finished
    ):
        invite_for = inventories._invite_for

        def finish_after_reading(*args, **kwargs):
            found = invite_for(*args, **kwargs)
            InventoryInvite.objects.filter(pk=found.pk).update(status=finished)
            return found

        monkeypatch.setattr(inventories, "_invite_for", finish_after_reading)
        user = invitee if by == "invitee" else owner

        with pytest.raises(Conflict) as excinfo:
            action(user, invite.id)
        assert excinfo.value.detail == "This invite is no longer pending."
        assert self.status(invite) == finished
        assert not Membership.objects.filter(user=invitee).exists()

    @pytest.mark.parametrize("answer", [inventories.accept_invite, inventories.decline_invite])
    def test_an_admin_sees_the_invite_but_cannot_answer_it(self, invite, owner, answer):
        with pytest.raises(PermissionDenied):
            answer(owner, invite.id)

    @pytest.mark.parametrize("answer", [inventories.accept_invite, inventories.decline_invite])
    def test_anyone_else_gets_not_found(self, inventory, invite, answer):
        member = join(inventory, "member", 4)

        for user in [make_user(9), member]:
            with pytest.raises(NotFound):
                answer(user, invite.id)

    @pytest.mark.parametrize("role", ["admin", "owner"])
    def test_admins_and_owners_revoke_any_pending_invite(self, inventory, invite, role):
        actor = join(inventory, role, 4)

        inventories.revoke_invite(actor, invite.id)

        assert self.status(invite) == "revoked"

    def test_the_invitee_cannot_revoke(self, invitee, invite):
        with pytest.raises(PermissionDenied):
            inventories.revoke_invite(invitee, invite.id)

    def test_a_member_or_stranger_cannot_see_the_invite_to_revoke(self, inventory, invite):
        member = join(inventory, "member", 4)

        for user in [make_user(9), member]:
            with pytest.raises(NotFound):
                inventories.revoke_invite(user, invite.id)
        assert self.status(invite) == "pending"

    def test_revoking_a_finished_invite_conflicts(self, owner, invitee, invite):
        inventories.decline_invite(invitee, invite.id)

        with pytest.raises(Conflict):
            inventories.revoke_invite(owner, invite.id)

    def test_an_invite_stays_valid_when_its_sender_leaves(self, inventory, invitee):
        admin = join(inventory, "admin", 4)
        invite = inventories.invite(as_(admin, inventory), invitee.phone_number)
        inventories.remove_member(admin, inventory.id, admin.id)

        inventories.accept_invite(invitee, invite.id)

        assert role_of(inventory, invitee) == "member"

    def test_a_deleted_inventory_has_no_invites_to_answer(
        self, inventory, owner, invitee, invite
    ):
        inventories.delete_inventory(as_(owner, inventory, "owner"))

        with pytest.raises(NotFound):
            inventories.accept_invite(invitee, invite.id)
