from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models

# [0-9], not \d: Python's \d matches any Unicode digit, not only ASCII 0-9.
PHONE_NUMBER_PATTERN = r"^[0-9]{10}$"

ONE_MEMBERSHIP_PER_USER = "gear_library_membership_one_per_user"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone_number, password=None, **extra_fields):
        if not phone_number:
            raise ValueError("A phone number is required.")
        user = self.model(phone_number=phone_number, **extra_fields)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields["is_staff"] is not True:
            raise ValueError("A superuser must have is_staff=True.")
        if extra_fields["is_superuser"] is not True:
            raise ValueError("A superuser must have is_superuser=True.")
        return self.create_user(phone_number, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    phone_number = models.CharField(
        max_length=10,
        unique=True,
        validators=[
            RegexValidator(
                PHONE_NUMBER_PATTERN,
                message="Enter a US phone number as exactly 10 digits.",
            )
        ],
        error_messages={"unique": "A user with this phone number already exists."},
    )
    first_name = models.CharField(max_length=32)
    last_name = models.CharField(max_length=32)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(phone_number__regex=PHONE_NUMBER_PATTERN),
                name="gear_library_user_phone_number_10_digits",
            ),
        ]

    def __str__(self):
        return self.phone_number


class Inventory(models.Model):
    name = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    MEMBER = "member"
    ADMIN = "admin"
    OWNER = "owner"


class MembershipStatus(models.TextChoices):
    PENDING = "pending"
    ACTIVE = "active"


class MembershipQuerySet(models.QuerySet):
    def active(self):
        """The memberships that grant access. A pending one is an invite and grants none."""
        return self.filter(status=MembershipStatus.ACTIVE)

    def pending(self):
        return self.filter(status=MembershipStatus.PENDING)


class Membership(models.Model):
    """A user in an inventory. A `pending` membership is an invite the user has not
    accepted yet."""

    inventory = models.ForeignKey(
        Inventory, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="memberships")
    role = models.CharField(max_length=6, choices=Role.choices)
    status = models.CharField(max_length=7, choices=MembershipStatus.choices)
    # Null for the membership that created the inventory.
    invited_by = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, related_name="invites_sent"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = MembershipQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=Role.values),
                name="gear_library_membership_role_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=MembershipStatus.values),
                name="gear_library_membership_status_valid",
            ),
            models.CheckConstraint(
                condition=~models.Q(status=MembershipStatus.PENDING)
                | models.Q(role=Role.MEMBER),
                name="gear_library_membership_pending_is_member",
            ),
            models.UniqueConstraint(
                fields=["inventory", "user"], name=ONE_MEMBERSHIP_PER_USER
            ),
        ]
