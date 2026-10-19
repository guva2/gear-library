import threading
import time

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test.utils import CaptureQueriesContext
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

    def test_deleting_is_one_delete_of_the_inventory_row(self, inventory, owner):
        actor = as_(owner, inventory, "owner")
        with CaptureQueriesContext(connection) as queries:
            inventories.delete_inventory(actor)

        statements = [
            query["sql"]
            for query in queries
            if not query["sql"].startswith(("SAVEPOINT", "RELEASE"))
        ]
        assert len(statements) == 1
        assert statements[0].startswith('DELETE FROM "gear_library_inventory" ')

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

    def test_an_actor_demoted_since_the_check_is_forbidden(self, inventory, owner):
        member = join(inventory, "member", 2)
        actor = as_(owner, inventory, "owner")
        other_owner = join(inventory, "owner", 3)
        Membership.objects.filter(inventory=inventory, user=owner).update(role="admin")

        with pytest.raises(PermissionDenied):
            inventories.set_role(actor, member.id, "admin")
        assert role_of(inventory, member) == "member"
        assert role_of(inventory, other_owner) == "owner"

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

    def test_accepting_as_a_member_accepts_and_keeps_the_membership(
        self, inventory, invitee, invite
    ):
        existing = Membership.objects.create(inventory=inventory, user=invitee, role="admin")

        membership = inventories.accept_invite(invitee, invite.id)

        assert (membership.pk, membership.role) == (existing.pk, "admin")
        assert Membership.objects.filter(user=invitee).count() == 1
        assert self.status(invite) == "accepted"

    def test_accepting_an_accepted_invite_again_returns_the_membership(
        self, inventory, invitee, invite
    ):
        first = inventories.accept_invite(invitee, invite.id)

        again = inventories.accept_invite(invitee, invite.id)

        assert (again.pk, again.role) == (first.pk, "member")
        assert self.status(invite) == "accepted"

    def test_accepting_an_accepted_invite_after_leaving_conflicts(
        self, inventory, invitee, invite
    ):
        inventories.accept_invite(invitee, invite.id)
        inventories.remove_member(invitee, inventory.id, invitee.id)

        with pytest.raises(Conflict) as excinfo:
            inventories.accept_invite(invitee, invite.id)
        assert excinfo.value.detail == "This invite is no longer pending."
        assert not Membership.objects.filter(user=invitee).exists()

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

    @pytest.mark.parametrize(
        "action, by",
        [
            (inventories.accept_invite, "invitee"),
            (inventories.decline_invite, "invitee"),
            (inventories.revoke_invite, "owner"),
        ],
    )
    def test_an_invite_whose_inventory_was_deleted_after_it_was_read_is_not_found(
        self, inventory, invitee, owner, invite, monkeypatch, action, by
    ):
        invite_for = inventories._invite_for

        def delete_after_reading(*args, **kwargs):
            found = invite_for(*args, **kwargs)
            Inventory.objects.filter(pk=inventory.pk).delete()
            return found

        monkeypatch.setattr(inventories, "_invite_for", delete_after_reading)
        user = invitee if by == "invitee" else owner

        with pytest.raises(NotFound) as excinfo:
            action(user, invite.id)
        assert excinfo.value.detail == "Invite not found."
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


def hold_after_joining(monkeypatch, thread_name, joined, release):
    """Makes the accept in thread `thread_name` set `joined` after it adds the membership,
    then wait for `release` before it commits."""
    join_inventory = inventories._join

    def hold(*args, **kwargs):
        membership = join_inventory(*args, **kwargs)
        if threading.current_thread().name == thread_name:
            joined.set()
            assert release.wait(10)
        return membership

    monkeypatch.setattr(inventories, "_join", hold)


def step_down(user, inventory):
    def action():
        actor = inventories.get_membership(user, inventory.id, "owner")
        inventories.set_role(actor, user.id, "member")

    return action


def leave(user, inventory):
    return lambda: inventories.remove_member(user, inventory.id, user.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "first_action, second_action",
    [(step_down, step_down), (leave, step_down), (step_down, leave)],
)
def test_two_owners_giving_up_ownership_at_once_leave_one_owner(
    monkeypatch, first_action, second_action
):
    """The first owner's change holds the inventory lock until the second owner's change
    is queued behind it. The second one then counts the owners again and is refused."""
    first = make_user(1)
    inventory = inventories.create_inventory(first, "Climbing").inventory
    second = join(inventory, "owner", 2)

    locked = threading.Event()
    release = threading.Event()
    lock_inventory = inventories._lock_inventory

    def hold_lock_for_first(inventory_id):
        result = lock_inventory(inventory_id)
        if threading.current_thread().name == "first":
            locked.set()
            assert release.wait(10)
        return result

    monkeypatch.setattr(inventories, "_lock_inventory", hold_lock_for_first)
    outcomes = {}

    threads = [run_in_thread("first", first_action(first, inventory), outcomes)]
    assert locked.wait(10)
    threads.append(run_in_thread("second", second_action(second, inventory), outcomes))
    try:
        wait_for_a_blocked_lock()
    finally:
        release.set()
        for thread in threads:
            thread.join(10)

    assert outcomes["first"] == "ok"
    assert isinstance(outcomes["second"], Conflict)
    assert owner_count(inventory) == 1
    assert role_of(inventory, second) == "owner"


def promote(owner, member, inventory):
    def action():
        inventories.set_role(as_(owner, inventory, "owner"), member.id, "admin")

    return action


def remove(owner, member, inventory):
    return lambda: inventories.remove_member(owner, inventory.id, member.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("change", [promote, remove])
def test_a_delete_waits_for_a_member_change_and_then_deletes(monkeypatch, change):
    """The member change holds the inventory lock until the delete is queued behind it.
    Both finish, and the delete removes the inventory with all its memberships."""
    owner = make_user(1)
    inventory = inventories.create_inventory(owner, "Climbing").inventory
    member = join(inventory, "member", 2)
    delete_actor = as_(owner, inventory, "owner")

    locked = threading.Event()
    release = threading.Event()
    lock_inventory = inventories._lock_inventory

    def hold_lock_for_the_change(inventory_id):
        result = lock_inventory(inventory_id)
        if threading.current_thread().name == "change":
            locked.set()
            assert release.wait(10)
        return result

    monkeypatch.setattr(inventories, "_lock_inventory", hold_lock_for_the_change)
    outcomes = {}

    threads = [run_in_thread("change", change(owner, member, inventory), outcomes)]
    assert locked.wait(10)
    threads.append(
        run_in_thread("delete", lambda: inventories.delete_inventory(delete_actor), outcomes)
    )
    try:
        wait_for_a_blocked_lock()
    finally:
        release.set()
        for thread in threads:
            thread.join(10)

    assert outcomes == {"change": "ok", "delete": "ok"}
    assert not Inventory.objects.exists()
    assert not Membership.objects.exists()


@pytest.mark.django_db(transaction=True)
class TestCommittedRaces:
    """These tests commit for real: membership and invite foreign keys are checked at
    commit, and an insert waiting on a unique index learns the outcome only then."""

    @pytest.fixture
    def owner(self):
        return make_user(1, "Olive")

    @pytest.fixture
    def inventory(self, owner):
        return inventories.create_inventory(owner, "Climbing").inventory

    def test_inviting_to_an_inventory_deleted_since_the_check_is_not_found(
        self, inventory, owner
    ):
        actor = as_(owner, inventory, "admin")
        Inventory.objects.filter(pk=inventory.pk).delete()

        with pytest.raises(NotFound) as excinfo:
            inventories.invite(actor, make_user(3).phone_number)
        assert excinfo.value.detail == "Inventory not found."
        assert not InventoryInvite.objects.exists()

    def test_a_delete_after_an_invite_commits_deletes_the_invite(self, inventory, owner):
        invitee = make_user(3)
        outcomes = {}

        def invite_before_the_delete(execute, sql, params, many, context):
            if sql.startswith('DELETE FROM "gear_library_inventory" '):
                action = lambda: inventories.invite(as_(owner, inventory), invitee.phone_number)
                run_in_thread("invite", action, outcomes).join(10)
            return execute(sql, params, many, context)

        actor = as_(owner, inventory, "owner")
        with connection.execute_wrapper(invite_before_the_delete):
            inventories.delete_inventory(actor)

        assert outcomes["invite"] == "ok"
        assert not Inventory.objects.exists()
        assert not InventoryInvite.objects.exists()

    def test_a_delete_waits_for_an_accept_and_then_deletes_the_new_membership(
        self, inventory, owner, monkeypatch
    ):
        """The accept holds the inventory row until the delete waits on it."""
        invitee = make_user(3)
        invite = inventories.invite(as_(owner, inventory), invitee.phone_number)

        joined = threading.Event()
        release = threading.Event()
        hold_after_joining(monkeypatch, "accept", joined, release)
        outcomes = {}
        actor = as_(owner, inventory, "owner")

        threads = [
            run_in_thread("accept", lambda: inventories.accept_invite(invitee, invite.id), outcomes)
        ]
        assert joined.wait(10)
        threads.append(
            run_in_thread("delete", lambda: inventories.delete_inventory(actor), outcomes)
        )
        try:
            wait_for_a_blocked_lock()
        finally:
            release.set()
            for thread in threads:
                thread.join(10)

        assert outcomes == {"accept": "ok", "delete": "ok"}
        assert not Inventory.objects.exists()
        assert not Membership.objects.exists()
        assert not InventoryInvite.objects.exists()

    def test_an_invite_sent_while_an_accept_commits_can_be_accepted(
        self, inventory, owner, monkeypatch
    ):
        """The second invite checks membership before the accept commits, then waits on
        the pending-invite index until it does. The invitee ends up a member with a
        pending invite, and accepting it succeeds."""
        invitee = make_user(3)
        first = inventories.invite(as_(owner, inventory), invitee.phone_number)

        joined = threading.Event()
        release = threading.Event()
        hold_after_joining(monkeypatch, "accept", joined, release)
        outcomes = {}
        invited = []

        threads = [
            run_in_thread("accept", lambda: inventories.accept_invite(invitee, first.id), outcomes)
        ]
        assert joined.wait(10)
        send_again = lambda: invited.append(
            inventories.invite(as_(owner, inventory), invitee.phone_number)
        )
        threads.append(run_in_thread("invite", send_again, outcomes))
        try:
            wait_for_a_blocked_lock()
        finally:
            release.set()
            for thread in threads:
                thread.join(10)
        assert outcomes == {"accept": "ok", "invite": "ok"}

        membership = inventories.accept_invite(invitee, invited[0].id)

        assert membership.role == "member"
        assert Membership.objects.filter(inventory=inventory, user=invitee).count() == 1
        statuses = InventoryInvite.objects.filter(invitee=invitee).values_list("status", flat=True)
        assert list(statuses) == ["accepted", "accepted"]
