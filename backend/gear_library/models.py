from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import TrigramSimilarity, TrigramWordSimilarity
from django.core.validators import RegexValidator
from django.db import models

from .phone import PHONE_NUMBER_PATTERN

# A name has a character that is not whitespace. Every character Postgres matches with `\s`
# is also whitespace to Python, so the check constraint accepts any name the validator does.
NAME_PATTERN = r"\S"

ONE_MEMBERSHIP_PER_USER = "gear_library_membership_one_per_user"
ONE_CONNECTION_PER_PAIR = "gear_library_connection_one_per_pair"
ONE_LISTING_PER_ITEM = "gear_library_inventoryitem_one_per_item"

# A description matches a search at this word similarity or more. A name matches at
# `pg_trgm.word_similarity_threshold`, set in `config/settings.py`.
DESCRIPTION_MATCH = 0.6


_not_blank = RegexValidator(NAME_PATTERN, message="This field cannot be blank.")


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
                message=(
                    "Enter a US phone number as exactly 10 digits. The area code and the "
                    "3 digits after it cannot start with 0 or 1."
                ),
            )
        ],
        error_messages={"unique": "A user with this phone number already exists."},
    )
    first_name = models.CharField(max_length=32, validators=[_not_blank])
    last_name = models.CharField(max_length=32, validators=[_not_blank])
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
                name="gear_library_user_phone_number_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(first_name__regex=NAME_PATTERN),
                name="gear_library_user_first_name_not_blank",
            ),
            models.CheckConstraint(
                condition=models.Q(last_name__regex=NAME_PATTERN),
                name="gear_library_user_last_name_not_blank",
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


def ordered_pair(user, other):
    """The ids of two users, each given as a user or a user id, in the order a
    `Connection` stores them: lower id first."""
    ids = [getattr(person, "pk", person) for person in (user, other)]
    return tuple(sorted(ids))


class ConnectionStatus(models.TextChoices):
    PENDING = "pending"
    ACCEPTED = "accepted"


class ConnectionQuerySet(models.QuerySet):
    def between(self, user, other):
        first, second = ordered_pair(user, other)
        return self.filter(first_user_id=first, second_user_id=second)

    def involving(self, user):
        return self.filter(models.Q(first_user=user) | models.Q(second_user=user))

    def pending(self):
        return self.filter(status=ConnectionStatus.PENDING)

    def accepted(self):
        return self.filter(status=ConnectionStatus.ACCEPTED)


class Connection(models.Model):
    """Two users, once per pair. `pending` is a request from `requested_by` to the other
    user; `accepted` connects them both ways."""

    first_user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    second_user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    requested_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=8, choices=ConnectionStatus.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ConnectionQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(first_user__lt=models.F("second_user")),
                name="gear_library_connection_ordered_pair",
            ),
            models.CheckConstraint(
                condition=models.Q(requested_by=models.F("first_user"))
                | models.Q(requested_by=models.F("second_user")),
                name="gear_library_connection_requested_by_a_user",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=ConnectionStatus.values),
                name="gear_library_connection_status_valid",
            ),
            models.UniqueConstraint(
                fields=["first_user", "second_user"], name=ONE_CONNECTION_PER_PAIR
            ),
        ]

    def other_user(self, user):
        """The user of the pair who is not `user`."""
        return self.second_user if self.first_user_id == user.id else self.first_user


class LoanStatus(models.TextChoices):
    AVAILABLE = "available"
    REQUESTED = "requested"
    ON_LOAN = "on_loan"


class ItemQuerySet(models.QuerySet):
    def end_loan(self):
        """Makes the items available, with no borrower and no loan inventory."""
        return self.update(loan_status=LoanStatus.AVAILABLE, borrower=None, loan_inventory=None)

    def cancel_requests_through(self, inventory_id):
        """Cancels the pending requests made through the inventory `inventory_id`."""
        return self.filter(
            loan_status=LoanStatus.REQUESTED, loan_inventory_id=inventory_id
        ).end_loan()

    def matching(self, q):
        """The items whose name or description matches `q`, annotated with their scores:
        `name_match` (word similarity of `q` to the name, or 0 when the name does not
        match, so a name below the threshold cannot outrank a better description),
        `description_match` (word similarity of `q` to the description) and
        `name_similarity` (similarity of `q` to the whole name). Each side of the
        filter's OR has a `%>` operator, so the trigram indexes can serve it."""
        return self.annotate(
            name_match=models.Case(
                models.When(name__trigram_word_similar=q, then=TrigramWordSimilarity(q, "name")),
                default=models.Value(0.0),
            ),
            description_match=TrigramWordSimilarity(q, "description"),
            name_similarity=TrigramSimilarity("name", q),
        ).filter(
            models.Q(name__trigram_word_similar=q)
            | models.Q(
                description__trigram_word_similar=q, description_match__gte=DESCRIPTION_MATCH
            )
        )


class Item(models.Model):
    """A piece of gear. Its loan state is on this row: `borrower` is the requester while
    `requested` and the borrower while `on_loan`, and `loan_inventory` is the inventory the
    request or loan was made through. The owner as `borrower` is the owner using the item."""

    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name="items")
    name = models.CharField(max_length=64)
    description = models.CharField(max_length=512, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    borrower = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, related_name="borrowing"
    )
    loan_inventory = models.ForeignKey(
        Inventory, on_delete=models.SET_NULL, null=True, related_name="loans"
    )
    loan_status = models.CharField(
        max_length=9, choices=LoanStatus.choices, default=LoanStatus.AVAILABLE
    )

    objects = ItemQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(loan_status__in=LoanStatus.values),
                name="gear_library_item_loan_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    loan_status=LoanStatus.AVAILABLE,
                    borrower__isnull=True,
                    loan_inventory__isnull=True,
                )
                | models.Q(
                    loan_status=LoanStatus.REQUESTED,
                    borrower__isnull=False,
                    loan_inventory__isnull=False,
                )
                | models.Q(loan_status=LoanStatus.ON_LOAN, borrower__isnull=False),
                name="gear_library_item_loan_state",
            ),
            # The owner holds their own item only on loan with no loan inventory: they use
            # it without asking anyone.
            models.CheckConstraint(
                condition=~models.Q(borrower=models.F("owner"))
                | models.Q(loan_status=LoanStatus.ON_LOAN, loan_inventory__isnull=True),
                name="gear_library_item_owner_use",
            ),
        ]
        indexes = [
            GinIndex(
                fields=["name"], name="gear_library_item_name_trgm", opclasses=["gin_trgm_ops"]
            ),
            GinIndex(
                fields=["description"],
                name="gear_library_item_desc_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self):
        return self.name


class InventoryItem(models.Model):
    """An item listed in an inventory."""

    inventory = models.ForeignKey(Inventory, on_delete=models.CASCADE, related_name="listings")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="listings")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["inventory", "item"], name=ONE_LISTING_PER_ITEM),
        ]
