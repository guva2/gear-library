"""Every change to an inventory and its memberships.

A membership is `active` or `pending`; a pending one is an invite. Every access decision
reads memberships through `Membership.objects.active()`, so a pending member is a
non-member everywhere outside the invite actions.

Setting a role and removing a member, which includes leaving, lock the inventory row and
then re-read the caller's membership and the owners, so an inventory always keeps an
owner. Deleting is one `DELETE` of the inventory row, and the database deletes its
memberships in that statement. Renaming and the invite actions take no lock.

Inviting inserts a pending membership; the unique index on (inventory, user) refuses a
user who is already a member or invited, with `Conflict`. Accepting is one conditional
update from pending to active, and accepting an active membership again returns it.
Declining and revoking are each one conditional delete of a pending membership. A
membership that is gone gets `NotFound`, and one that is active where pending was required
gets `Conflict`.

Membership foreign keys are checked when the transaction commits. An invite whose
inventory was deleted first gets `NotFound` at commit.
"""

import functools

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from .models import ONE_MEMBERSHIP_PER_USER, Inventory, Membership, MembershipStatus, Role

User = get_user_model()

_RANK = {Role.MEMBER: 0, Role.ADMIN: 1, Role.OWNER: 2}

INVENTORY_NOT_FOUND = "Inventory not found."
INVITE_NOT_FOUND = "Invite not found."
MEMBER_NOT_FOUND = "This user is not a member of the inventory."
ROLE_REQUIRED = {
    Role.ADMIN: "Only admins and owners can do this.",
    Role.OWNER: "Only owners can do this.",
}
LAST_OWNER = "An inventory must keep at least one owner."
NO_SUCH_USER = "No user has this phone number."
NOT_PENDING = "This invite is no longer pending."
ALREADY_IN = "This user is already a member or has a pending invite."


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The request conflicts with the current state."
    default_code = "conflict"


def has_role(membership, role):
    """True when `membership` has `role` or a higher one."""
    return _RANK[membership.role] >= _RANK[role]


def get_membership(user, inventory_id, role=Role.MEMBER):
    """The caller's membership. A non-member gets `NotFound`, and a member without `role`
    or a higher one gets `PermissionDenied`."""
    membership = (
        Membership.objects.active()
        .select_related("inventory")
        .filter(inventory_id=inventory_id, user=user)
        .first()
    )
    if membership is None:
        raise NotFound(INVENTORY_NOT_FOUND)
    if not has_role(membership, role):
        raise PermissionDenied(ROLE_REQUIRED[role])
    return membership


def _violates(error, *constraints):
    """True when the database raised `error` for one of the constraints named."""
    diag = getattr(error.__cause__, "diag", None)
    return diag is not None and diag.constraint_name in constraints


@functools.cache
def _inventory_foreign_key():
    """The name of the foreign key from memberships to the inventory."""
    target = (Inventory._meta.db_table, Inventory._meta.pk.column)
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(
            cursor, Membership._meta.db_table
        )
    (name,) = (name for name, c in constraints.items() if c["foreign_key"] == target)
    return name


def _lock_inventory(inventory_id):
    inventory = Inventory.objects.select_for_update().filter(pk=inventory_id).first()
    if inventory is None:
        raise NotFound(INVENTORY_NOT_FOUND)
    return inventory


def _lock_as(user_id, inventory_id, role):
    """Locks the inventory and returns the caller's membership, which must have `role`."""
    inventory = _lock_inventory(inventory_id)
    membership = Membership.objects.active().filter(inventory=inventory, user_id=user_id).first()
    if membership is None:
        raise NotFound(INVENTORY_NOT_FOUND)
    membership.inventory = inventory
    if not has_role(membership, role):
        raise PermissionDenied(ROLE_REQUIRED[role])
    return membership


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


# `actor` below is the caller's membership from `get_membership` with the role the action
# needs. Only `set_role` checks the role again.


def rename_inventory(actor, name):
    """`actor` must be an owner."""
    if not Inventory.objects.filter(pk=actor.inventory_id).update(name=name):
        raise NotFound(INVENTORY_NOT_FOUND)
    actor.inventory.name = name
    return actor


def delete_inventory(actor):
    """`actor` must be an owner."""
    Inventory.objects.filter(pk=actor.inventory_id).delete()


@transaction.atomic
def set_role(actor, member_user_id, role):
    """`actor` must be an owner, and is checked again with the inventory locked."""
    actor = _lock_as(actor.user_id, actor.inventory_id, Role.OWNER)
    target = _target_membership(actor.inventory_id, member_user_id)
    if role != Role.OWNER:
        _refuse_losing_last_owner(target)
    if not Membership.objects.active().filter(pk=target.pk).update(role=role):
        raise NotFound(MEMBER_NOT_FOUND)
    target.role = role
    return target


@transaction.atomic
def remove_member(user, inventory_id, member_user_id):
    """Removes a member. Removing yourself is leaving, which any member may do."""
    leaving = member_user_id == user.id
    actor = _lock_as(user.id, inventory_id, Role.MEMBER if leaving else Role.OWNER)
    target = actor if leaving else _target_membership(inventory_id, member_user_id)
    _refuse_losing_last_owner(target)
    target.delete()


def invite(actor, phone_number):
    """Invites the user with `phone_number` by adding a pending membership. `actor` must be
    an admin or owner, checked before this looks the number up, so a plain member or
    outsider learns nothing. An admin or owner can still tell whether a number has an
    account: an unknown one is a `ValidationError`."""
    invitee = User.objects.filter(phone_number=phone_number).first()
    if invitee is None:
        raise ValidationError({"phone_number": [NO_SUCH_USER]})
    try:
        with transaction.atomic():
            return Membership.objects.create(
                inventory_id=actor.inventory_id,
                user=invitee,
                role=Role.MEMBER,
                status=MembershipStatus.PENDING,
                invited_by_id=actor.user_id,
            )
    except IntegrityError as error:
        if _violates(error, ONE_MEMBERSHIP_PER_USER):
            raise Conflict(ALREADY_IN)
        if _violates(error, _inventory_foreign_key()):
            raise NotFound(INVENTORY_NOT_FOUND)
        raise


def _invite_for(user, invite_id, by_invitee):
    """The membership `invite_id`, if `user` may see it as an invite and act on it. Its
    status is not checked here.

    The invited user and the inventory's admins and owners see it; anyone else gets
    `NotFound`. The action is the invited user's when `by_invitee`, otherwise an admin's or
    an owner's; a caller who sees it but may not act gets `PermissionDenied`.
    """
    invite = Membership.objects.filter(pk=invite_id).first()
    if invite is None:
        raise NotFound(INVITE_NOT_FOUND)
    is_invitee = invite.user_id == user.id
    own = Membership.objects.active().filter(inventory_id=invite.inventory_id, user=user).first()
    is_admin = own is not None and has_role(own, Role.ADMIN)
    if not (is_invitee or is_admin):
        raise NotFound(INVITE_NOT_FOUND)
    if not (is_invitee if by_invitee else is_admin):
        raise PermissionDenied("You cannot do this with this invite.")
    return invite


def _delete_pending(invite):
    """Deletes `invite` if it is still pending. Raises `NotFound` if it is gone and
    `Conflict` if it was accepted."""
    if Membership.objects.pending().filter(pk=invite.pk).delete()[0]:
        return
    if Membership.objects.filter(pk=invite.pk).exists():
        raise Conflict(NOT_PENDING)
    raise NotFound(INVITE_NOT_FOUND)


def accept_invite(user, invite_id):
    """Activates the caller's pending membership and returns it. Accepting a membership
    that is already active returns it unchanged."""
    invite = _invite_for(user, invite_id, by_invitee=True)
    mine = Membership.objects.filter(pk=invite.pk, user=user)
    with transaction.atomic():
        mine.pending().update(status=MembershipStatus.ACTIVE)
        membership = mine.active().select_related("inventory").first()
    if membership is None:
        raise NotFound(INVITE_NOT_FOUND)
    return membership


def decline_invite(user, invite_id):
    _delete_pending(_invite_for(user, invite_id, by_invitee=True))


def revoke_invite(user, invite_id):
    _delete_pending(_invite_for(user, invite_id, by_invitee=False))
