from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.middleware.csrf import get_token
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.settings import api_settings

from . import inventories
from .authentication import CsrfSessionAuthentication
from .models import InventoryInvite, InviteStatus, Membership, Role
from .serializers import (
    InventoryInviteSerializer,
    InventoryNameSerializer,
    InventorySerializer,
    LoginSerializer,
    MemberSerializer,
    MyInviteSerializer,
    NewInviteSerializer,
    PersonNameSerializer,
    RegisterSerializer,
    RoleSerializer,
    UserSerializer,
)

User = get_user_model()

WRONG_CREDENTIALS = "Wrong phone number or password."
PHONE_TAKEN = User._meta.get_field("phone_number").error_messages["unique"]


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return Response(
            {"status": "error", "database": "unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response({"status": "ok", "database": "ok"})


class IsAnonymous(BasePermission):
    message = "You are already logged in."

    def has_permission(self, request, view):
        return not request.user.is_authenticated


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def csrf(request):
    get_token(request)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@authentication_classes([CsrfSessionAuthentication])
@permission_classes([IsAnonymous])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    fields = serializer.validated_data
    password = fields.pop("password")

    errors = {}
    if User.objects.filter(phone_number=fields["phone_number"]).exists():
        errors["phone_number"] = [PHONE_TAKEN]
    try:
        validate_password(password, User(**fields))
    except DjangoValidationError as error:
        errors["password"] = error.messages
    if errors:
        raise ValidationError(errors)

    try:
        with transaction.atomic():
            user = User.objects.create_user(password=password, **fields)
    except DjangoValidationError as error:
        raise ValidationError(error.message_dict)
    except IntegrityError:
        # Another signup for the same number inserted after this one's full_clean.
        if not User.objects.filter(phone_number=fields["phone_number"]).exists():
            raise
        raise ValidationError({"phone_number": [PHONE_TAKEN]})

    login(request, user)
    return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@authentication_classes([CsrfSessionAuthentication])
@permission_classes([AllowAny])
def login_view(request):
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = authenticate(request, **serializer.validated_data)
    if user is None:
        raise ValidationError({api_settings.NON_FIELD_ERRORS_KEY: [WRONG_CREDENTIALS]})
    login(request, user)
    return Response(UserSerializer(user).data)


@api_view(["POST"])
def logout_view(request):
    logout(request)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
def me(request):
    return Response(UserSerializer(request.user).data)


def _validated(serializer_class, request):
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


@api_view(["GET", "POST"])
def inventory_list(request):
    if request.method == "POST":
        name = _validated(InventoryNameSerializer, request)["name"]
        inventory = inventories.create_inventory(request.user, name)
        membership = Membership(inventory=inventory, role=Role.OWNER)
        return Response(InventorySerializer(membership).data, status=status.HTTP_201_CREATED)
    memberships = (
        Membership.objects.filter(user=request.user)
        .select_related("inventory")
        .order_by("inventory__name", "inventory_id")
    )
    return Response(InventorySerializer(memberships, many=True).data)


# Unsafe views check the caller's access before reading the body, so a non-member gets
# 404 and a member without the role gets 403 whatever they send. This check takes no lock;
# it only decides which error comes first.


@api_view(["GET", "PATCH", "DELETE"])
def inventory_detail(request, inventory_id):
    if request.method == "GET":
        membership = inventories.get_membership(request.user, inventory_id)
        return Response(InventorySerializer(membership).data)
    inventories.get_membership(request.user, inventory_id, Role.OWNER)
    if request.method == "DELETE":
        inventories.delete_inventory(request.user, inventory_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
    name = _validated(InventoryNameSerializer, request)["name"]
    membership = inventories.rename_inventory(request.user, inventory_id, name)
    return Response(InventorySerializer(membership).data)


@api_view(["GET"])
def member_list(request, inventory_id):
    membership = inventories.get_membership(request.user, inventory_id)
    members = (
        Membership.objects.filter(inventory_id=inventory_id)
        .select_related("user")
        .order_by("user__last_name", "user__first_name", "user_id")
    )
    if inventories.has_role(membership, Role.ADMIN):
        return Response(MemberSerializer(members, many=True).data)
    people = [m.user for m in members if m.role in (Role.ADMIN, Role.OWNER)]
    return Response(PersonNameSerializer(people, many=True).data)


@api_view(["PATCH", "DELETE"])
def member_detail(request, inventory_id, user_id):
    if request.method == "DELETE":
        inventories.remove_member(request.user, inventory_id, user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
    inventories.get_membership(request.user, inventory_id, Role.OWNER)
    role = _validated(RoleSerializer, request)["role"]
    membership = inventories.set_role(request.user, inventory_id, user_id, role)
    return Response(MemberSerializer(membership).data)


@api_view(["GET", "POST"])
def inventory_invites(request, inventory_id):
    inventories.get_membership(request.user, inventory_id, Role.ADMIN)
    if request.method == "POST":
        phone_number = _validated(NewInviteSerializer, request)["phone_number"]
        invite = inventories.invite(request.user, inventory_id, phone_number)
        return Response(InventoryInviteSerializer(invite).data, status=status.HTTP_201_CREATED)
    invites = (
        InventoryInvite.objects.filter(inventory_id=inventory_id, status=InviteStatus.PENDING)
        .select_related("invitee", "invited_by")
        .order_by("created_at", "id")
    )
    return Response(InventoryInviteSerializer(invites, many=True).data)


@api_view(["GET"])
def my_invites(request):
    invites = (
        InventoryInvite.objects.filter(invitee=request.user, status=InviteStatus.PENDING)
        .select_related("inventory", "invited_by")
        .order_by("created_at", "id")
    )
    return Response(MyInviteSerializer(invites, many=True).data)


@api_view(["POST"])
def accept_invite(request, invite_id):
    membership = inventories.accept_invite(request.user, invite_id)
    return Response(InventorySerializer(membership).data)


@api_view(["POST"])
def decline_invite(request, invite_id):
    inventories.decline_invite(request.user, invite_id)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
def revoke_invite(request, invite_id):
    inventories.revoke_invite(request.user, invite_id)
    return Response(status=status.HTTP_204_NO_CONTENT)
