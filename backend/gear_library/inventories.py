"""Every change to an inventory, its memberships and its invites.

No change takes a row lock. Accept, decline and revoke are each one conditional update
that matches only a pending invite, and the unique indexes on memberships and pending
invites refuse duplicates. An invite change that loses a race gets `Conflict` (409).

The at-least-one-owner rule is a read followed by a write, so two owners stepping down at
the same moment can both pass it.
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from .models import (
    ONE_MEMBERSHIP_PER_USER,
    ONE_PENDING_INVITE,
    Inventory,
    InventoryInvite,
    InviteStatus,
    Membership,
    Role,
)

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
ALREADY_A_MEMBER = "You are already a member."


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
        Membership.objects.select_related("inventory")
        .filter(inventory_id=inventory_id, user=user)
        .first()
    )
    if membership is None:
        raise NotFound(INVENTORY_NOT_FOUND)
    if not has_role(membership, role):
        raise PermissionDenied(ROLE_REQUIRED[role])
    return membership


def _violates(error, constraint):
    """True when the database raised `error` for the constraint named `constraint`."""
    diag = getattr(error.__cause__, "diag", None)
    return diag is not None and diag.constraint_name == constraint


def _target_membership(inventory_id, user_id):
    membership = Membership.objects.filter(inventory_id=inventory_id, user_id=user_id).first()
    if membership is None:
        raise NotFound(MEMBER_NOT_FOUND)
    return membership


def _refuse_losing_last_owner(membership):
    """Called before `membership` stops being an owner."""
    if membership.role != Role.OWNER:
        return
    owners = Membership.objects.filter(inventory_id=membership.inventory_id, role=Role.OWNER)
    if not owners.exclude(pk=membership.pk).exists():
        raise Conflict(LAST_OWNER)


@transaction.atomic
def create_inventory(user, name):
    inventory = Inventory.objects.create(name=name)
    return Membership.objects.create(inventory=inventory, user=user, role=Role.OWNER)


# `actor` below is the caller's membership from `get_membership` with the role the action
# needs. These functions do not check the role again.


def rename_inventory(actor, name):
    """`actor` must be an owner."""
    if not Inventory.objects.filter(pk=actor.inventory_id).update(name=name):
        raise NotFound(INVENTORY_NOT_FOUND)
    actor.inventory.name = name
    return actor


def delete_inventory(actor):
    """`actor` must be an owner."""
    Inventory.objects.filter(pk=actor.inventory_id).delete()


def set_role(actor, member_user_id, role):
    """`actor` must be an owner."""
    target = _target_membership(actor.inventory_id, member_user_id)
    if role != Role.OWNER:
        _refuse_losing_last_owner(target)
    if not Membership.objects.filter(pk=target.pk).update(role=role):
        raise NotFound(MEMBER_NOT_FOUND)
    target.role = role
    return target


def remove_member(user, inventory_id, member_user_id):
    """Removes a member. Removing yourself is leaving, which any member may do."""
    leaving = member_user_id == user.id
    actor = get_membership(user, inventory_id, Role.MEMBER if leaving else Role.OWNER)
    target = actor if leaving else _target_membership(inventory_id, member_user_id)
    _refuse_losing_last_owner(target)
    target.delete()


def invite(actor, phone_number):
    """Invites the user with `phone_number`. `actor` must be an admin or owner, checked
    before this looks the number up, so a plain member or outsider learns nothing. An
    admin or owner can still tell whether a number has an account: an unknown one is a
    `ValidationError`."""
    invitee = User.objects.filter(phone_number=phone_number).first()
    if invitee is None:
        raise ValidationError({"phone_number": [NO_SUCH_USER]})
    if Membership.objects.filter(inventory_id=actor.inventory_id, user=invitee).exists():
        raise Conflict("This user is already a member.")
    try:
        with transaction.atomic():
            return InventoryInvite.objects.create(
                inventory_id=actor.inventory_id, invitee=invitee, invited_by_id=actor.user_id
            )
    except IntegrityError as error:
        if _violates(error, ONE_PENDING_INVITE):
            raise Conflict("This user already has a pending invite.")
        raise


def _invite_for(user, invite_id, by_invitee):
    """The invite, if `user` may see it and act on it. Its status is not checked here.

    The invitee and the inventory's admins and owners see the invite; anyone else gets
    `NotFound`. The action is the invitee's when `by_invitee`, otherwise an admin's or an
    owner's; a caller who sees the invite but may not act gets `PermissionDenied`.
    """
    invite = InventoryInvite.objects.filter(pk=invite_id).first()
    if invite is None:
        raise NotFound(INVITE_NOT_FOUND)
    is_invitee = invite.invitee_id == user.id
    membership = Membership.objects.filter(inventory_id=invite.inventory_id, user=user).first()
    is_admin = membership is not None and has_role(membership, Role.ADMIN)
    if not (is_invitee or is_admin):
        raise NotFound(INVITE_NOT_FOUND)
    if not (is_invitee if by_invitee else is_admin):
        raise PermissionDenied("You cannot do this with this invite.")
    return invite


def _finish(invite, status):
    """Moves `invite` from pending to `status`, or raises `Conflict` if it is no longer
    pending."""
    pending = InventoryInvite.objects.filter(pk=invite.pk, status=InviteStatus.PENDING)
    if not pending.update(status=status):
        raise Conflict(NOT_PENDING)


def accept_invite(user, invite_id):
    invite = _invite_for(user, invite_id, by_invitee=True)
    try:
        with transaction.atomic():
            _finish(invite, InviteStatus.ACCEPTED)
            return Membership.objects.create(
                inventory_id=invite.inventory_id, user=user, role=Role.MEMBER
            )
    except IntegrityError as error:
        if _violates(error, ONE_MEMBERSHIP_PER_USER):
            raise Conflict(ALREADY_A_MEMBER)
        raise


def decline_invite(user, invite_id):
    _finish(_invite_for(user, invite_id, by_invitee=True), InviteStatus.DECLINED)


def revoke_invite(user, invite_id):
    _finish(_invite_for(user, invite_id, by_invitee=False), InviteStatus.REVOKED)
