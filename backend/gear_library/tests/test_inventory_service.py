import threading
import time

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, connections, transaction
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from gear_library import inventories
from gear_library.inventories import Conflict
from gear_library.models import Inventory, Membership

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


def role_of(inventory, user):
    return Membership.objects.get(inventory=inventory, user=user).role


def as_(user, inventory, role="member"):
    return inventories.get_membership(user, inventory.id, role)


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
class TestPendingMember:
    """A pending membership is an invite: everywhere else its user is not a member."""

    @pytest.fixture
    def pending(self, inventory, owner):
        return invite_pending(inventory, 5, owner)

    @pytest.mark.parametrize("role", ["member", "admin", "owner"])
    def test_gets_not_found_for_the_inventory(self, inventory, pending, role):
        with pytest.raises(NotFound):
            as_(pending, inventory, role)

    def test_cannot_leave(self, inventory, pending):
        with pytest.raises(NotFound):
            inventories.remove_member(pending, inventory.id, pending.id)
        assert status_of(Membership.objects.get(user=pending).pk) == "pending"

    def test_an_owner_cannot_set_their_role_or_remove_them(self, inventory, owner, pending):
        with pytest.raises(NotFound):
            inventories.set_role(as_(owner, inventory, "owner"), pending.id, "member")
        with pytest.raises(NotFound):
            inventories.remove_member(owner, inventory.id, pending.id)
        assert status_of(Membership.objects.get(user=pending).pk) == "pending"

    def test_is_not_counted_as_an_owner(self, inventory, owner, pending):
        with pytest.raises(Conflict):
            inventories.remove_member(owner, inventory.id, owner.id)


@pytest.mark.django_db
class TestInvite:
    @pytest.mark.parametrize("role", ["admin", "owner"])
    def test_admins_and_owners_invite_by_phone_number(self, inventory, role):
        actor = join(inventory, role, 2)
        invitee = make_user(3)

        invite = inventories.invite(as_(actor, inventory), invitee.phone_number)

        assert (invite.user, invite.invited_by, invite.status, invite.role) == (
            invitee,
            actor,
            "pending",
            "member",
        )

    def test_an_unknown_phone_number_is_invalid(self, inventory, owner):
        with pytest.raises(ValidationError) as excinfo:
            inventories.invite(as_(owner, inventory), "5559999999")
        assert "phone_number" in excinfo.value.detail

    @pytest.mark.parametrize("status", ["active", "pending"])
    def test_a_member_or_someone_already_invited_conflicts(self, inventory, owner, status):
        invitee = make_user(3)
        Membership.objects.create(
            inventory=inventory, user=invitee, role="member", status=status, invited_by=owner
        )

        with pytest.raises(Conflict):
            inventories.invite(as_(owner, inventory), invitee.phone_number)
        assert Membership.objects.filter(user=invitee).count() == 1

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

    def test_accepting_joins_as_member(self, inventory, invitee, invite):
        membership = inventories.accept_invite(invitee, invite.id)

        assert (membership.pk, membership.role, membership.status) == (
            invite.pk,
            "member",
            "active",
        )
        assert membership.inventory.name == "Climbing"
        assert as_(invitee, inventory).pk == invite.pk

    def test_accepting_again_returns_the_membership(self, inventory, invitee, invite):
        inventories.accept_invite(invitee, invite.id)
        Membership.objects.filter(pk=invite.pk).update(role="admin")

        again = inventories.accept_invite(invitee, invite.id)

        assert (again.pk, again.role, again.status) == (invite.pk, "admin", "active")
        assert again.inventory.name == "Climbing"

    def test_declining_deletes_the_invite(self, invitee, invite):
        inventories.decline_invite(invitee, invite.id)

        assert not Membership.objects.filter(user=invitee).exists()

    @pytest.mark.parametrize("role", ["admin", "owner"])
    def test_admins_and_owners_revoke_any_pending_invite(self, inventory, invite, role):
        actor = join(inventory, role, 4)

        inventories.revoke_invite(actor, invite.id)

        assert status_of(invite.pk) is None

    @pytest.mark.parametrize(
        "action, by",
        [(inventories.decline_invite, "invitee"), (inventories.revoke_invite, "owner")],
    )
    def test_declining_or_revoking_after_an_accept_conflicts(
        self, invitee, owner, invite, action, by
    ):
        inventories.accept_invite(invitee, invite.id)

        with pytest.raises(Conflict) as excinfo:
            action(invitee if by == "invitee" else owner, invite.id)
        assert excinfo.value.detail == "This is not a pending invite."
        assert status_of(invite.pk) == "active"

    @pytest.mark.parametrize(
        "action", [inventories.accept_invite, inventories.decline_invite]
    )
    @pytest.mark.parametrize("gone_by", ["revoke", "leave"])
    def test_answering_an_invite_that_is_gone_is_not_found(
        self, inventory, owner, invitee, invite, action, gone_by
    ):
        if gone_by == "revoke":
            inventories.revoke_invite(owner, invite.id)
        else:
            inventories.accept_invite(invitee, invite.id)
            inventories.remove_member(invitee, inventory.id, invitee.id)

        with pytest.raises(NotFound):
            action(invitee, invite.id)
        assert not Membership.objects.filter(user=invitee).exists()

    ANSWERS = [
        (inventories.accept_invite, "invitee"),
        (inventories.decline_invite, "invitee"),
        (inventories.revoke_invite, "owner"),
    ]

    def hook_after_reading(self, monkeypatch, change):
        """Runs `change(invite)` after the action has read the invite and checked access."""
        invite_for = inventories._invite_for

        def change_after_reading(*args, **kwargs):
            found = invite_for(*args, **kwargs)
            change(found)
            return found

        monkeypatch.setattr(inventories, "_invite_for", change_after_reading)

    @pytest.mark.parametrize("action, by", ANSWERS)
    def test_an_invite_deleted_after_it_was_read_is_not_found(
        self, invitee, owner, invite, monkeypatch, action, by
    ):
        self.hook_after_reading(
            monkeypatch, lambda found: Membership.objects.filter(pk=found.pk).delete()
        )

        with pytest.raises(NotFound) as excinfo:
            action(invitee if by == "invitee" else owner, invite.id)
        assert excinfo.value.detail == "Invite not found."
        assert not Membership.objects.filter(user=invitee).exists()

    @pytest.mark.parametrize("action, by", ANSWERS)
    def test_an_invite_whose_inventory_was_deleted_after_it_was_read_is_not_found(
        self, inventory, invitee, owner, invite, monkeypatch, action, by
    ):
        self.hook_after_reading(
            monkeypatch, lambda found: Inventory.objects.filter(pk=inventory.pk).delete()
        )

        with pytest.raises(NotFound):
            action(invitee if by == "invitee" else owner, invite.id)
        assert not Membership.objects.exists()

    def test_an_invite_accepted_after_it_was_read_accepts(
        self, invitee, invite, monkeypatch
    ):
        self.hook_after_reading(
            monkeypatch,
            lambda found: Membership.objects.filter(pk=found.pk).update(status="active"),
        )

        membership = inventories.accept_invite(invitee, invite.id)

        assert (membership.pk, membership.status) == (invite.pk, "active")

    @pytest.mark.parametrize("action, by", ANSWERS[1:])
    def test_an_invite_accepted_after_it_was_read_conflicts(
        self, invitee, owner, invite, monkeypatch, action, by
    ):
        self.hook_after_reading(
            monkeypatch,
            lambda found: Membership.objects.filter(pk=found.pk).update(status="active"),
        )

        with pytest.raises(Conflict):
            action(invitee if by == "invitee" else owner, invite.id)
        assert status_of(invite.pk) == "active"

    @pytest.mark.parametrize("action", [inventories.accept_invite, inventories.decline_invite])
    def test_an_admin_sees_the_invite_but_cannot_answer_it(self, invite, owner, action):
        with pytest.raises(PermissionDenied):
            action(owner, invite.id)
        assert status_of(invite.pk) == "pending"

    def test_the_invitee_cannot_revoke(self, invitee, invite):
        with pytest.raises(PermissionDenied):
            inventories.revoke_invite(invitee, invite.id)
        assert status_of(invite.pk) == "pending"

    def non_parties(self, inventory, owner):
        """A stranger, a plain member, another invitee, and an owner of another inventory."""
        elsewhere = inventories.create_inventory(make_user(8), "Elsewhere")
        return [
            make_user(9),
            join(inventory, "member", 4),
            invite_pending(inventory, 6, owner),
            elsewhere.user,
        ]

    @pytest.mark.parametrize("action, by", ANSWERS)
    @pytest.mark.parametrize("state", ["pending", "active", "gone"])
    def test_anyone_else_gets_not_found_whatever_the_state(
        self, inventory, owner, invitee, invite, action, by, state
    ):
        users = self.non_parties(inventory, owner)
        if state == "active":
            inventories.accept_invite(invitee, invite.id)
        elif state == "gone":
            inventories.decline_invite(invitee, invite.id)

        for user in users:
            with pytest.raises(NotFound):
                action(user, invite.id)
        assert status_of(invite.pk) == (None if state == "gone" else state)

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


INSERT_MEMBERSHIP = 'INSERT INTO "gear_library_membership" '
UPDATE_MEMBERSHIP = 'UPDATE "gear_library_membership" '


def hold_after(sql_prefix, held, release):
    """An execute wrapper that, after the first statement starting with `sql_prefix`,
    sets `held` and waits for `release` before the transaction goes on."""

    def wrapper(execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        if sql.startswith(sql_prefix) and not held.is_set():
            held.set()
            assert release.wait(10)
        return result

    return wrapper


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
    """These tests commit for real: membership foreign keys are checked at commit, and an
    insert waiting on a unique index learns the outcome only then."""

    @pytest.fixture
    def owner(self):
        return make_user(1, "Olive")

    @pytest.fixture
    def inventory(self, owner):
        return inventories.create_inventory(owner, "Climbing").inventory

    @pytest.fixture
    def invitee(self):
        return make_user(3, "Ivy")

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

    def test_inviting_to_an_inventory_deleted_since_the_check_is_not_found(
        self, inventory, owner, invitee
    ):
        actor = as_(owner, inventory, "admin")
        Inventory.objects.filter(pk=inventory.pk).delete()

        with pytest.raises(NotFound) as excinfo:
            inventories.invite(actor, invitee.phone_number)
        assert excinfo.value.detail == "Inventory not found."
        assert not Membership.objects.exists()

    def test_a_delete_after_an_invite_commits_deletes_the_invite(
        self, inventory, owner, invitee
    ):
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
        assert not Membership.objects.exists()

    def test_a_second_invite_waits_for_the_first_and_conflicts(
        self, inventory, owner, invitee
    ):
        held, release = threading.Event(), threading.Event()

        def first():
            with connection.execute_wrapper(hold_after(INSERT_MEMBERSHIP, held, release)):
                inventories.invite(as_(owner, inventory), invitee.phone_number)

        second = lambda: inventories.invite(as_(owner, inventory), invitee.phone_number)

        outcomes = self.race(first, second, held, release)

        assert outcomes["first"] == "ok"
        assert isinstance(outcomes["second"], Conflict)
        assert status_of(Membership.objects.get(user=invitee).pk) == "pending"

    def test_a_delete_waits_for_an_accept_and_then_deletes_the_new_membership(
        self, inventory, owner, invitee
    ):
        invite = inventories.invite(as_(owner, inventory), invitee.phone_number)
        actor = as_(owner, inventory, "owner")
        held, release = threading.Event(), threading.Event()

        def accept():
            with connection.execute_wrapper(hold_after(UPDATE_MEMBERSHIP, held, release)):
                inventories.accept_invite(invitee, invite.id)

        outcomes = self.race(accept, lambda: inventories.delete_inventory(actor), held, release)

        assert outcomes == {"first": "ok", "second": "ok"}
        assert not Inventory.objects.exists()
        assert not Membership.objects.exists()

    def test_an_accept_waits_for_a_delete_and_is_not_found(self, inventory, owner, invitee):
        invite = inventories.invite(as_(owner, inventory), invitee.phone_number)
        actor = as_(owner, inventory, "owner")
        held, release = threading.Event(), threading.Event()

        def delete():
            with transaction.atomic():
                inventories.delete_inventory(actor)
                held.set()
                assert release.wait(10)

        outcomes = self.race(
            delete, lambda: inventories.accept_invite(invitee, invite.id), held, release
        )

        assert outcomes["first"] == "ok"
        assert isinstance(outcomes["second"], NotFound)
        assert not Inventory.objects.exists()
        assert not Membership.objects.exists()

    def test_a_revoke_waits_for_an_accept_and_conflicts(self, inventory, owner, invitee):
        invite = inventories.invite(as_(owner, inventory), invitee.phone_number)
        held, release = threading.Event(), threading.Event()

        def accept():
            with connection.execute_wrapper(hold_after(UPDATE_MEMBERSHIP, held, release)):
                inventories.accept_invite(invitee, invite.id)

        revoke = lambda: inventories.revoke_invite(owner, invite.id)

        outcomes = self.race(accept, revoke, held, release)

        assert outcomes["first"] == "ok"
        assert isinstance(outcomes["second"], Conflict)
        assert status_of(invite.pk) == "active"
