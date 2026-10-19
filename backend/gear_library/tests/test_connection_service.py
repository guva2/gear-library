import threading

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from gear_library import connections
from gear_library.errors import Conflict
from gear_library.models import Connection, ordered_pair

from .test_inventory_service import hold_after, run_in_thread, wait_for_a_blocked_lock

User = get_user_model()


def make_user(n, first_name="User"):
    return User.objects.create_user(
        phone_number=f"555123{n:04d}", first_name=first_name, last_name=str(n)
    )


@pytest.fixture
def ada():
    return make_user(1, "Ada")


@pytest.fixture
def bob():
    return make_user(2, "Bob")


def add(requested_by, other, status="pending"):
    """A connection added straight to the database."""
    first, second = ordered_pair(requested_by, other)
    return Connection.objects.create(
        first_user=first, second_user=second, requested_by=requested_by, status=status
    )


def status_of(connection_id):
    row = Connection.objects.filter(pk=connection_id).first()
    return row and row.status


@pytest.mark.django_db
class TestRequest:
    @pytest.mark.parametrize("order", ["lower first", "higher first"])
    def test_stores_one_pending_row_with_the_pair_ordered(self, ada, bob, order):
        requester, other = (ada, bob) if order == "lower first" else (bob, ada)

        request = connections.request_connection(requester, other.phone_number)

        row = Connection.objects.get()
        assert row.pk == request.pk
        assert (row.first_user, row.second_user) == (ada, bob)
        assert (row.requested_by, row.status) == (requester, "pending")

    def test_an_unknown_phone_number_is_invalid(self, ada):
        with pytest.raises(ValidationError) as excinfo:
            connections.request_connection(ada, "5559999999")
        assert excinfo.value.detail == {"phone_number": ["No user has this phone number."]}

    def test_your_own_phone_number_is_invalid(self, ada):
        with pytest.raises(ValidationError) as excinfo:
            connections.request_connection(ada, ada.phone_number)
        assert excinfo.value.detail == {
            "phone_number": ["You cannot send a request to yourself."]
        }
        assert not Connection.objects.exists()

    @pytest.mark.parametrize("requested_by", ["ada", "bob"])
    def test_an_accepted_connection_conflicts(self, ada, bob, requested_by):
        users = {"ada": ada, "bob": bob}
        row = add(users[requested_by], ada if requested_by == "bob" else bob, "accepted")

        with pytest.raises(Conflict) as excinfo:
            connections.request_connection(ada, bob.phone_number)
        assert excinfo.value.detail == "You are already connected."
        assert status_of(row.pk) == "accepted"

    def test_a_second_request_to_the_same_user_conflicts(self, ada, bob):
        row = add(ada, bob)

        with pytest.raises(Conflict) as excinfo:
            connections.request_connection(ada, bob.phone_number)
        assert excinfo.value.detail == "You have already sent this user a request."
        assert (Connection.objects.get().pk, status_of(row.pk)) == (row.pk, "pending")

    def test_a_request_to_someone_whose_request_is_pending_accepts_it(self, ada, bob):
        theirs = add(bob, ada)

        result = connections.request_connection(ada, bob.phone_number)

        assert (result.pk, result.status, result.requested_by) == (theirs.pk, "accepted", bob)
        assert result.other_user(ada) == bob
        assert status_of(theirs.pk) == "accepted"

    def test_can_request_again_after_a_decline_cancel_or_remove(self, ada, bob):
        for finish in ["decline", "cancel", "remove"]:
            request = connections.request_connection(ada, bob.phone_number)
            if finish == "decline":
                connections.decline(bob, request.id)
            elif finish == "cancel":
                connections.cancel(ada, request.id)
            else:
                connections.accept(bob, request.id)
                connections.remove(ada, request.id)

        assert connections.request_connection(ada, bob.phone_number).status == "pending"

    def test_a_request_deleted_after_the_insert_failed_conflicts(self, ada, bob, monkeypatch):
        """The other user cancelled their request between this insert and the read."""
        add(bob, ada)
        accept_theirs = connections._accept_theirs

        def cancel_first(*args):
            Connection.objects.all().delete()
            return accept_theirs(*args)

        monkeypatch.setattr(connections, "_accept_theirs", cancel_first)

        with pytest.raises(Conflict) as excinfo:
            connections.request_connection(ada, bob.phone_number)
        assert excinfo.value.detail == "This connection changed. Try again."
        assert not Connection.objects.exists()


@pytest.mark.django_db
class TestAnswer:
    @pytest.fixture
    def request_(self, ada, bob):
        return add(ada, bob)

    def test_the_other_user_accepts(self, bob, request_):
        accepted = connections.accept(bob, request_.id)

        assert (accepted.pk, accepted.status) == (request_.pk, "accepted")
        assert status_of(request_.pk) == "accepted"

    def test_the_other_user_declines(self, bob, request_):
        connections.decline(bob, request_.id)

        assert status_of(request_.pk) is None

    def test_the_requester_cancels(self, ada, request_):
        connections.cancel(ada, request_.id)

        assert status_of(request_.pk) is None

    @pytest.mark.parametrize("by", ["ada", "bob"])
    def test_either_user_removes_an_accepted_connection(self, ada, bob, request_, by):
        connections.accept(bob, request_.id)

        connections.remove(ada if by == "ada" else bob, request_.id)

        assert status_of(request_.pk) is None

    @pytest.mark.parametrize(
        "action, by",
        [
            (connections.accept, "ada"),
            (connections.decline, "ada"),
            (connections.cancel, "bob"),
        ],
    )
    @pytest.mark.parametrize("state", ["pending", "accepted"])
    def test_the_wrong_one_of_the_two_is_forbidden(self, ada, bob, request_, action, by, state):
        if state == "accepted":
            connections.accept(bob, request_.id)

        with pytest.raises(PermissionDenied):
            action(ada if by == "ada" else bob, request_.id)
        assert status_of(request_.pk) == state

    @pytest.mark.parametrize(
        "action, by",
        [(connections.decline, "bob"), (connections.cancel, "ada")],
    )
    def test_answering_an_accepted_connection_conflicts(self, ada, bob, request_, action, by):
        connections.accept(bob, request_.id)

        with pytest.raises(Conflict) as excinfo:
            action(ada if by == "ada" else bob, request_.id)
        assert excinfo.value.detail == "This is not a pending request."
        assert status_of(request_.pk) == "accepted"

    def test_accepting_an_accepted_connection_returns_it(self, bob, request_):
        connections.accept(bob, request_.id)

        again = connections.accept(bob, request_.id)

        assert again.pk == request_.pk
        assert status_of(request_.pk) == "accepted"

    def test_removing_a_pending_request_conflicts(self, ada, request_):
        with pytest.raises(Conflict) as excinfo:
            connections.remove(ada, request_.id)
        assert excinfo.value.detail == "You are not connected."
        assert status_of(request_.pk) == "pending"

    ACTIONS = [
        (connections.accept, "bob"),
        (connections.decline, "bob"),
        (connections.cancel, "ada"),
        (connections.remove, "ada"),
    ]

    @pytest.mark.parametrize("action, by", ACTIONS)
    def test_a_connection_that_is_gone_is_not_found(self, ada, bob, request_, action, by):
        Connection.objects.all().delete()

        with pytest.raises(NotFound) as excinfo:
            action(ada if by == "ada" else bob, request_.id)
        assert excinfo.value.detail == "Connection not found."

    @pytest.mark.parametrize("action, by", ACTIONS)
    @pytest.mark.parametrize("state", ["pending", "accepted"])
    def test_anyone_else_gets_not_found_whatever_the_state(self, request_, action, by, state):
        Connection.objects.filter(pk=request_.pk).update(status=state)
        stranger = make_user(9)

        with pytest.raises(NotFound):
            action(stranger, request_.id)
        assert status_of(request_.pk) == state

    def hook_after_reading(self, monkeypatch, change):
        """Runs `change(found)` after the action has read the connection and checked
        access."""
        connection_for = connections._connection_for

        def change_after_reading(*args, **kwargs):
            found = connection_for(*args, **kwargs)
            change(found)
            return found

        monkeypatch.setattr(connections, "_connection_for", change_after_reading)

    @pytest.mark.parametrize("action, by", ACTIONS)
    def test_a_connection_deleted_after_it_was_read_is_not_found(
        self, ada, bob, request_, monkeypatch, action, by
    ):
        if action is connections.remove:
            connections.accept(bob, request_.id)
        self.hook_after_reading(
            monkeypatch, lambda found: Connection.objects.filter(pk=found.pk).delete()
        )

        with pytest.raises(NotFound):
            action(ada if by == "ada" else bob, request_.id)

    def test_a_request_accepted_after_it_was_read_is_returned_by_accept(
        self, bob, request_, monkeypatch
    ):
        self.hook_after_reading(
            monkeypatch,
            lambda found: Connection.objects.filter(pk=found.pk).update(status="accepted"),
        )

        assert connections.accept(bob, request_.id).pk == request_.pk

    @pytest.mark.parametrize("action, by", ACTIONS[1:3])
    def test_a_request_accepted_after_it_was_read_conflicts(
        self, ada, bob, request_, monkeypatch, action, by
    ):
        self.hook_after_reading(
            monkeypatch,
            lambda found: Connection.objects.filter(pk=found.pk).update(status="accepted"),
        )

        with pytest.raises(Conflict):
            action(ada if by == "ada" else bob, request_.id)
        assert status_of(request_.pk) == "accepted"


INSERT_CONNECTION = 'INSERT INTO "gear_library_connection" '
UPDATE_CONNECTION = 'UPDATE "gear_library_connection" '
DELETE_CONNECTION = 'DELETE FROM "gear_library_connection" '


@pytest.mark.django_db(transaction=True)
class TestCommittedRaces:
    """These tests commit for real: an insert or update waiting on another transaction's
    row learns the outcome only when that transaction commits."""

    @pytest.fixture
    def ada(self):
        return make_user(1, "Ada")

    @pytest.fixture
    def bob(self):
        return make_user(2, "Bob")

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

    def holding(self, sql_prefix, action):
        """`action` in a transaction that stays open after its first `sql_prefix`
        statement. Returns it with its `held` and `release` events."""
        held, release = threading.Event(), threading.Event()

        def run():
            hold = hold_after(sql_prefix, held, release)
            with connection.execute_wrapper(hold), transaction.atomic():
                action()

        return run, held, release

    def test_two_users_requesting_each_other_at_once_connect(self, ada, bob):
        first, held, release = self.holding(
            INSERT_CONNECTION, lambda: connections.request_connection(ada, bob.phone_number)
        )
        second = lambda: connections.request_connection(bob, ada.phone_number)

        outcomes = self.race(first, second, held, release)

        assert outcomes == {"first": "ok", "second": "ok"}
        row = Connection.objects.get()
        assert (row.status, row.requested_by) == ("accepted", ada)

    def test_a_second_request_waits_for_the_first_and_conflicts(self, ada, bob):
        first, held, release = self.holding(
            INSERT_CONNECTION, lambda: connections.request_connection(ada, bob.phone_number)
        )
        second = lambda: connections.request_connection(ada, bob.phone_number)

        outcomes = self.race(first, second, held, release)

        assert outcomes["first"] == "ok"
        assert isinstance(outcomes["second"], Conflict)
        assert Connection.objects.get().status == "pending"

    def test_a_crossed_request_waits_for_a_cancel_and_becomes_a_new_request(self, ada, bob):
        request = connections.request_connection(bob, ada.phone_number)
        first, held, release = self.holding(
            DELETE_CONNECTION, lambda: connections.cancel(bob, request.id)
        )
        second = lambda: connections.request_connection(ada, bob.phone_number)

        outcomes = self.race(first, second, held, release)

        assert outcomes == {"first": "ok", "second": "ok"}
        row = Connection.objects.get()
        assert (row.status, row.requested_by) == ("pending", ada)

    def test_a_cancel_waits_for_a_crossed_request_and_conflicts(self, ada, bob):
        request = connections.request_connection(bob, ada.phone_number)
        first, held, release = self.holding(
            UPDATE_CONNECTION, lambda: connections.request_connection(ada, bob.phone_number)
        )
        second = lambda: connections.cancel(bob, request.id)

        outcomes = self.race(first, second, held, release)

        assert outcomes["first"] == "ok"
        assert isinstance(outcomes["second"], Conflict)
        assert Connection.objects.get().status == "accepted"

    def test_a_decline_waits_for_a_cancel_and_is_not_found(self, ada, bob):
        request = connections.request_connection(ada, bob.phone_number)
        first, held, release = self.holding(
            DELETE_CONNECTION, lambda: connections.cancel(ada, request.id)
        )
        second = lambda: connections.decline(bob, request.id)

        outcomes = self.race(first, second, held, release)

        assert outcomes["first"] == "ok"
        assert isinstance(outcomes["second"], NotFound)
        assert not Connection.objects.exists()

    def test_a_cancel_waits_for_an_accept_and_conflicts(self, ada, bob):
        request = connections.request_connection(ada, bob.phone_number)
        first, held, release = self.holding(
            UPDATE_CONNECTION, lambda: connections.accept(bob, request.id)
        )
        second = lambda: connections.cancel(ada, request.id)

        outcomes = self.race(first, second, held, release)

        assert outcomes["first"] == "ok"
        assert isinstance(outcomes["second"], Conflict)
        assert Connection.objects.get().status == "accepted"
