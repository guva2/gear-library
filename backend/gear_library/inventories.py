"""Every change to an inventory and its memberships.

A membership is `active` or `pending`; a pending one is an invite. Every access decision
reads memberships through `Membership.objects.active()`, so a pending member is a
non-member everywhere outside the invite actions.

The functions that take `actor`, the caller's membership, run with the inventory row
locked by `lock_inventory`, taken before the caller's membership was read. Changes to one
inventory therefore run one at a time, and each sees the memberships and owners as they
are. Leaving, being removed and taking the `member` role also delete the user's listings
in the inventory and cancel the pending requests for those items; leaving and being
removed also cancel the user's own pending requests made through the inventory. Deleting
cancels the pending requests made through the inventory, then deletes its memberships and
the row.

Inviting inserts a pending membership; the unique index on (inventory, user) refuses a
user who is already a member or invited, with `Conflict`. Accepting, declining and
revoking take no inventory lock. Accepting is one conditional update from pending to
active, and accepting an active membership again returns it. Declining and revoking are
each one conditional delete of a pending membership. A membership that is gone gets
`NotFound`, and one that is active where pending was required gets `Conflict`.
"""

from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound, ValidationError

from .errors import Conflict, violates
from .models import (
    ONE_MEMBERSHIP_PER_USER,
    Connection,
    Inventory,
    InventoryItem,
    Item,
    Membership,
    MembershipStatus,
    Role,
)

_RANK = {Role.MEMBER: 0, Role.ADMIN: 1, Role.OWNER: 2}

INVENTORY_NOT_FOUND = "Inventory not found."
INVITE_NOT_FOUND = "Invite not found."
MEMBER_NOT_FOUND = "This user is not a member of the inventory."
ROLE_REQUIRED = {
    Role.ADMIN: "Only admins and owners can do this.",
    Role.OWNER: "Only owners can do this.",
}
LAST_OWNER = "An inventory must keep at least one owner."
NOT_PENDING = "This is not a pending invite."
ALREADY_IN = "This user is already a member or has a pending invite."
NOT_A_CONNECTION = "You can invite only your connections."


def has_role(membership, role):
    """True when `membership` has `role` or a higher one."""
    return _RANK[membership.role] >= _RANK[role]


def lock_inventory(inventory_id):
    """Locks the inventory row, if there is one, until the transaction ends."""
    Inventory.objects.select_for_update().filter(pk=inventory_id).first()


def _delete_listings(membership):
    """Deletes the listings of `membership`'s user's items in its inventory, and cancels the
    pending requests for those items made through it."""
    InventoryItem.objects.filter(
        inventory_id=membership.inventory_id, item__owner_id=membership.user_id
    ).delete()
    Item.objects.filter(owner_id=membership.user_id).cancel_requests_through(
        membership.inventory_id
    )


def _target_membership(inventory_id, user_id):
    membership = (
        Membership.objects.active().filter(inventory_id=inventory_id, user_id=user_id).first()
    )
    if membership is None:
        raise NotFound(MEMBER_NOT_FOUND)
    return membership


def _refuse_losing_last_owner(membership):
    """Called before `membership` stops being an owner, with the inventory locked."""
    if membership.role != Role.OWNER:
        return
    owners = Membership.objects.active().filter(
        inventory_id=membership.inventory_id, role=Role.OWNER
    )
    if not owners.exclude(pk=membership.pk).exists():
        raise Conflict(LAST_OWNER)


@transaction.atomic
def create_inventory(user, name):
    inventory = Inventory.objects.create(name=name)
    return Membership.objects.create(
        inventory=inventory, user=user, role=Role.OWNER, status=MembershipStatus.ACTIVE
    )


# `actor` below is the caller's membership, which has the role the action needs.


def rename_inventory(actor, name):
    """`actor` must be an owner."""
    Inventory.objects.filter(pk=actor.inventory_id).update(name=name)
    actor.inventory.name = name
    return actor


def delete_inventory(actor):
    """`actor` must be an owner."""
    # First: the delete sets `loan_inventory` to null, and `gear_library_item_loan_state`
    # refuses a pending request without one.
    Item.objects.cancel_requests_through(actor.inventory_id)
    actor.inventory.delete()


def set_role(actor, member_user_id, role):
    """`actor` must be an owner."""
    target = _target_membership(actor.inventory_id, member_user_id)
    if role != Role.OWNER:
        _refuse_losing_last_owner(target)
    if not Membership.objects.active().filter(pk=target.pk).update(role=role):
        raise NotFound(MEMBER_NOT_FOUND)
    if role == Role.MEMBER:
        _delete_listings(target)
    target.role = role
    return target


def remove_member(actor, member_user_id):
    """Removes the member `member_user_id`. Removing yourself is leaving, which any member
    may do; to remove someone else, `actor` must be an owner."""
    leaving = member_user_id == actor.user_id
    target = actor if leaving else _target_membership(actor.inventory_id, member_user_id)
    _refuse_losing_last_owner(target)
    _delete_listings(target)
    Item.objects.filter(borrower_id=target.user_id).cancel_requests_through(actor.inventory_id)
    target.delete()


def invite(actor, user_id):
    """Invites the user `user_id` by adding a pending membership. `actor` must be an admin
    or owner, and the invitee one of the actor's accepted connections. Anyone else is a
    `ValidationError` with one message, so the actor learns nothing about other users."""
    if not Connection.objects.accepted().between(actor.user_id, user_id).exists():
        raise ValidationError({"user_id": [NOT_A_CONNECTION]})
    try:
        with transaction.atomic():
            return Membership.objects.create(
                inventory_id=actor.inventory_id,
                user_id=user_id,
                role=Role.MEMBER,
                status=MembershipStatus.PENDING,
                invited_by_id=actor.user_id,
            )
    except IntegrityError as error:
        if violates(error, ONE_MEMBERSHIP_PER_USER):
            raise Conflict(ALREADY_IN)
        raise


# `invite` below is a membership the caller may act on as an invite, whatever its status:
# the invited user's own to accept or decline, or one an admin or owner of its inventory
# revokes.


def delete_invite(invite):
    """Declines or revokes `invite` by deleting it if it is still pending. Raises
    `NotFound` if it is gone and `Conflict` if it is active."""
    if Membership.objects.pending().filter(pk=invite.pk).delete()[0]:
        return
    if Membership.objects.filter(pk=invite.pk).exists():
        raise Conflict(NOT_PENDING)
    raise NotFound(INVITE_NOT_FOUND)


def accept_invite(invite):
    """Activates the pending membership and returns it. Accepting a membership that is
    already active returns it unchanged."""
    this = Membership.objects.filter(pk=invite.pk)
    this.pending().update(status=MembershipStatus.ACTIVE)
    membership = this.active().select_related("inventory").first()
    if membership is None:
        raise NotFound(INVITE_NOT_FOUND)
    return membership
