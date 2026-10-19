"""Every change to an inventory, its memberships and its invites.

Setting a role and removing a member, which includes leaving, lock the inventory row and
then re-read the caller's membership and the owners, so an inventory always keeps an
owner. Accepting takes `FOR KEY SHARE` on the inventory row. Deleting is one `DELETE` of
the inventory row, and the database deletes its memberships and invites in that statement.
Every one of these locks the inventory row before any membership or invite row. Renaming
and the other invite changes take no lock.

Accept, decline and revoke are each one conditional update that matches only a pending
invite; an invite that is no longer pending gets `Conflict` (409), and one deleted with
its inventory gets `NotFound`. Accepting is idempotent: an invitee who is already a
member keeps their membership, and accepting an accepted invite again returns it. The
unique index on pending invites refuses a second invite with `Conflict`.

Membership and invite foreign keys are checked when the transaction commits. An invite
whose inventory was deleted first gets `NotFound` at commit. An accept whose inventory is
gone gets `NotFound` when it takes its lock.
"""

import functools

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from .models import (
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


def _violates(error, *constraints):
    """True when the database raised `error` for one of the constraints named."""
    diag = getattr(error.__cause__, "diag", None)
    return diag is not None and diag.constraint_name in constraints


@functools.cache
def _inventory_foreign_keys():
    """Names of the foreign keys from memberships and invites to the inventory."""
    target = (Inventory._meta.db_table, Inventory._meta.pk.column)
    with connection.cursor() as cursor:
        return tuple(
            name
            for model in (Membership, InventoryInvite)
            for name, constraint in connection.introspection.get_constraints(
                cursor, model._meta.db_table
            ).items()
            if constraint["foreign_key"] == target
        )


def _violates_inventory_reference(error):
    return _violates(error, *_inventory_foreign_keys())


def _lock_inventory(inventory_id):
    inventory = Inventory.objects.select_for_update().filter(pk=inventory_id).first()
    if inventory is None:
        raise NotFound(INVENTORY_NOT_FOUND)
    return inventory


def _lock_as(user_id, inventory_id, role):
    """Locks the inventory and returns the caller's membership, which must have `role`."""
    inventory = _lock_inventory(inventory_id)
    membership = Membership.objects.filter(inventory=inventory, user_id=user_id).first()
    if membership is None:
        raise NotFound(INVENTORY_NOT_FOUND)
    membership.inventory = inventory
    if not has_role(membership, role):
        raise PermissionDenied(ROLE_REQUIRED[role])
    return membership


def _target_membership(inventory_id, user_id):
    membership = Membership.objects.filter(inventory_id=inventory_id, user_id=user_id).first()
    if membership is None:
        raise NotFound(MEMBER_NOT_FOUND)
    return membership


def _refuse_losing_last_owner(membership):
    """Called before `membership` stops being an owner, with the inventory locked."""
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
    if not Membership.objects.filter(pk=target.pk).update(role=role):
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
        if _violates_inventory_reference(error):
            raise NotFound(INVENTORY_NOT_FOUND)
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
    """Moves `invite` from pending to `status`. Raises `NotFound` if the invite is gone and
    `Conflict` if it is no longer pending."""
    pending = InventoryInvite.objects.filter(pk=invite.pk, status=InviteStatus.PENDING)
    if pending.update(status=status):
        return
    if not InventoryInvite.objects.filter(pk=invite.pk).exists():
        raise NotFound(INVITE_NOT_FOUND)
    raise Conflict(NOT_PENDING)


def _join(invite, user):
    """The invitee's membership, added as `member` unless they already have one."""
    membership, _ = Membership.objects.get_or_create(
        inventory_id=invite.inventory_id, user=user, defaults={"role": Role.MEMBER}
    )
    return membership


def _membership_if_accepted(invite, user):
    """The invitee's membership, if `invite` is accepted and they are still a member."""
    if not InventoryInvite.objects.filter(pk=invite.pk, status=InviteStatus.ACCEPTED).exists():
        return None
    return Membership.objects.filter(inventory_id=invite.inventory_id, user=user).first()


def _key_share_inventory(inventory_id):
    """Takes `FOR KEY SHARE` on the inventory row, the lock a new membership's foreign key
    check takes at commit. False when the inventory is gone."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT 1 FROM {connection.ops.quote_name(Inventory._meta.db_table)}"
            " WHERE id = %s FOR KEY SHARE",
            [inventory_id],
        )
        return cursor.fetchone() is not None


def accept_invite(user, invite_id):
    """Returns the invitee's membership. Accepting again, or as an existing member,
    succeeds without adding a second membership."""
    invite = _invite_for(user, invite_id, by_invitee=True)
    with transaction.atomic():
        if not _key_share_inventory(invite.inventory_id):
            raise NotFound(INVITE_NOT_FOUND)
        try:
            _finish(invite, InviteStatus.ACCEPTED)
        except Conflict:
            membership = _membership_if_accepted(invite, user)
            if membership is None:
                raise
            return membership
        return _join(invite, user)


def decline_invite(user, invite_id):
    _finish(_invite_for(user, invite_id, by_invitee=True), InviteStatus.DECLINED)


def revoke_invite(user, invite_id):
    _finish(_invite_for(user, invite_id, by_invitee=False), InviteStatus.REVOKED)
