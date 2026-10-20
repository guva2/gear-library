import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from gear_library.models import Inventory, InventoryItem, Item, Membership

User = get_user_model()

ITEMS_URL = "/api/items/"


def item_url(item):
    return f"{ITEMS_URL}{item.id}/"


def listings_url(inventory, item=None):
    url = f"/api/inventories/{inventory.id}/items/"
    return f"{url}{item.id}/" if item else url


def make_user(n, first_name="User"):
    return User.objects.create_user(
        phone_number=f"555123{n:04d}", first_name=first_name, last_name=f"L{n}"
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def make_inventory(name, members):
    inventory = Inventory.objects.create(name=name)
    for user, role in members:
        Membership.objects.create(inventory=inventory, user=user, role=role, status="active")
    return inventory


def list_in(inventory, *items):
    for item in items:
        InventoryItem.objects.create(inventory=inventory, item=item)


def listed(inventory):
    return set(InventoryItem.objects.filter(inventory=inventory).values_list("item", flat=True))


@pytest.fixture
def people():
    """An inventory with one user in each role, a user invited to it, and a stranger."""
    names = ["Olive", "Adam", "Mia", "Pat", "Stan"]
    owner, admin, member, pending, stranger = (
        make_user(n, name) for n, name in enumerate(names, 1)
    )
    inventory = make_inventory(
        "Climbing", [(owner, "owner"), (admin, "admin"), (member, "member")]
    )
    Membership.objects.create(
        inventory=inventory, user=pending, role="member", status="pending", invited_by=owner
    )
    return {
        "inventory": inventory,
        "owner": owner,
        "admin": admin,
        "member": member,
        "pending": pending,
        "stranger": stranger,
    }


@pytest.mark.django_db
class TestAnonymous:
    @pytest.mark.parametrize(
        "method, url",
        [
            ("get", ITEMS_URL),
            ("post", ITEMS_URL),
            ("patch", "/api/items/1/"),
            ("delete", "/api/items/1/"),
            ("get", "/api/inventories/1/items/"),
            ("post", "/api/inventories/1/items/"),
            ("delete", "/api/inventories/1/items/1/"),
        ],
    )
    def test_is_forbidden(self, method, url):
        assert getattr(APIClient(), method)(url, {}, format="json").status_code == 403


@pytest.mark.django_db
class TestMyItems:
    def test_lists_only_the_callers_items_by_name_with_where_each_is_listed(self, people):
        admin = people["admin"]
        camping = make_inventory("Camping", [(admin, "owner")])
        rope = Item.objects.create(owner=admin, name="Rope", description="60 m")
        axe = Item.objects.create(owner=admin, name="Axe")
        Item.objects.create(owner=people["owner"], name="Boots")
        list_in(people["inventory"], rope)
        list_in(camping, rope)

        response = client_for(admin).get(ITEMS_URL)

        assert response.status_code == 200
        assert response.json() == [
            {"id": axe.id, "name": "Axe", "description": "", "inventories": []},
            {
                "id": rope.id,
                "name": "Rope",
                "description": "60 m",
                "inventories": [
                    {"id": camping.id, "name": "Camping"},
                    {"id": people["inventory"].id, "name": "Climbing"},
                ],
            },
        ]

    def test_creates_an_item_owned_by_the_caller(self, people):
        response = client_for(people["stranger"]).post(
            ITEMS_URL, {"name": " Rope ", "description": " 60 m "}, format="json"
        )

        assert response.status_code == 201
        item = Item.objects.get()
        assert response.json() == {
            "id": item.id,
            "name": "Rope",
            "description": "60 m",
            "inventories": [],
        }
        assert item.owner == people["stranger"]

    @pytest.mark.parametrize("description", [None, ""])
    def test_the_description_is_optional(self, people, description):
        body = {"name": "Rope"}
        if description is not None:
            body["description"] = description

        response = client_for(people["owner"]).post(ITEMS_URL, body, format="json")

        assert response.status_code == 201
        assert Item.objects.get().description == ""

    @pytest.mark.parametrize(
        "body, field",
        [
            ({"name": ""}, "name"),
            ({"name": "   "}, "name"),
            ({"name": "x" * 65}, "name"),
            ({}, "name"),
            ({"name": "Rope", "description": "x" * 513}, "description"),
            ({"name": "Rope", "description": None}, "description"),
        ],
    )
    def test_rejects_an_invalid_field(self, people, body, field):
        response = client_for(people["owner"]).post(ITEMS_URL, body, format="json")

        assert response.status_code == 400
        assert list(response.json()) == [field]
        assert not Item.objects.exists()


@pytest.mark.django_db
class TestItemDetail:
    @pytest.fixture
    def rope(self, people):
        rope = Item.objects.create(owner=people["admin"], name="Rope")
        list_in(people["inventory"], rope)
        return rope

    def test_the_owner_edits_one_field_and_gets_the_item_back(self, people, rope):
        response = client_for(people["admin"]).patch(
            item_url(rope), {"description": "60 m"}, format="json"
        )

        assert response.status_code == 200
        assert response.json() == {
            "id": rope.id,
            "name": "Rope",
            "description": "60 m",
            "inventories": [{"id": people["inventory"].id, "name": "Climbing"}],
        }

    def test_an_invalid_edit_changes_nothing(self, people, rope):
        response = client_for(people["admin"]).patch(item_url(rope), {"name": ""}, format="json")

        assert response.status_code == 400
        assert list(response.json()) == ["name"]
        assert Item.objects.get().name == "Rope"

    @pytest.mark.parametrize("who", ["owner", "member", "stranger"])
    @pytest.mark.parametrize("method", ["patch", "delete"])
    def test_anyone_but_the_owner_gets_not_found_whatever_the_body(
        self, people, rope, who, method
    ):
        """An owner and a member of the inventory see the item there, and still get 404."""
        response = getattr(client_for(people[who]), method)(
            item_url(rope), {"name": ""}, format="json"
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "Item not found."}
        assert Item.objects.get().name == "Rope"

    def test_a_missing_item_is_not_found(self, people):
        response = client_for(people["admin"]).patch(
            "/api/items/999999/", {"name": "Rope"}, format="json"
        )

        assert response.status_code == 404

    def test_the_owner_deletes_the_item_and_its_listings(self, people, rope):
        response = client_for(people["admin"]).delete(item_url(rope))

        assert response.status_code == 204
        assert not Item.objects.exists()
        assert not InventoryItem.objects.exists()


@pytest.mark.django_db
class TestInventoryItems:
    @pytest.fixture
    def rope(self, people):
        return Item.objects.create(owner=people["admin"], name="Rope", description="60 m")

    @pytest.mark.parametrize("who", ["owner", "admin", "member"])
    def test_members_see_listed_items_with_their_owners_name(self, people, rope, who):
        tent = Item.objects.create(owner=people["owner"], name="Tent")
        Item.objects.create(owner=people["owner"], name="Unlisted")
        elsewhere = make_inventory("Elsewhere", [(people["stranger"], "owner")])
        list_in(people["inventory"], tent, rope)
        list_in(elsewhere, Item.objects.create(owner=people["stranger"], name="Kayak"))

        response = client_for(people[who]).get(listings_url(people["inventory"]))

        assert response.status_code == 200
        admin, owner = people["admin"], people["owner"]
        assert response.json() == [
            {
                "id": rope.id,
                "name": "Rope",
                "description": "60 m",
                "owner": {"id": admin.id, "first_name": "Adam", "last_name": "L2"},
            },
            {
                "id": tent.id,
                "name": "Tent",
                "description": "",
                "owner": {"id": owner.id, "first_name": "Olive", "last_name": "L1"},
            },
        ]

    @pytest.mark.parametrize("who", ["pending", "stranger"])
    def test_a_non_member_gets_not_found(self, people, rope, who):
        list_in(people["inventory"], rope)

        response = client_for(people[who]).get(listings_url(people["inventory"]))

        assert response.status_code == 404

    def test_an_admin_lists_their_item(self, people, rope):
        response = client_for(people["admin"]).post(
            listings_url(people["inventory"]), {"item_id": rope.id}, format="json"
        )

        assert response.status_code == 201
        assert response.json() == {
            "id": rope.id,
            "name": "Rope",
            "description": "60 m",
            "owner": {"id": people["admin"].id, "first_name": "Adam", "last_name": "L2"},
        }
        assert listed(people["inventory"]) == {rope.id}

    @pytest.mark.parametrize("who, code", [("member", 403), ("pending", 404), ("stranger", 404)])
    def test_access_is_checked_before_the_body(self, people, who, code):
        mine = Item.objects.create(owner=people[who], name="Mine")

        for body in [{"item_id": mine.id}, {}]:
            response = client_for(people[who]).post(
                listings_url(people["inventory"]), body, format="json"
            )
            assert response.status_code == code
        assert not InventoryItem.objects.exists()

    @pytest.mark.parametrize("whose", ["another admin", "missing"])
    def test_an_item_that_is_not_the_callers_is_one_400(self, people, rope, whose):
        item_id = rope.id if whose == "another admin" else 999999

        response = client_for(people["owner"]).post(
            listings_url(people["inventory"]), {"item_id": item_id}, format="json"
        )

        assert response.status_code == 400
        assert response.json() == {"item_id": ["You can list only your own items."]}

    @pytest.mark.parametrize("item_id", [None, "rope"])
    def test_a_missing_or_non_integer_item_id_is_a_field_error(self, people, item_id):
        body = {} if item_id is None else {"item_id": item_id}

        response = client_for(people["owner"]).post(
            listings_url(people["inventory"]), body, format="json"
        )

        assert response.status_code == 400
        assert list(response.json()) == ["item_id"]

    def test_listing_twice_conflicts(self, people, rope):
        list_in(people["inventory"], rope)

        response = client_for(people["admin"]).post(
            listings_url(people["inventory"]), {"item_id": rope.id}, format="json"
        )

        assert response.status_code == 409
        assert response.json() == {"detail": "This item is already listed in this inventory."}


@pytest.mark.django_db
class TestRemoveListing:
    @pytest.fixture
    def rope(self, people):
        rope = Item.objects.create(owner=people["admin"], name="Rope")
        list_in(people["inventory"], rope)
        return rope

    def remove(self, people, who, item):
        return client_for(people[who]).delete(listings_url(people["inventory"], item))

    @pytest.mark.parametrize("who", ["admin", "owner"])
    def test_the_items_owner_or_an_inventory_owner_removes_it(self, people, rope, who):
        response = self.remove(people, who, rope)

        assert response.status_code == 204
        assert listed(people["inventory"]) == set()
        assert Item.objects.filter(pk=rope.pk).exists()

    def test_an_admin_cannot_remove_someone_elses_item(self, people, rope):
        tent = Item.objects.create(owner=people["owner"], name="Tent")
        list_in(people["inventory"], tent)

        response = self.remove(people, "admin", tent)

        assert response.status_code == 403
        assert response.json() == {"detail": "Only owners can remove other people's items."}
        assert listed(people["inventory"]) == {rope.id, tent.id}

    @pytest.mark.parametrize("who, code", [("member", 403), ("pending", 404), ("stranger", 404)])
    def test_others_are_refused(self, people, rope, who, code):
        assert self.remove(people, who, rope).status_code == code
        assert listed(people["inventory"]) == {rope.id}

    def test_an_item_not_listed_here_is_not_found(self, people):
        unlisted = Item.objects.create(owner=people["admin"], name="Axe")

        response = self.remove(people, "admin", unlisted)

        assert response.status_code == 404
        assert response.json() == {"detail": "This item is not listed in this inventory."}
