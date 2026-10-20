import threading
import time

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, connections, transaction
from rest_framework.exceptions import NotFound, ValidationError

from gear_library import inventories
from gear_library.errors import Conflict
from gear_library.models import Connection, Inventory, Membership, ordered_pair

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


def invite_pending(inventory, n, invited_by):
    """A user with a pending membership in `inventory`, added straight to the database."""
    user = make_user(n, "Pat")
    Membership.objects.create(
        inventory=inventory, user=user, role="member", status="pending", invited_by=invited_by
    )
    return user


def connect(user, other, status="accepted", requested_by=None):
    first, second = ordered_pair(user, other)
    return Connection.objects.create(
        first_user_id=first,
        second_user_id=second,
        requested_by=requested_by or user,
        status=status,
    )


def role_of(inventory, user):
    return Membership.objects.get(inventory=inventory, user=user).role


def as_(user, inventory):
    """The user's active membership of `inventory`, with the inventory."""
    return Membership.objects.active().select_related("inventory").get(
        inventory=inventory, user=user
    )


def owner_count(inventory):
    return Membership.objects.filter(inventory=inventory, role="owner").count()


def status_of(membership_id):
    row = Membership.objects.filter(pk=membership_id).first()
    return row and row.status


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
class TestRenameAndDelete:
    def test_an_owner_renames_and_deletes(self, inventory, owner):
        inventories.rename_inventory(as_(owner, inventory), "Bouldering")
        assert Inventory.objects.get().name == "Bouldering"

        inventories.delete_inventory(as_(owner, inventory))
        assert not Inventory.objects.exists()
        assert not Membership.objects.exists()


@pytest.mark.django_db
class TestSetRole:
    def set_role(self, owner, inventory, target, role):
        return inventories.set_role(as_(owner, inventory), target.id, role)

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

        inventories.remove_member(as_(owner, inventory), member.id)

        assert not Membership.objects.filter(user=member).exists()

    @pytest.mark.parametrize("role", ["member", "admin"])
    def test_any_member_leaves(self, inventory, role):
        user = join(inventory, role, 2)

        inventories.remove_member(as_(user, inventory), user.id)

        assert not Membership.objects.filter(user=user).exists()

    def test_an_owner_leaves_when_another_owner_remains(self, inventory, owner):
        join(inventory, "owner", 2)

        inventories.remove_member(as_(owner, inventory), owner.id)

        assert owner_count(inventory) == 1

    def test_the_last_owner_cannot_leave(self, inventory, owner):
        join(inventory, "member", 2)

        with pytest.raises(Conflict):
            inventories.remove_member(as_(owner, inventory), owner.id)
        assert owner_count(inventory) == 1


@pytest.mark.django_db
class TestPendingMember:
    """A pending membership is an invite: everywhere else its user is not a member."""

    @pytest.fixture
    def pending(self, inventory, owner):
        return invite_pending(inventory, 5, owner)

    def test_an_owner_cannot_set_their_role_or_remove_them(self, inventory, owner, pending):
        with pytest.raises(NotFound):
            inventories.set_role(as_(owner, inventory), pending.id, "member")
        with pytest.raises(NotFound):
            inventories.remove_member(as_(owner, inventory), pending.id)
        assert status_of(Membership.objects.get(user=pending).pk) == "pending"

    def test_is_not_counted_as_an_owner(self, inventory, owner, pending):
        with pytest.raises(Conflict):
            inventories.remove_member(as_(owner, inventory), owner.id)


@pytest.mark.django_db
class TestInvite:
    @pytest.mark.parametrize("role", ["admin", "owner"])
    def test_admins_and_owners_invite_a_connection(self, inventory, role):
        actor = join(inventory, role, 2)
        invitee = make_user(3)
        connect(actor, invitee)

        invite = inventories.invite(as_(actor, inventory), invitee.id)

        assert (invite.user, invite.invited_by, invite.status, invite.role) == (
            invitee,
            actor,
            "pending",
            "member",
        )

    @pytest.mark.parametrize(
        "who",
        [
            "no such user",
            "not connected",
            "requested by the caller",
            "requested of the caller",
            "connected to another admin",
            "the caller",
        ],
    )
    def test_anyone_but_a_connection_is_invalid_with_one_message(self, inventory, owner, who):
        admin = join(inventory, "admin", 2)
        other = make_user(3)
        if who == "requested by the caller":
            connect(owner, other, status="pending", requested_by=owner)
        elif who == "requested of the caller":
            connect(owner, other, status="pending", requested_by=other)
        elif who == "connected to another admin":
            connect(admin, other)
        user_id = {"no such user": 999999, "the caller": owner.id}.get(who, other.id)

        with pytest.raises(ValidationError) as excinfo:
            inventories.invite(as_(owner, inventory), user_id)
        assert excinfo.value.detail == {"user_id": [inventories.NOT_A_CONNECTION]}
        assert not Membership.objects.pending().exists()

    @pytest.mark.parametrize("status", ["active", "pending"])
    def test_a_member_or_someone_already_invited_conflicts(self, inventory, owner, status):
        invitee = make_user(3)
        connect(owner, invitee)
        Membership.objects.create(
            inventory=inventory, user=invitee, role="member", status=status, invited_by=owner
        )

        with pytest.raises(Conflict):
            inventories.invite(as_(owner, inventory), invitee.id)
        assert Membership.objects.filter(user=invitee).count() == 1

    def test_a_member_who_is_not_a_connection_is_invalid_not_a_conflict(self, inventory, owner):
        member = join(inventory, "member", 3)

        with pytest.raises(ValidationError):
            inventories.invite(as_(owner, inventory), member.id)

    def test_can_invite_again_after_a_decline_or_revoke(self, inventory, owner):
        invitee = make_user(3)
        connect(owner, invitee)
        invite = inventories.invite(as_(owner, inventory), invitee.id)
        inventories.delete_invite(invite)

        again = inventories.invite(as_(owner, inventory), invitee.id)

        assert again.status == "pending"

    def test_removing_the_connection_later_leaves_invites_and_members_alone(
        self, inventory, owner
    ):
        """The connection is checked only when the invite is sent."""
        invitee, member = make_user(3), make_user(4)
        connect(owner, invitee)
        connect(owner, member)
        pending = inventories.invite(as_(owner, inventory), invitee.id)
        joined = inventories.invite(as_(owner, inventory), member.id)
        inventories.accept_invite(joined)

        Connection.objects.all().delete()

        assert (status_of(pending.pk), status_of(joined.pk)) == ("pending", "active")
        inventories.accept_invite(pending)
        assert role_of(inventory, invitee) == "member"


@pytest.mark.django_db
class TestAnswerInvite:
    @pytest.fixture
    def invitee(self, owner):
        invitee = make_user(3, "Ivy")
        connect(owner, invitee)
        return invitee

    @pytest.fixture
    def invite(self, inventory, owner, invitee):
        return inventories.invite(as_(owner, inventory), invitee.id)

    def test_accepting_joins_as_member(self, inventory, invitee, invite):
        membership = inventories.accept_invite(invite)

        assert (membership.pk, membership.role, membership.status) == (
            invite.pk,
            "member",
            "active",
        )
        assert membership.inventory.name == "Climbing"
        assert as_(invitee, inventory).pk == invite.pk

    def test_accepting_again_returns_the_membership(self, invite):
        inventories.accept_invite(invite)
        Membership.objects.filter(pk=invite.pk).update(role="admin")

        again = inventories.accept_invite(invite)

        assert (again.pk, again.role, again.status) == (invite.pk, "admin", "active")
        assert again.inventory.name == "Climbing"

    def test_declining_or_revoking_deletes_the_invite(self, invitee, invite):
        inventories.delete_invite(invite)

        assert not Membership.objects.filter(user=invitee).exists()

    def test_declining_or_revoking_after_an_accept_conflicts(self, invite):
        inventories.accept_invite(invite)

        with pytest.raises(Conflict) as excinfo:
            inventories.delete_invite(invite)
        assert excinfo.value.detail == "This is not a pending invite."
        assert status_of(invite.pk) == "active"

    ANSWERS = [inventories.accept_invite, inventories.delete_invite]

    @pytest.mark.parametrize("action", ANSWERS)
    @pytest.mark.parametrize("gone_by", ["revoke", "leave"])
    def test_answering_an_invite_that_is_gone_is_not_found(
        self, inventory, invitee, invite, action, gone_by
    ):
        if gone_by == "revoke":
            inventories.delete_invite(invite)
        else:
            inventories.accept_invite(invite)
            inventories.remove_member(as_(invitee, inventory), invitee.id)

        with pytest.raises(NotFound) as excinfo:
            action(invite)
        assert excinfo.value.detail == "Invite not found."
        assert not Membership.objects.filter(user=invitee).exists()

    @pytest.mark.parametrize("action", ANSWERS)
    def test_an_invite_whose_inventory_was_deleted_after_it_was_read_is_not_found(
        self, inventory, invite, action
    ):
        Inventory.objects.filter(pk=inventory.pk).delete()

        with pytest.raises(NotFound):
            action(invite)
        assert not Membership.objects.exists()

    def test_an_invite_accepted_after_it_was_read_accepts(self, invite):
        Membership.objects.filter(pk=invite.pk).update(status="active")

        membership = inventories.accept_invite(invite)

        assert (membership.pk, membership.status) == (invite.pk, "active")

    def test_an_invite_stays_valid_when_its_sender_leaves(self, inventory, invitee):
        admin = join(inventory, "admin", 4)
        connect(admin, invitee)
        invite = inventories.invite(as_(admin, inventory), invitee.id)
        inventories.remove_member(as_(admin, inventory), admin.id)

        inventories.accept_invite(invite)

        assert role_of(inventory, invitee) == "member"

    def test_a_deleted_inventory_has_no_invites_to_answer(self, inventory, owner, invite):
        inventories.delete_inventory(as_(owner, inventory))

        with pytest.raises(NotFound):
            inventories.accept_invite(invite)


def wait_for_a_blocked_lock(timeout=5.0):
    """Waits until another connection to this database is waiting on a row lock."""
    deadline = time.monotonic() + timeout
    with connection.cursor() as cursor:
        while time.monotonic() < deadline:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE datname = current_database() AND wait_event_type = 'Lock'"
            )
            if cursor.fetchone()[0] > 0:
                return
            time.sleep(0.02)
    raise AssertionError("the second request never waited on a lock")


def run_in_thread(name, action, outcomes):
    """Runs `action` on its own database connection, recording "ok" or the error raised."""

    def target():
        try:
            action()
            outcomes[name] = "ok"
        except Exception as error:
            outcomes[name] = error
        finally:
            connections.close_all()

    thread = threading.Thread(target=target, name=name)
    thread.start()
    return thread


INSERT_MEMBERSHIP = 'INSERT INTO "gear_library_membership" '
UPDATE_MEMBERSHIP = 'UPDATE "gear_library_membership" '


def hold_after(sql_prefix, held, release, sql_suffix=""):
    """An execute wrapper that, after the first statement starting with `sql_prefix` and
    ending with `sql_suffix`, sets `held` and waits for `release` before the transaction
    goes on."""

    def wrapper(execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        if sql.startswith(sql_prefix) and sql.endswith(sql_suffix) and not held.is_set():
            held.set()
            assert release.wait(10)
        return result

    return wrapper


@pytest.mark.django_db(transaction=True)
class TestCommittedRaces:
    """These tests commit for real: membership foreign keys are checked at commit, and an
    insert waiting on a unique index learns the outcome only then."""

    @pytest.fixture
    def owner(self):
        return make_user(1, "Olive")

    @pytest.fixture
    def inventory(self, owner):
        return inventories.create_inventory(owner, "Climbing").inventory

    @pytest.fixture
    def invitee(self, owner):
        invitee = make_user(3, "Ivy")
        connect(owner, invitee)
        return invitee

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

    def test_a_second_invite_waits_for_the_first_and_conflicts(
        self, inventory, owner, invitee
    ):
        held, release = threading.Event(), threading.Event()

        def first():
            with connection.execute_wrapper(hold_after(INSERT_MEMBERSHIP, held, release)):
                inventories.invite(as_(owner, inventory), invitee.id)

        second = lambda: inventories.invite(as_(owner, inventory), invitee.id)

        outcomes = self.race(first, second, held, release)

        assert outcomes["first"] == "ok"
        assert isinstance(outcomes["second"], Conflict)
        assert status_of(Membership.objects.get(user=invitee).pk) == "pending"

    def test_a_delete_waits_for_an_accept_and_then_deletes_the_new_membership(
        self, inventory, owner, invitee
    ):
        invite = inventories.invite(as_(owner, inventory), invitee.id)
        actor = as_(owner, inventory)
        held, release = threading.Event(), threading.Event()

        def accept():
            with connection.execute_wrapper(hold_after(UPDATE_MEMBERSHIP, held, release)):
                inventories.accept_invite(invite)

        outcomes = self.race(accept, lambda: inventories.delete_inventory(actor), held, release)

        assert outcomes == {"first": "ok", "second": "ok"}
        assert not Inventory.objects.exists()
        assert not Membership.objects.exists()

    def test_an_accept_waits_for_a_delete_and_is_not_found(self, inventory, owner, invitee):
        invite = inventories.invite(as_(owner, inventory), invitee.id)
        actor = as_(owner, inventory)
        held, release = threading.Event(), threading.Event()

        def delete():
            with transaction.atomic():
                inventories.delete_inventory(actor)
                held.set()
                assert release.wait(10)

        outcomes = self.race(
            delete, lambda: inventories.accept_invite(invite), held, release
        )

        assert outcomes["first"] == "ok"
        assert isinstance(outcomes["second"], NotFound)
        assert not Inventory.objects.exists()
        assert not Membership.objects.exists()

    def test_a_revoke_waits_for_an_accept_and_conflicts(self, inventory, owner, invitee):
        invite = inventories.invite(as_(owner, inventory), invitee.id)
        held, release = threading.Event(), threading.Event()

        def accept():
            with connection.execute_wrapper(hold_after(UPDATE_MEMBERSHIP, held, release)):
                inventories.accept_invite(invite)

        revoke = lambda: inventories.delete_invite(invite)

        outcomes = self.race(accept, revoke, held, release)

        assert outcomes["first"] == "ok"
        assert isinstance(outcomes["second"], Conflict)
        assert status_of(invite.pk) == "active"
