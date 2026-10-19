from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from gear_library.models import (
    Connection,
    ConnectionStatus,
    Inventory,
    Membership,
    MembershipStatus,
    Role,
    ordered_pair,
)

DEMO_PASSWORD = "gear-library-demo"

# 555-01xx numbers are reserved for fictional use.
AVERY, JORDAN, SAM = "5555550101", "5555550102", "5555550103"
DEMO_USERS = [
    (AVERY, "Avery", "Brooks"),
    (JORDAN, "Jordan", "Diaz"),
    (SAM, "Sam", "Okafor"),
]

# Each inventory's first member is its owner, and is how a later run recognises it.
DEMO_INVENTORIES = [
    {
        "name": "Climbing Club",
        "members": [(AVERY, Role.OWNER), (JORDAN, Role.ADMIN), (SAM, Role.MEMBER)],
        "invites": [],
    },
    {
        "name": "Camping Crew",
        "members": [(JORDAN, Role.OWNER), (SAM, Role.ADMIN)],
        # (invitee, invited by)
        "invites": [(AVERY, SAM)],
    },
]

# (requested by, other user, status). A later run skips a pair that already has a row.
DEMO_CONNECTIONS = [
    (AVERY, JORDAN, ConnectionStatus.ACCEPTED),
    (JORDAN, SAM, ConnectionStatus.ACCEPTED),
    (SAM, AVERY, ConnectionStatus.PENDING),
]


class Command(BaseCommand):
    help = (
        "Create the demo users, their inventories and their connections. Users, demo "
        "inventories and connected pairs that already exist are left unchanged."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        created = 0
        for phone_number, first_name, last_name in DEMO_USERS:
            if User.objects.filter(phone_number=phone_number).exists():
                continue
            User.objects.create_user(
                phone_number=phone_number,
                password=DEMO_PASSWORD,
                first_name=first_name,
                last_name=last_name,
            )
            created += 1
        existing = len(DEMO_USERS) - created
        self.stdout.write(f"Created {created} demo users; {existing} already existed.")

        demo_phone_numbers = [phone_number for phone_number, _, _ in DEMO_USERS]
        users = User.objects.in_bulk(demo_phone_numbers, field_name="phone_number")
        created = 0
        for demo in DEMO_INVENTORIES:
            owner_phone = demo["members"][0][0]
            if Membership.objects.active().filter(
                inventory__name=demo["name"], user=users[owner_phone]
            ).exists():
                continue
            inventory = Inventory.objects.create(name=demo["name"])
            for phone_number, role in demo["members"]:
                Membership.objects.create(
                    inventory=inventory,
                    user=users[phone_number],
                    role=role,
                    status=MembershipStatus.ACTIVE,
                )
            for invitee, invited_by in demo["invites"]:
                Membership.objects.create(
                    inventory=inventory,
                    user=users[invitee],
                    role=Role.MEMBER,
                    status=MembershipStatus.PENDING,
                    invited_by=users[invited_by],
                )
            created += 1
        existing = len(DEMO_INVENTORIES) - created
        self.stdout.write(f"Created {created} demo inventories; {existing} already existed.")

        created = 0
        for requested_by, other, status in DEMO_CONNECTIONS:
            requester, other_user = users[requested_by], users[other]
            if Connection.objects.between(requester, other_user).exists():
                continue
            first, second = ordered_pair(requester, other_user)
            Connection.objects.create(
                first_user=first, second_user=second, requested_by=requester, status=status
            )
            created += 1
        existing = len(DEMO_CONNECTIONS) - created
        self.stdout.write(f"Created {created} demo connections; {existing} already existed.")
