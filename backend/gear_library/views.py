"""The API's views. Everything under `/api/inventories/{id}/` derives from
`InventoryScopedViewSet`."""

from django.contrib import auth
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import (
    BooleanField,
    Case,
    Exists,
    ExpressionWrapper,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Value,
    When,
)
from django.middleware.csrf import get_token
from rest_framework import serializers, status
from rest_framework.decorators import (
    action,
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import MethodNotAllowed, NotFound, ValidationError
from rest_framework.permissions import SAFE_METHODS, AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.viewsets import GenericViewSet

from . import connections, inventories, items, loans
from .authentication import CsrfSessionAuthentication
from .models import (
    Connection,
    ConnectionStatus,
    InventoryItem,
    Item,
    LoanStatus,
    Membership,
    Role,
)
from .permissions import (
    InventoryRole,
    IsAnonymous,
    IsInviteInventoryAdmin,
    IsInvitee,
    OwnItemOrOwner,
    ReceivedRequest,
    SentRequest,
)
from .serializers import (
    BorrowedItemSerializer,
    BorrowerIdSerializer,
    ConnectionSerializer,
    DiscoverItemSerializer,
    InventoryInviteSerializer,
    InventoryNameSerializer,
    InventorySerializer,
    InviteSerializer,
    ItemFieldsSerializer,
    ItemIdSerializer,
    ItemSerializer,
    LendingItemSerializer,
    ListedItemSerializer,
    LoginSerializer,
    MemberSerializer,
    MyInviteSerializer,
    PersonNameSerializer,
    PhoneNumberSerializer,
    ReceivedRequestSerializer,
    RegisterSerializer,
    RoleSerializer,
    SentRequestSerializer,
    UserSerializer,
)

User = get_user_model()

WRONG_CREDENTIALS = "Wrong phone number or password."
PHONE_TAKEN = User._meta.get_field("phone_number").error_messages["unique"]


# Outside the request transaction, so a database that cannot start one still gets a 503.
@transaction.non_atomic_requests
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


def _validated(serializer_class, request, partial=False):
    serializer = serializer_class(data=request.data, partial=partial)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _no_content():
    return Response(status=status.HTTP_204_NO_CONTENT)


class ApiViewSet(GenericViewSet):
    """The base of every viewset. Ids in URLs are integers, and `get_object` answers an
    object the queryset does not hold with `NotFound` and `not_found` as its message."""

    lookup_url_kwarg = "id"
    lookup_value_converter = "int"
    # The browsable API and OPTIONS build their forms from it. Actions validate their body
    # with their own serializers.
    serializer_class = serializers.Serializer
    not_found = None

    def get_object(self):
        lookup = {self.lookup_field: self.kwargs[self.lookup_url_kwarg]}
        found = self.get_queryset().filter(**lookup).first()
        if found is None:
            raise NotFound(self.not_found)
        self.check_object_permissions(self.request, found)
        return found


class AuthViewSet(ApiViewSet):
    @action(detail=False, authentication_classes=[], permission_classes=[AllowAny])
    def csrf(self, request):
        get_token(request)
        return _no_content()

    @action(
        detail=False,
        methods=["post"],
        authentication_classes=[CsrfSessionAuthentication],
        permission_classes=[IsAnonymous],
    )
    def register(self, request):
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

        auth.login(request, user)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    @action(
        detail=False,
        methods=["post"],
        authentication_classes=[CsrfSessionAuthentication],
        permission_classes=[AllowAny],
    )
    def login(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = auth.authenticate(request, **serializer.validated_data)
        if user is None:
            raise ValidationError({api_settings.NON_FIELD_ERRORS_KEY: [WRONG_CREDENTIALS]})
        auth.login(request, user)
        return Response(UserSerializer(user).data)

    @action(detail=False, methods=["post"])
    def logout(self, request):
        auth.logout(request)
        return _no_content()

    @action(detail=False)
    def me(self, request):
        return Response(UserSerializer(request.user).data)


class InventoryListViewSet(ApiViewSet):
    def list(self, request):
        memberships = (
            Membership.objects.active()
            .filter(user=request.user)
            .select_related("inventory")
            .order_by("inventory__name", "inventory_id")
        )
        return Response(InventorySerializer(memberships, many=True).data)

    def create(self, request):
        name = _validated(InventoryNameSerializer, request)["name"]
        membership = inventories.create_inventory(request.user, name)
        return Response(InventorySerializer(membership).data, status=status.HTTP_201_CREATED)


class InventoryScopedViewSet(ApiViewSet):
    """The base of the views under `/api/inventories/{id}/`.

    A change, any method not in `SAFE_METHODS`, locks the inventory row before
    `InventoryRole` reads the caller's membership, and keeps it until the request's
    transaction ends. The role checked therefore stays the caller's until the change
    commits. Reads take no lock.

    `InventoryRole` runs before the body is read, so a non-member gets 404 and a member
    without `required_role` gets 403 whatever they send. Actions read the caller's
    membership as `request.membership`.
    """

    permission_classes = [IsAuthenticated, InventoryRole]

    def inventory_id(self):
        return self.kwargs["inventory_id"]

    def required_role(self, request):
        return Role.MEMBER

    def perform_authentication(self, request):
        # `initial()` calls this first, before the permission checks. A logged-out caller
        # is left to `IsAuthenticated`. For anyone else, a method the view does not serve
        # is answered 405 before anything locks or reads membership. The browsable API
        # and OPTIONS check permissions on copies of the request without calling it, so
        # they take no lock.
        super().perform_authentication(request)
        if not request.user.is_authenticated:
            return
        method = request.method.lower()
        if method not in self.http_method_names or not hasattr(self, method):
            raise MethodNotAllowed(request.method)
        if request.method not in SAFE_METHODS:
            inventories.lock_inventory(self.inventory_id())


class InventoryViewSet(InventoryScopedViewSet):
    def inventory_id(self):
        return self.kwargs["id"]

    def required_role(self, request):
        return Role.MEMBER if request.method in SAFE_METHODS else Role.OWNER

    def retrieve(self, request, **kwargs):
        return Response(InventorySerializer(request.membership).data)

    def partial_update(self, request, **kwargs):
        name = _validated(InventoryNameSerializer, request)["name"]
        membership = inventories.rename_inventory(request.membership, name)
        return Response(InventorySerializer(membership).data)

    def destroy(self, request, **kwargs):
        inventories.delete_inventory(request.membership)
        return _no_content()


class MemberViewSet(InventoryScopedViewSet):
    lookup_url_kwarg = "user_id"

    def required_role(self, request):
        if request.method in SAFE_METHODS:
            return Role.MEMBER
        leaving = request.method == "DELETE" and self.kwargs["user_id"] == request.user.id
        return Role.MEMBER if leaving else Role.OWNER

    def list(self, request, **kwargs):
        members = (
            Membership.objects.active()
            .filter(inventory_id=self.inventory_id())
            .select_related("user")
            .order_by("user__last_name", "user__first_name", "user_id")
        )
        if inventories.has_role(request.membership, Role.ADMIN):
            return Response(MemberSerializer(members, many=True).data)
        people = [m.user for m in members if m.role in (Role.ADMIN, Role.OWNER)]
        return Response(PersonNameSerializer(people, many=True).data)

    def partial_update(self, request, **kwargs):
        role = _validated(RoleSerializer, request)["role"]
        membership = inventories.set_role(request.membership, self.kwargs["user_id"], role)
        return Response(MemberSerializer(membership).data)

    def destroy(self, request, **kwargs):
        inventories.remove_member(request.membership, self.kwargs["user_id"])
        return _no_content()


class InventoryInviteViewSet(InventoryScopedViewSet):
    def required_role(self, request):
        return Role.ADMIN

    def list(self, request, **kwargs):
        invites = (
            Membership.objects.pending()
            .filter(inventory_id=self.inventory_id())
            .select_related("user", "invited_by")
            .order_by("created_at", "id")
        )
        return Response(InventoryInviteSerializer(invites, many=True).data)

    def create(self, request, **kwargs):
        user_id = _validated(InviteSerializer, request)["user_id"]
        invite = inventories.invite(request.membership, user_id)
        return Response(InventoryInviteSerializer(invite).data, status=status.HTTP_201_CREATED)


class ListingViewSet(InventoryScopedViewSet):
    lookup_field = "item_id"
    lookup_url_kwarg = "item_id"
    not_found = items.LISTING_NOT_FOUND

    def get_queryset(self):
        return (
            InventoryItem.objects.filter(inventory_id=self.inventory_id())
            .select_related("item__owner", "item__borrower")
            .order_by("item__name", "item_id")
        )

    def get_permissions(self):
        permissions = super().get_permissions()
        if self.action == "destroy":
            permissions.append(OwnItemOrOwner())
        return permissions

    def required_role(self, request):
        if request.method in SAFE_METHODS or self.action == "borrow":
            return Role.MEMBER
        return Role.ADMIN

    def _listed(self, data, status_code=status.HTTP_200_OK, many=False):
        context = {"membership": self.request.membership}
        serializer = ListedItemSerializer(data, many=many, context=context)
        return Response(serializer.data, status=status_code)

    def list(self, request, **kwargs):
        return self._listed(self.get_queryset(), many=True)

    def create(self, request, **kwargs):
        item_id = _validated(ItemIdSerializer, request)["item_id"]
        listing = items.add_listing(request.membership, item_id)
        return self._listed(listing, status.HTTP_201_CREATED)

    def destroy(self, request, **kwargs):
        items.remove_listing(self.get_object())
        return _no_content()

    @action(detail=True, methods=["post"])
    def borrow(self, request, **kwargs):
        loans.borrow(request.membership, self.get_object())
        return _no_content()

    def _change_loan(self, change):
        # The body is checked before the listing is looked up.
        borrower_id = _validated(BorrowerIdSerializer, self.request)["borrower_id"]
        change(self.request.user, self.get_object(), borrower_id)
        return _no_content()

    @action(detail=True, methods=["post"])
    def approve(self, request, **kwargs):
        return self._change_loan(loans.approve)

    @action(detail=True, methods=["post"])
    def decline(self, request, **kwargs):
        return self._change_loan(loans.decline)

    @action(detail=True, methods=["post"], url_path="return")
    def mark_returned(self, request, **kwargs):
        return self._change_loan(loans.mark_returned)


class InviteViewSet(ApiViewSet):
    """The caller's own invites, and every membership they may act on as an invite."""

    not_found = inventories.INVITE_NOT_FOUND

    def get_queryset(self):
        """The memberships of the caller, and every membership of the inventories where
        the caller is an admin or owner, whatever their status."""
        user = self.request.user
        admin_of = Membership.objects.active().filter(
            user=user, role__in=[Role.ADMIN, Role.OWNER]
        )
        return Membership.objects.filter(
            Q(user=user) | Q(inventory_id__in=admin_of.values("inventory_id"))
        )

    def list(self, request):
        invites = (
            Membership.objects.pending()
            .filter(user=request.user)
            .select_related("inventory", "invited_by")
            .order_by("created_at", "id")
        )
        return Response(MyInviteSerializer(invites, many=True).data)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsInvitee])
    def accept(self, request, **kwargs):
        membership = inventories.accept_invite(self.get_object())
        return Response(InventorySerializer(membership).data)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsInvitee])
    def decline(self, request, **kwargs):
        inventories.delete_invite(self.get_object())
        return _no_content()

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated, IsInviteInventoryAdmin],
    )
    def revoke(self, request, **kwargs):
        inventories.delete_invite(self.get_object())
        return _no_content()


def _connection_data(connection, user):
    """A connection in the shape its status lets the caller see: accepted in full,
    otherwise as a sent request."""
    if connection.status == ConnectionStatus.ACCEPTED:
        return ConnectionSerializer(connection, context={"user": user}).data
    return SentRequestSerializer(connection, context={"user": user}).data


class ConnectionViewSet(ApiViewSet):
    not_found = connections.NOT_FOUND

    def get_queryset(self):
        return Connection.objects.involving(self.request.user).select_related(
            "first_user", "second_user"
        )

    def list(self, request):
        def by_name(connection):
            other = connection.other_user(request.user)
            return (other.last_name, other.first_name, other.id)

        accepted = sorted(self.get_queryset().accepted(), key=by_name)
        context = {"user": request.user}
        return Response(ConnectionSerializer(accepted, many=True, context=context).data)

    def create(self, request):
        phone_number = _validated(PhoneNumberSerializer, request)["phone_number"]
        connection = connections.request_connection(request.user, phone_number)
        code = status.HTTP_200_OK
        if connection.status == ConnectionStatus.PENDING:
            code = status.HTTP_201_CREATED
        return Response(_connection_data(connection, request.user), status=code)

    @action(detail=False)
    def requests(self, request):
        pending = list(self.get_queryset().pending().order_by("created_at", "id"))
        sent = [c for c in pending if c.requested_by_id == request.user.id]
        received = [c for c in pending if c.requested_by_id != request.user.id]
        context = {"user": request.user}
        return Response(
            {
                "received": ReceivedRequestSerializer(received, many=True, context=context).data,
                "sent": SentRequestSerializer(sent, many=True, context=context).data,
            }
        )

    def destroy(self, request, **kwargs):
        connections.remove(self.get_object())
        return _no_content()

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, ReceivedRequest])
    def accept(self, request, **kwargs):
        connection = connections.accept(self.get_object())
        return Response(_connection_data(connection, request.user))

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, ReceivedRequest])
    def decline(self, request, **kwargs):
        connections.delete_request(self.get_object())
        return _no_content()

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, SentRequest])
    def cancel(self, request, **kwargs):
        connections.delete_request(self.get_object())
        return _no_content()


class ItemViewSet(ApiViewSet):
    """The caller's own items."""

    not_found = items.ITEM_NOT_FOUND

    def get_queryset(self):
        listings = InventoryItem.objects.select_related("inventory").order_by(
            "inventory__name", "inventory_id"
        )
        return (
            Item.objects.filter(owner=self.request.user)
            .select_related("borrower", "loan_inventory")
            .prefetch_related(Prefetch("listings", queryset=listings))
            .order_by("name", "id")
        )

    def list(self, request):
        return Response(ItemSerializer(self.get_queryset(), many=True).data)

    def create(self, request):
        fields = _validated(ItemFieldsSerializer, request)
        item = items.create_item(request.user, fields)
        return Response(ItemSerializer(item).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, **kwargs):
        self.get_object()
        fields = _validated(ItemFieldsSerializer, request, partial=True)
        items.update_item(request.user, self.kwargs["id"], fields)
        return Response(ItemSerializer(self.get_object()).data)

    def destroy(self, request, **kwargs):
        items.delete_item(request.user, self.kwargs["id"])
        return _no_content()

    @action(detail=True, methods=["post"], url_path="return")
    def mark_returned(self, request, **kwargs):
        if not Item.objects.filter(owner=request.user, pk=self.kwargs["id"]).exists():
            raise NotFound(self.not_found)
        borrower_id = _validated(BorrowerIdSerializer, request)["borrower_id"]
        loans.owner_mark_returned(request.user, self.kwargs["id"], borrower_id)
        return _no_content()

    @action(detail=True, methods=["post"])
    def use(self, request, **kwargs):
        loans.use(request.user, self.kwargs["id"])
        return _no_content()


class BorrowingViewSet(ApiViewSet):
    """The caller's pending requests and the items they hold."""

    def list(self, request):
        user = request.user
        admin_of = _inventory_ids(user, [Role.ADMIN, Role.OWNER])
        # The holder marks it returned through `/api/items/{id}/return/` as its owner, or
        # through its loan inventory's `return/` as an admin or owner there.
        can_return = Q(loan_status=LoanStatus.ON_LOAN) & (
            Q(owner=user) | Q(loan_inventory_id__in=admin_of) & Exists(_listed_where_lent())
        )
        borrowed = (
            Item.objects.filter(borrower=user)
            .annotate(can_return=ExpressionWrapper(can_return, output_field=BooleanField()))
            .select_related("owner", "loan_inventory")
            .order_by("name", "id")
        )
        return Response(BorrowedItemSerializer(borrowed, many=True).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, **kwargs):
        loans.cancel(request.user, self.kwargs["id"])
        return _no_content()


def _inventory_ids(user, roles=None):
    """The ids of the inventories where `user` is an active member, with one of `roles`
    when given."""
    memberships = Membership.objects.active().filter(user=user)
    if roles is not None:
        memberships = memberships.filter(role__in=roles)
    return memberships.values("inventory_id")


def _listed_where_lent():
    """A subquery for an outer item: its listing in its loan inventory."""
    return InventoryItem.objects.filter(item=OuterRef("pk"), inventory=OuterRef("loan_inventory"))


def _visible_listings(user, with_role=False):
    """A prefetch of each item's listings in `user`'s inventories, as `visible_listings`,
    sorted by inventory name. `with_role` adds `user`'s role in each inventory as `role`."""
    listings = (
        InventoryItem.objects.filter(inventory_id__in=_inventory_ids(user))
        .select_related("inventory")
        .order_by("inventory__name", "inventory_id")
    )
    if with_role:
        own = Membership.objects.active().filter(user=user, inventory=OuterRef("inventory"))
        listings = listings.annotate(role=Subquery(own.values("role")))
    return Prefetch("listings", queryset=listings, to_attr="visible_listings")


class DiscoverViewSet(ApiViewSet):
    """The items listed in the caller's inventories that someone else owns."""

    def list(self, request):
        user = request.user
        listed = InventoryItem.objects.filter(inventory_id__in=_inventory_ids(user))
        found = (
            Item.objects.filter(pk__in=listed.values("item_id"))
            .exclude(owner=user)
            .select_related("owner")
            .prefetch_related(_visible_listings(user, with_role=True))
            .order_by(
                Case(When(loan_status=LoanStatus.AVAILABLE, then=Value(0)), default=Value(1)),
                "name",
                "id",
            )
        )
        serializer = DiscoverItemSerializer(found, many=True, context={"user": user})
        return Response(serializer.data)


class LendingViewSet(ApiViewSet):
    """The requests and loans of someone else that the caller may answer or close: of the
    caller's own items, and of items listed in an inventory where the caller is an admin or
    owner, requested or lent through it."""

    def list(self, request):
        user = request.user
        admin_of = set(
            _inventory_ids(user, [Role.ADMIN, Role.OWNER]).values_list("inventory_id", flat=True)
        )
        found = (
            Item.objects.filter(loan_status__in=[LoanStatus.REQUESTED, LoanStatus.ON_LOAN])
            .exclude(borrower=user)
            .filter(
                Q(owner=user) | Q(loan_inventory_id__in=admin_of) & Exists(_listed_where_lent())
            )
            .select_related("owner", "borrower", "loan_inventory")
            .prefetch_related(_visible_listings(user))
            .order_by("name", "id")
        )
        context = {"user": user, "admin_of": admin_of}
        return Response(LendingItemSerializer(found, many=True, context=context).data)
