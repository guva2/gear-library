import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from gear_library.models import Item, Membership

from .test_items_api import client_for, list_in, make_inventory, make_user
from .test_loans_api import person, set_loan


@pytest.fixture
def people():
    """Climbing: Olive owns it, Adam is an admin, Mia a member. Camping: Adam owns it, Mia
    is an admin. Hiking: only Stan, who also has a pending invite to Climbing."""
    names = ["Olive", "Adam", "Mia", "Stan"]
    olive, adam, mia, stan = (make_user(n, name) for n, name in enumerate(names, 1))
    climbing = make_inventory("Climbing", [(olive, "owner"), (adam, "admin"), (mia, "member")])
    camping = make_inventory("Camping", [(adam, "owner"), (mia, "admin")])
    hiking = make_inventory("Hiking", [(stan, "owner")])
    Membership.objects.create(inventory=climbing, user=stan, role="member", status="pending")
    return {
        "olive": olive,
        "adam": adam,
        "mia": mia,
        "stan": stan,
        "climbing": climbing,
        "camping": camping,
        "hiking": hiking,
    }


def get(user, url):
    response = client_for(user).get(url)
    assert response.status_code == 200
    return response.json()


def name_of(user):
    return {"first_name": user.first_name, "last_name": user.last_name}


def ref(inventory):
    return {"id": inventory.id, "name": inventory.name}


def query_count(user, url):
    client = client_for(user)
    with CaptureQueriesContext(connection) as captured:
        assert client.get(url).status_code == 200
    return len(captured.captured_queries)


@pytest.mark.django_db
@pytest.mark.parametrize("url", ["/api/discover/", "/api/lending/"])
def test_anonymous_callers_are_refused(url):
    assert APIClient().get(url).status_code == 403


@pytest.mark.django_db
class TestDiscover:
    url = "/api/discover/"

    def test_an_item_listed_in_two_of_the_callers_inventories_appears_once(self, people):
        rope = Item.objects.create(owner=people["adam"], name="Rope", description="60 m")
        list_in(people["climbing"], rope)
        list_in(people["camping"], rope)

        assert get(people["mia"], self.url) == [
            {
                "id": rope.id,
                "name": "Rope",
                "description": "60 m",
                "owner": name_of(people["adam"]),
                "loan_status": "available",
                "borrowed_by_me": False,
                "inventories": [ref(people["camping"]), ref(people["climbing"])],
            }
        ]

    def test_leaves_out_the_callers_own_items_and_unlisted_items(self, people):
        list_in(people["climbing"], Item.objects.create(owner=people["mia"], name="Mine"))
        Item.objects.create(owner=people["adam"], name="Unlisted")

        assert get(people["mia"], self.url) == []

    def test_lists_only_the_inventories_where_the_caller_is_an_active_member(self, people):
        rope = Item.objects.create(owner=people["adam"], name="Rope")
        list_in(people["climbing"], rope)
        list_in(people["camping"], rope)

        (seen,) = get(people["olive"], self.url)

        assert seen["inventories"] == [ref(people["climbing"])]

    def test_an_invite_shows_nothing(self, people):
        list_in(people["climbing"], Item.objects.create(owner=people["adam"], name="Rope"))

        assert get(people["stan"], self.url) == []

    def test_available_items_come_first_then_by_name(self, people):
        made = {}
        for name in ["Axe", "Bivy", "Cord", "Duct tape"]:
            made[name] = Item.objects.create(owner=people["adam"], name=name)
            list_in(people["climbing"], made[name])
        set_loan(made["Axe"], "on_loan", people["olive"], people["climbing"])
        set_loan(made["Cord"], "requested", people["mia"], people["climbing"])

        seen = get(people["mia"], self.url)

        assert [(i["name"], i["loan_status"], i["borrowed_by_me"]) for i in seen] == [
            ("Bivy", "available", False),
            ("Duct tape", "available", False),
            ("Axe", "on_loan", False),
            ("Cord", "requested", True),
        ]

    def test_the_number_of_queries_does_not_grow_with_the_items(self, people):
        def add_item(name):
            item = Item.objects.create(owner=people["adam"], name=name)
            list_in(people["climbing"], item)
            list_in(people["camping"], item)

        add_item("Rope")
        one = query_count(people["mia"], self.url)
        for name in ["Axe", "Bivy", "Cord"]:
            add_item(name)

        assert query_count(people["mia"], self.url) == one


@pytest.mark.django_db
class TestLending:
    url = "/api/lending/"

    def test_the_owner_sees_their_requested_item(self, people):
        rope = Item.objects.create(owner=people["adam"], name="Rope", description="60 m")
        list_in(people["climbing"], rope)
        list_in(people["camping"], rope)
        set_loan(rope, "requested", people["mia"], people["climbing"])

        assert get(people["adam"], self.url) == [
            {
                "id": rope.id,
                "name": "Rope",
                "description": "60 m",
                "inventories": [ref(people["camping"]), ref(people["climbing"])],
                "loan_status": "requested",
                "borrower": person(people["mia"]),
                "loan_inventory": ref(people["climbing"]),
                "owner": None,
                "can_answer": True,
            }
        ]

    def test_an_admin_of_the_loan_inventory_sees_someone_elses_item(self, people):
        rope = Item.objects.create(owner=people["adam"], name="Rope")
        list_in(people["climbing"], rope)
        list_in(people["camping"], rope)
        set_loan(rope, "requested", people["mia"], people["climbing"])

        (seen,) = get(people["olive"], self.url)

        assert seen["owner"] == name_of(people["adam"])
        assert seen["inventories"] == [ref(people["climbing"])]
        assert seen["borrower"] == person(people["mia"])
        assert seen["can_answer"] is True

    def test_a_loan_cannot_be_answered(self, people):
        rope = Item.objects.create(owner=people["adam"], name="Rope")
        list_in(people["climbing"], rope)
        set_loan(rope, "on_loan", people["mia"], people["climbing"])

        assert [i["can_answer"] for i in get(people["olive"], self.url)] == [False]
        assert [i["can_answer"] for i in get(people["adam"], self.url)] == [False]

    def test_the_owner_keeps_a_loan_whose_inventory_is_gone(self, people):
        rope = Item.objects.create(owner=people["adam"], name="Rope")
        list_in(people["climbing"], rope)
        set_loan(rope, "on_loan", people["mia"], people["climbing"])
        people["climbing"].delete()

        (seen,) = get(people["adam"], self.url)

        assert (seen["loan_inventory"], seen["inventories"], seen["can_answer"]) == (
            None,
            [],
            False,
        )

    def test_leaves_out_members_and_admins_of_other_inventories_it_is_listed_in(self, people):
        rope = Item.objects.create(owner=people["adam"], name="Rope")
        list_in(people["climbing"], rope)
        list_in(people["camping"], rope)
        set_loan(rope, "requested", people["olive"], people["climbing"])

        assert get(people["mia"], self.url) == []
        assert get(people["stan"], self.url) == []

    def test_an_admin_does_not_see_a_loan_no_longer_listed_in_their_inventory(self, people):
        rope = Item.objects.create(owner=people["adam"], name="Rope")
        list_in(people["camping"], rope)
        set_loan(rope, "on_loan", people["mia"], people["climbing"])

        assert get(people["olive"], self.url) == []
        assert [i["id"] for i in get(people["adam"], self.url)] == [rope.id]

    def test_leaves_out_the_callers_own_request(self, people):
        tent = Item.objects.create(owner=people["olive"], name="Tent")
        list_in(people["climbing"], tent)
        set_loan(tent, "requested", people["adam"], people["climbing"])
        Membership.objects.filter(inventory=people["climbing"], user=people["mia"]).update(
            role="admin"
        )

        (seen,) = get(people["mia"], self.url)

        assert seen["id"] == tent.id
        assert get(people["adam"], self.url) == []

    def test_available_items_are_left_out_and_the_rest_sorted_by_name(self, people):
        made = {}
        for name in ["Cord", "Axe", "Bivy"]:
            made[name] = Item.objects.create(owner=people["adam"], name=name)
            list_in(people["climbing"], made[name])
        set_loan(made["Cord"], "requested", people["mia"], people["climbing"])
        set_loan(made["Axe"], "on_loan", people["mia"], people["climbing"])

        assert [i["name"] for i in get(people["adam"], self.url)] == ["Axe", "Cord"]

    def test_the_number_of_queries_does_not_grow_with_the_items(self, people):
        def add_item(name, owner):
            item = Item.objects.create(owner=owner, name=name)
            list_in(people["climbing"], item)
            set_loan(item, "requested", people["mia"], people["climbing"])

        add_item("Rope", people["adam"])
        one = query_count(people["olive"], self.url)
        add_item("Axe", people["adam"])
        add_item("Bivy", people["olive"])

        assert query_count(people["olive"], self.url) == one
