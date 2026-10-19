from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

DEMO_PASSWORD = "gear-library-demo"

# 555-01xx numbers are reserved for fictional use.
DEMO_USERS = [
    ("5555550101", "Avery", "Brooks"),
    ("5555550102", "Jordan", "Diaz"),
    ("5555550103", "Sam", "Okafor"),
]


class Command(BaseCommand):
    help = "Create the demo users. Users that already exist are left unchanged."

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
