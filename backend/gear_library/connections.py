"""Every change to a connection between two users.

A pair of users has at most one `Connection` row. A pending row is a request from
`requested_by` to the other user; an accepted row connects them both ways. Declining,
cancelling and removing delete the row, so a pair keeps no history and can start again.

No action takes an explicit lock. Requesting inserts a pending row, and the unique index
on the pair refuses it when the pair already has a row. The request then accepts the
other user's pending request with one conditional update, or gets `Conflict`. Accepting is
one conditional update from pending, and declining, cancelling and removing are each one
conditional delete on the status the action needs. When that matches no row, a row that
is gone gets `NotFound` and one in the other status gets `Conflict`, except that accepting
an accepted connection returns it.
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from .errors import NO_SUCH_USER, Conflict, violates
from .models import ONE_CONNECTION_PER_PAIR, Connection, ConnectionStatus, ordered_pair

User = get_user_model()

OWN_NUMBER = "You cannot send a request to yourself."
ALREADY_CONNECTED = "You are already connected."
ALREADY_REQUESTED = "You have already sent this user a request."
CHANGED = "This connection changed. Try again."
NOT_FOUND = "Connection not found."
NOT_PENDING = "This is not a pending request."
NOT_CONNECTED = "You are not connected."
RECEIVER_ONLY = "Only the user who received the request can do this."
REQUESTER_ONLY = "Only the user who sent the request can do this."


def request_connection(user, phone_number):
    """Sends a request to the user with `phone_number` and returns the new pending row.
    When that user's own request to the caller is pending, accepts it instead and returns
    the accepted row."""
    other = User.objects.filter(phone_number=phone_number).first()
    if other is None:
        raise ValidationError({"phone_number": [NO_SUCH_USER]})
    if other.pk == user.pk:
        raise ValidationError({"phone_number": [OWN_NUMBER]})
    first, second = ordered_pair(user, other)
    try:
        with transaction.atomic():
            return Connection.objects.create(
                first_user_id=first,
                second_user_id=second,
                requested_by=user,
                status=ConnectionStatus.PENDING,
            )
    except IntegrityError as error:
        if not violates(error, ONE_CONNECTION_PER_PAIR):
            raise
    accepted = _accept_theirs(user, other)
    if accepted is not None:
        return accepted
    existing = Connection.objects.between(user, other).first()
    if existing is None:
        raise Conflict(CHANGED)
    if existing.status == ConnectionStatus.ACCEPTED:
        raise Conflict(ALREADY_CONNECTED)
    if existing.requested_by_id == user.pk:
        raise Conflict(ALREADY_REQUESTED)
    # Deleted and requested again by the other user since the update above.
    raise Conflict(CHANGED)


def _accept_theirs(user, other):
    """Accepts `other`'s pending request to `user` and returns it, or returns None when
    there is none."""
    pair = Connection.objects.between(user, other)
    with transaction.atomic():
        if not pair.pending().filter(requested_by=other).update(
            status=ConnectionStatus.ACCEPTED
        ):
            return None
        return pair.select_related("first_user", "second_user").get()


def _connection_for(user, connection_id):
    """The connection `connection_id`, if `user` is one of its two users. Anyone else gets
    `NotFound`. Its status is not checked here."""
    found = (
        Connection.objects.involving(user)
        .select_related("first_user", "second_user")
        .filter(pk=connection_id)
        .first()
    )
    if found is None:
        raise NotFound(NOT_FOUND)
    return found


def _refuse_requester(found, user):
    if found.requested_by_id == user.pk:
        raise PermissionDenied(RECEIVER_ONLY)


def _gone_or_conflict(connection_id, wrong_status):
    """Called when a conditional change matched no row."""
    if Connection.objects.filter(pk=connection_id).exists():
        raise Conflict(wrong_status)
    raise NotFound(NOT_FOUND)


def _delete_if(found, status, wrong_status):
    if Connection.objects.filter(pk=found.pk, status=status).delete()[0]:
        return
    _gone_or_conflict(found.pk, wrong_status)


def accept(user, connection_id):
    """Accepts a pending request the caller received and returns the connection. Accepting
    a connection that is already accepted returns it unchanged."""
    found = _connection_for(user, connection_id)
    _refuse_requester(found, user)
    if not Connection.objects.pending().filter(pk=found.pk).update(
        status=ConnectionStatus.ACCEPTED
    ):
        if not Connection.objects.accepted().filter(pk=found.pk).exists():
            _gone_or_conflict(found.pk, NOT_PENDING)
    found.status = ConnectionStatus.ACCEPTED
    return found


def decline(user, connection_id):
    """Deletes a pending request the caller received."""
    found = _connection_for(user, connection_id)
    _refuse_requester(found, user)
    _delete_if(found, ConnectionStatus.PENDING, NOT_PENDING)


def cancel(user, connection_id):
    """Deletes a pending request the caller sent."""
    found = _connection_for(user, connection_id)
    if found.requested_by_id != user.pk:
        raise PermissionDenied(REQUESTER_ONLY)
    _delete_if(found, ConnectionStatus.PENDING, NOT_PENDING)


def remove(user, connection_id):
    """Deletes an accepted connection. Either user may."""
    found = _connection_for(user, connection_id)
    _delete_if(found, ConnectionStatus.ACCEPTED, NOT_CONNECTED)
