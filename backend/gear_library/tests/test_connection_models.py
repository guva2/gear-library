import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from gear_library.models import Connection, ordered_pair

User = get_user_model()


def make_user(n):
    return User.objects.create_user(
        phone_number=f"555223{n:04d}", first_name="User", last_name=str(n)
    )


@pytest.fixture
def ada():
    return make_user(1)


@pytest.fixture
def bob():
    return make_user(2)


def connect(first, second, requested_by=None, status="pending"):
    return Connection.objects.create(
        first_user=first,
        second_user=second,
        requested_by=requested_by or first,
        status=status,
    )


def assert_rejected_by(constraint, create):
    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        create()


@pytest.mark.django_db
class TestConnection:
    def test_ordered_pair_puts_the_lower_id_first(self, ada, bob):
        assert ordered_pair(bob, ada) == (ada.pk, bob.pk)
        assert ordered_pair(ada, bob) == (ada.pk, bob.pk)

    def test_ordered_pair_takes_user_ids(self, ada, bob):
        assert ordered_pair(bob.pk, ada) == (ada.pk, bob.pk)
        assert ordered_pair(ada.pk, bob.pk) == (ada.pk, bob.pk)

    def test_the_lower_user_id_must_come_first(self, ada, bob):
        assert_rejected_by(
            "gear_library_connection_ordered_pair", lambda: connect(bob, ada, requested_by=bob)
        )

    def test_a_user_cannot_connect_to_themselves(self, ada):
        assert_rejected_by("gear_library_connection_ordered_pair", lambda: connect(ada, ada))

    def test_the_requester_must_be_one_of_the_two_users(self, ada, bob):
        carl = make_user(3)

        assert_rejected_by(
            "gear_library_connection_requested_by_a_user",
            lambda: connect(ada, bob, requested_by=carl),
        )

    @pytest.mark.parametrize("status", ["declined", ""])
    def test_status_check_rejects_an_unknown_status(self, ada, bob, status):
        assert_rejected_by(
            "gear_library_connection_status_valid", lambda: connect(ada, bob, status=status)
        )

    @pytest.mark.parametrize("first_status", ["pending", "accepted"])
    def test_a_pair_has_one_row_whoever_requested_it(self, ada, bob, first_status):
        connect(ada, bob, status=first_status)

        for requested_by in [ada, bob]:
            assert_rejected_by(
                "gear_library_connection_one_per_pair",
                lambda: connect(ada, bob, requested_by=requested_by),
            )

    @pytest.mark.parametrize("person", ["first_user", "second_user", "requested_by"])
    def test_deleting_a_connected_user_is_refused(self, ada, bob, person):
        connection = connect(ada, bob, requested_by=bob)

        with pytest.raises(ProtectedError):
            getattr(connection, person).delete()

    def test_between_finds_the_pair_in_either_order(self, ada, bob):
        connection = connect(ada, bob)
        make_user(3)

        assert list(Connection.objects.between(bob, ada)) == [connection]
        assert list(Connection.objects.between(ada, bob)) == [connection]

    def test_between_takes_user_ids(self, ada, bob):
        connection = connect(ada, bob)

        assert list(Connection.objects.between(bob.pk, ada.pk)) == [connection]
        assert list(Connection.objects.between(ada, bob.pk)) == [connection]

    def test_other_user_is_the_one_who_is_not_the_caller(self, ada, bob):
        connection = connect(ada, bob)

        assert connection.other_user(ada) == bob
        assert connection.other_user(bob) == ada
