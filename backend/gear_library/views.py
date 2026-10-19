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

from . import connections, inventories
from .authentication import CsrfSessionAuthentication
from .models import Connection, ConnectionStatus, Membership, Role
from .serializers import (
    ConnectionRequestSerializer,
    ConnectionSerializer,
    InventoryInviteSerializer,
    InventoryNameSerializer,
    InventorySerializer,
    LoginSerializer,
    MemberSerializer,
    MyInviteSerializer,
    PersonNameSerializer,
    PhoneNumberSerializer,
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
        membership = inventories.create_inventory(request.user, name)
        return Response(InventorySerializer(membership).data, status=status.HTTP_201_CREATED)
    memberships = (
        Membership.objects.active()
        .filter(user=request.user)
        .select_related("inventory")
        .order_by("inventory__name", "inventory_id")
    )
    return Response(InventorySerializer(memberships, many=True).data)


# Unsafe views check the caller's access before reading the body, so a non-member gets
# 404 and a member without the role gets 403 whatever they send.


@api_view(["GET", "PATCH", "DELETE"])
def inventory_detail(request, inventory_id):
    if request.method == "GET":
        membership = inventories.get_membership(request.user, inventory_id)
        return Response(InventorySerializer(membership).data)
    actor = inventories.get_membership(request.user, inventory_id, Role.OWNER)
    if request.method == "DELETE":
        inventories.delete_inventory(actor)
        return Response(status=status.HTTP_204_NO_CONTENT)
    name = _validated(InventoryNameSerializer, request)["name"]
    membership = inventories.rename_inventory(actor, name)
    return Response(InventorySerializer(membership).data)


@api_view(["GET"])
def member_list(request, inventory_id):
    membership = inventories.get_membership(request.user, inventory_id)
    members = (
        Membership.objects.active()
        .filter(inventory_id=inventory_id)
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
    actor = inventories.get_membership(request.user, inventory_id, Role.OWNER)
    role = _validated(RoleSerializer, request)["role"]
    membership = inventories.set_role(actor, user_id, role)
    return Response(MemberSerializer(membership).data)


@api_view(["GET", "POST"])
def inventory_invites(request, inventory_id):
    actor = inventories.get_membership(request.user, inventory_id, Role.ADMIN)
    if request.method == "POST":
        phone_number = _validated(PhoneNumberSerializer, request)["phone_number"]
        invite = inventories.invite(actor, phone_number)
        return Response(InventoryInviteSerializer(invite).data, status=status.HTTP_201_CREATED)
    invites = (
        Membership.objects.pending()
        .filter(inventory_id=inventory_id)
        .select_related("user", "invited_by")
        .order_by("created_at", "id")
    )
    return Response(InventoryInviteSerializer(invites, many=True).data)


@api_view(["GET"])
def my_invites(request):
    invites = (
        Membership.objects.pending()
        .filter(user=request.user)
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


def _connection_data(connection, user):
    if connection.status == ConnectionStatus.ACCEPTED:
        return ConnectionSerializer(connection, context={"user": user}).data
    return ConnectionRequestSerializer(connection, context={"user": user}).data


def _connections_of(user):
    return Connection.objects.involving(user).select_related("first_user", "second_user")


@api_view(["GET", "POST"])
def connection_list(request):
    if request.method == "POST":
        phone_number = _validated(PhoneNumberSerializer, request)["phone_number"]
        connection = connections.request_connection(request.user, phone_number)
        code = status.HTTP_200_OK
        if connection.status == ConnectionStatus.PENDING:
            code = status.HTTP_201_CREATED
        return Response(_connection_data(connection, request.user), status=code)

    def by_name(connection):
        other = connection.other_user(request.user)
        return (other.last_name, other.first_name, other.id)

    accepted = sorted(_connections_of(request.user).accepted(), key=by_name)
    context = {"user": request.user}
    return Response(ConnectionSerializer(accepted, many=True, context=context).data)


@api_view(["GET"])
def connection_requests(request):
    pending = list(_connections_of(request.user).pending().order_by("created_at", "id"))
    sent = [c for c in pending if c.requested_by_id == request.user.id]
    received = [c for c in pending if c.requested_by_id != request.user.id]
    context = {"user": request.user}
    return Response(
        {
            "received": ConnectionRequestSerializer(received, many=True, context=context).data,
            "sent": ConnectionRequestSerializer(sent, many=True, context=context).data,
        }
    )


@api_view(["DELETE"])
def connection_detail(request, connection_id):
    connections.remove(request.user, connection_id)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
def accept_connection(request, connection_id):
    connection = connections.accept(request.user, connection_id)
    return Response(_connection_data(connection, request.user))


@api_view(["POST"])
def decline_connection(request, connection_id):
    connections.decline(request.user, connection_id)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
def cancel_connection(request, connection_id):
    connections.cancel(request.user, connection_id)
    return Response(status=status.HTTP_204_NO_CONTENT)
