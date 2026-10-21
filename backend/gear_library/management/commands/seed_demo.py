from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from gear_library.models import (
    Connection,
    ConnectionStatus,
    Inventory,
    InventoryItem,
    Item,
    LoanStatus,
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

# Each inventory's first member is its owner, who created it, and is how a later run
# recognises it: (phone number, role). Every other member accepted an invite from an admin
# or owner: (phone number, role, invited by).
DEMO_INVENTORIES = [
    {
        "name": "Climbing Club",
        "members": [
            (AVERY, Role.OWNER),
            (JORDAN, Role.ADMIN, AVERY),
            (SAM, Role.MEMBER, AVERY),
        ],
        "invites": [],
    },
    {
        "name": "Camping Crew",
        "members": [
            (JORDAN, Role.OWNER),
            (SAM, Role.ADMIN, JORDAN),
            (AVERY, Role.MEMBER, SAM),
        ],
        "invites": [],
    },
    {
        "name": "Hiking Group",
        "members": [(SAM, Role.OWNER)],
        # (invitee, invited by)
        "invites": [(AVERY, SAM)],
    },
]

# (requested by, other user, status). A later run skips a pair that already has a row.
# Each invite above goes to a connection of its sender.
DEMO_CONNECTIONS = [
    (SAM, AVERY, ConnectionStatus.ACCEPTED),
    (JORDAN, SAM, ConnectionStatus.ACCEPTED),
    (AVERY, JORDAN, ConnectionStatus.PENDING),
]


# (owner, name, description, names of the demo inventories it is listed in). Each owner is
# an admin or owner of those inventories. A later run skips an item whose owner already has
# an item with its name, and so does not list it again.
DEMO_ITEMS = [
    (AVERY, "Climbing rope", "60 m dynamic rope, 9.8 mm.", ["Climbing Club"]),
    (AVERY, "Belay device", "Tube style, with a locking carabiner.", ["Climbing Club"]),
    (AVERY, "Headlamp", "", []),
    (JORDAN, "Quickdraws", "A set of 12.", ["Climbing Club"]),
    (JORDAN, "First aid kit", "For groups of up to 6.", ["Climbing Club", "Camping Crew"]),
    (JORDAN, "Two-person tent", "Freestanding, 2 kg.", ["Camping Crew"]),
    (SAM, "Camp stove", "Canister stove. Fuel not included.", ["Camping Crew"]),
    (SAM, "Sleeping bag", "Rated to -5 °C.", ["Camping Crew"]),
    (SAM, "Chalk bag", "", []),
]

# (owner, item name, borrower, loan inventory name, status). Applied only to an item created
# in the same run, while it is listed in that inventory and the borrower is a member there.
DEMO_LOANS = [
    (AVERY, "Climbing rope", SAM, "Climbing Club", LoanStatus.REQUESTED),
    (JORDAN, "Two-person tent", SAM, "Camping Crew", LoanStatus.ON_LOAN),
]


class Command(BaseCommand):
    help = (
        "Create the demo users, their inventories, connections, items and loans. Users, "
        "demo inventories and items that already exist, and pairs that already have a "
        "connection or a request, are left unchanged, and existing items get no loan."
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
        inventories = {}
        for demo in DEMO_INVENTORIES:
            owner_phone = demo["members"][0][0]
            existing = (
                Membership.objects.active()
                .filter(inventory__name=demo["name"], user=users[owner_phone])
                .order_by("inventory_id")
                .first()
            )
            if existing is not None:
                inventories[demo["name"]] = existing.inventory_id
                continue
            inventory = Inventory.objects.create(name=demo["name"])
            inventories[demo["name"]] = inventory.id
            for phone_number, role, *inviter in demo["members"]:
                Membership.objects.create(
                    inventory=inventory,
                    user=users[phone_number],
                    role=role,
                    status=MembershipStatus.ACTIVE,
                    invited_by=users[inviter[0]] if inviter else None,
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
                first_user_id=first, second_user_id=second, requested_by=requester, status=status
            )
            created += 1
        existing = len(DEMO_CONNECTIONS) - created
        self.stdout.write(f"Created {created} demo connections; {existing} already existed.")

        created = 0
        new_items = {}
        for owner_phone, name, description, listed_in in DEMO_ITEMS:
            owner = users[owner_phone]
            if Item.objects.filter(owner=owner, name=name).exists():
                continue
            item = Item.objects.create(owner=owner, name=name, description=description)
            new_items[owner_phone, name] = item
            for inventory_name in listed_in:
                inventory_id = inventories[inventory_name]
                if Membership.objects.active().filter(
                    inventory_id=inventory_id, user=owner, role__in=[Role.ADMIN, Role.OWNER]
                ).exists():
                    InventoryItem.objects.create(inventory_id=inventory_id, item=item)
            created += 1
        existing = len(DEMO_ITEMS) - created
        self.stdout.write(f"Created {created} demo items; {existing} already existed.")

        created = 0
        for owner_phone, name, borrower_phone, inventory_name, status in DEMO_LOANS:
            item = new_items.get((owner_phone, name))
            inventory_id = inventories[inventory_name]
            if (
                item is None
                or not item.listings.filter(inventory_id=inventory_id).exists()
                or not Membership.objects.active()
                .filter(inventory_id=inventory_id, user=users[borrower_phone])
                .exists()
            ):
                continue
            Item.objects.filter(pk=item.pk).update(
                loan_status=status, borrower=users[borrower_phone], loan_inventory_id=inventory_id
            )
            created += 1
        self.stdout.write(f"Created {created} demo loans and borrow requests.")
