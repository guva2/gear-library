import threading

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from rest_framework.exceptions import NotFound, ValidationError

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
        first_user_id=first, second_user_id=second, requested_by=requested_by, status=status
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
        for finish in ["delete", "remove"]:
            request = connections.request_connection(ada, bob.phone_number)
            if finish == "delete":
                connections.delete_request(request)
            else:
                connections.accept(request)
                connections.remove(request)

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
    """Each action takes the connection as the caller read it."""

    @pytest.fixture
    def request_(self, ada, bob):
        return add(ada, bob)

    def test_accepting(self, request_):
        accepted = connections.accept(request_)

        assert (accepted.pk, accepted.status) == (request_.pk, "accepted")
        assert status_of(request_.pk) == "accepted"

    def test_declining_or_cancelling(self, request_):
        connections.delete_request(request_)

        assert status_of(request_.pk) is None

    def test_removing_an_accepted_connection(self, request_):
        connections.accept(request_)

        connections.remove(request_)

        assert status_of(request_.pk) is None

    def test_declining_or_cancelling_an_accepted_connection_conflicts(self, request_):
        connections.accept(request_)

        with pytest.raises(Conflict) as excinfo:
            connections.delete_request(request_)
        assert excinfo.value.detail == "This is not a pending request."
        assert status_of(request_.pk) == "accepted"

    def test_accepting_an_accepted_connection_returns_it(self, request_):
        connections.accept(request_)

        again = connections.accept(request_)

        assert again.pk == request_.pk
        assert status_of(request_.pk) == "accepted"

    def test_removing_a_pending_request_conflicts(self, request_):
        with pytest.raises(Conflict) as excinfo:
            connections.remove(request_)
        assert excinfo.value.detail == "You are not connected."
        assert status_of(request_.pk) == "pending"

    @pytest.mark.parametrize(
        "action", [connections.accept, connections.delete_request, connections.remove]
    )
    def test_a_connection_deleted_after_it_was_read_is_not_found(self, request_, action):
        Connection.objects.all().delete()

        with pytest.raises(NotFound) as excinfo:
            action(request_)
        assert excinfo.value.detail == "Connection not found."

    def test_a_request_accepted_after_it_was_read_is_returned_by_accept(self, request_):
        Connection.objects.filter(pk=request_.pk).update(status="accepted")

        assert connections.accept(request_).pk == request_.pk


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
            DELETE_CONNECTION, lambda: connections.delete_request(request)
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
        second = lambda: connections.delete_request(request)

        outcomes = self.race(first, second, held, release)

        assert outcomes["first"] == "ok"
        assert isinstance(outcomes["second"], Conflict)
        assert Connection.objects.get().status == "accepted"

    def test_a_decline_waits_for_a_cancel_and_is_not_found(self, ada, bob):
        request = connections.request_connection(ada, bob.phone_number)
        first, held, release = self.holding(
            DELETE_CONNECTION, lambda: connections.delete_request(request)
        )
        second = lambda: connections.delete_request(request)

        outcomes = self.race(first, second, held, release)

        assert outcomes["first"] == "ok"
        assert isinstance(outcomes["second"], NotFound)
        assert not Connection.objects.exists()

    def test_a_cancel_waits_for_an_accept_and_conflicts(self, ada, bob):
        request = connections.request_connection(ada, bob.phone_number)
        first, held, release = self.holding(
            UPDATE_CONNECTION, lambda: connections.accept(request)
        )
        second = lambda: connections.delete_request(request)

        outcomes = self.race(first, second, held, release)

        assert outcomes["first"] == "ok"
        assert isinstance(outcomes["second"], Conflict)
        assert Connection.objects.get().status == "accepted"
