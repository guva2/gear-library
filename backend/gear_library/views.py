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

from .authentication import CsrfSessionAuthentication
from .serializers import LoginSerializer, RegisterSerializer, UserSerializer

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
