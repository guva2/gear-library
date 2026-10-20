import pytest
from rest_framework.test import APIClient

from gear_library.models import Item, Membership

from .test_items_api import client_for, list_in, listings_url, make_inventory, make_user


@pytest.fixture
def people():
    """Climbing: Olive owns it, the admin Adam lists his rope there, and Mia and Max are
    members. Stan is a stranger."""
    names = ["Olive", "Adam", "Mia", "Max", "Stan"]
    olive, adam, mia, max_, stan = (make_user(n, name) for n, name in enumerate(names, 1))
    inventory = make_inventory(
        "Climbing", [(olive, "owner"), (adam, "admin"), (mia, "member"), (max_, "member")]
    )
    rope = Item.objects.create(owner=adam, name="Rope", description="60 m")
    list_in(inventory, rope)
    return {
        "inventory": inventory,
        "olive": olive,
        "adam": adam,
        "mia": mia,
        "max": max_,
        "stan": stan,
        "rope": rope,
    }


def action_url(people, action, item=None):
    return f"{listings_url(people['inventory'], item or people['rope'])}{action}/"


def set_loan(item, status, borrower, inventory):
    Item.objects.filter(pk=item.pk).update(
        loan_status=status, borrower=borrower, loan_inventory=inventory
    )


def loan_of(item):
    item.refresh_from_db()
    return (item.loan_status, item.borrower_id, item.loan_inventory_id)


def listed_rope(people, who):
    response = client_for(people[who]).get(listings_url(people["inventory"]))
    assert response.status_code == 200
    (rope,) = response.json()
    return rope


def person(user):
    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone_number": user.phone_number,
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    [
        "/api/inventories/1/items/1/borrow/",
        "/api/inventories/1/items/1/approve/",
        "/api/inventories/1/items/1/decline/",
        "/api/inventories/1/items/1/return/",
        "/api/borrowing/1/cancel/",
        "/api/items/1/return/",
    ],
)
def test_anonymous_callers_are_refused(url):
    assert APIClient().post(url).status_code == 403


@pytest.mark.django_db
def test_anonymous_callers_cannot_see_their_borrowing():
    assert APIClient().get("/api/borrowing/").status_code == 403


@pytest.mark.django_db
class TestBorrow:
    def test_a_member_requests_an_item(self, people):
        response = client_for(people["mia"]).post(action_url(people, "borrow"))

        assert response.status_code == 204
        assert loan_of(people["rope"]) == ("requested", people["mia"].id, people["inventory"].id)

    @pytest.mark.parametrize("who, code", [("stan", 404), ("adam", 403)])
    def test_a_non_member_and_the_owner_are_refused(self, people, who, code):
        response = client_for(people[who]).post(action_url(people, "borrow"))

        assert response.status_code == code
        assert loan_of(people["rope"])[0] == "available"

    def test_an_item_not_listed_here_is_not_found(self, people):
        tent = Item.objects.create(owner=people["olive"], name="Tent")

        response = client_for(people["mia"]).post(action_url(people, "borrow", tent))

        assert response.status_code == 404
        assert response.json() == {"detail": "This item is not listed in this inventory."}

    def test_an_item_already_requested_conflicts(self, people):
        client_for(people["max"]).post(action_url(people, "borrow"))

        response = client_for(people["mia"]).post(action_url(people, "borrow"))

        assert response.status_code == 409
        assert response.json() == {
            "detail": "This item has already been requested or is on loan."
        }


@pytest.mark.django_db
class TestApproveDeclineReturn:
    @pytest.mark.parametrize(
        "action, status, after",
        [
            ("approve", "requested", "on_loan"),
            ("decline", "requested", "available"),
            ("return", "on_loan", "available"),
        ],
    )
    def test_an_admin_changes_the_loan(self, people, action, status, after):
        set_loan(people["rope"], status, people["mia"], people["inventory"])

        response = client_for(people["adam"]).post(
            action_url(people, action), {"borrower_id": people["mia"].id}, format="json"
        )

        assert response.status_code == 204
        assert loan_of(people["rope"])[0] == after

    @pytest.mark.parametrize("action", ["approve", "decline", "return"])
    @pytest.mark.parametrize("who, code", [("stan", 404), ("max", 403)])
    def test_access_is_checked_before_the_body(self, people, action, who, code):
        response = client_for(people[who]).post(action_url(people, action), {}, format="json")

        assert response.status_code == code

    @pytest.mark.parametrize("action", ["approve", "decline", "return"])
    def test_the_borrower_id_is_required(self, people, action):
        response = client_for(people["olive"]).post(action_url(people, action), {}, format="json")

        assert response.status_code == 400
        assert response.json() == {"borrower_id": ["This field is required."]}

    @pytest.mark.parametrize(
        "action, status, message",
        [
            ("approve", "requested", "You cannot approve or decline your own request."),
            ("return", "on_loan", "You cannot mark your own loan returned."),
        ],
    )
    def test_the_borrower_cannot_act_on_their_own_loan(self, people, action, status, message):
        set_loan(people["rope"], status, people["olive"], people["inventory"])

        response = client_for(people["olive"]).post(
            action_url(people, action), {"borrower_id": people["olive"].id}, format="json"
        )

        assert response.status_code == 403
        assert response.json() == {"detail": message}

    def test_a_request_that_changed_conflicts(self, people):
        set_loan(people["rope"], "requested", people["max"], people["inventory"])

        response = client_for(people["olive"]).post(
            action_url(people, "approve"), {"borrower_id": people["mia"].id}, format="json"
        )

        assert response.status_code == 409
        assert response.json() == {"detail": "This request or loan changed. Try again."}


@pytest.mark.django_db
class TestCancel:
    def url(self, item):
        return f"/api/borrowing/{item.id}/cancel/"

    def test_the_requester_cancels(self, people):
        set_loan(people["rope"], "requested", people["mia"], people["inventory"])

        response = client_for(people["mia"]).post(self.url(people["rope"]))

        assert response.status_code == 204
        assert loan_of(people["rope"])[0] == "available"

    def test_someone_elses_request_is_not_found(self, people):
        set_loan(people["rope"], "requested", people["mia"], people["inventory"])

        response = client_for(people["max"]).post(self.url(people["rope"]))

        assert response.status_code == 404
        assert response.json() == {"detail": "Request not found."}

    def test_an_approved_request_conflicts(self, people):
        set_loan(people["rope"], "on_loan", people["mia"], people["inventory"])

        response = client_for(people["mia"]).post(self.url(people["rope"]))

        assert response.status_code == 409


@pytest.mark.django_db
class TestOwnerMarksReturned:
    def url(self, item):
        return f"/api/items/{item.id}/return/"

    def test_the_owner_marks_it_returned(self, people):
        set_loan(people["rope"], "on_loan", people["mia"], None)

        response = client_for(people["adam"]).post(
            self.url(people["rope"]), {"borrower_id": people["mia"].id}, format="json"
        )

        assert response.status_code == 204
        assert loan_of(people["rope"]) == ("available", None, None)

    @pytest.mark.parametrize("who", ["mia", "olive"])
    def test_anyone_else_is_not_found_before_the_body_is_read(self, people, who):
        set_loan(people["rope"], "on_loan", people["mia"], None)

        response = client_for(people[who]).post(self.url(people["rope"]), {}, format="json")

        assert response.status_code == 404
        assert response.json() == {"detail": "Item not found."}

    def test_the_borrower_id_is_required(self, people):
        response = client_for(people["adam"]).post(self.url(people["rope"]), {}, format="json")

        assert response.status_code == 400
        assert response.json() == {"borrower_id": ["This field is required."]}

    def test_an_item_not_on_loan_conflicts(self, people):
        response = client_for(people["adam"]).post(
            self.url(people["rope"]), {"borrower_id": people["mia"].id}, format="json"
        )

        assert response.status_code == 409


@pytest.mark.django_db
class TestListedItems:
    def test_an_available_item(self, people):
        rope = listed_rope(people, "mia")

        assert (rope["loan_status"], rope["borrowed_by_me"], rope["borrower"]) == (
            "available",
            False,
            None,
        )

    @pytest.mark.parametrize("status", ["requested", "on_loan"])
    def test_admins_and_owners_see_the_borrower(self, people, status):
        set_loan(people["rope"], status, people["mia"], people["inventory"])

        for who in ("olive", "adam"):
            rope = listed_rope(people, who)
            assert (rope["loan_status"], rope["borrower"]) == (status, person(people["mia"]))

    def test_other_members_see_only_the_status(self, people):
        set_loan(people["rope"], "requested", people["mia"], people["inventory"])

        rope = listed_rope(people, "max")

        assert (rope["loan_status"], rope["borrowed_by_me"], rope["borrower"]) == (
            "requested",
            False,
            None,
        )

    def test_the_requester_sees_their_own_request(self, people):
        set_loan(people["rope"], "requested", people["mia"], people["inventory"])

        rope = listed_rope(people, "mia")

        assert (rope["borrowed_by_me"], rope["borrower"]) == (True, None)

    def test_admins_do_not_see_the_borrower_of_a_loan_through_another_inventory(self, people):
        other = make_inventory("Camping", [(people["adam"], "owner")])
        list_in(other, people["rope"])
        set_loan(people["rope"], "on_loan", people["mia"], other)

        rope = listed_rope(people, "olive")

        assert (rope["loan_status"], rope["borrower"]) == ("on_loan", None)

    def test_listing_an_item_returns_its_loan_status(self, people):
        tent = Item.objects.create(owner=people["adam"], name="Tent")
        set_loan(tent, "on_loan", people["mia"], None)

        response = client_for(people["adam"]).post(
            listings_url(people["inventory"]), {"item_id": tent.id}, format="json"
        )

        assert response.status_code == 201
        assert (response.json()["loan_status"], response.json()["borrower"]) == ("on_loan", None)


@pytest.mark.django_db
class TestOwnItems:
    def get_rope(self, people):
        response = client_for(people["adam"]).get("/api/items/")
        (rope,) = response.json()
        return rope

    def test_an_available_item(self, people):
        rope = self.get_rope(people)

        assert (rope["loan_status"], rope["borrower"], rope["loan_inventory"]) == (
            "available",
            None,
            None,
        )

    def test_the_owner_sees_the_borrower_and_the_loan_inventory(self, people):
        set_loan(people["rope"], "on_loan", people["mia"], people["inventory"])

        rope = self.get_rope(people)

        assert rope["loan_status"] == "on_loan"
        assert rope["borrower"] == person(people["mia"])
        assert rope["loan_inventory"] == {"id": people["inventory"].id, "name": "Climbing"}

    def test_a_loan_whose_inventory_is_gone(self, people):
        set_loan(people["rope"], "on_loan", people["mia"], None)

        rope = self.get_rope(people)

        assert (rope["borrower"], rope["loan_inventory"]) == (person(people["mia"]), None)

    def test_an_item_on_loan_cannot_be_deleted(self, people):
        set_loan(people["rope"], "on_loan", people["mia"], people["inventory"])

        response = client_for(people["adam"]).delete(f"/api/items/{people['rope'].id}/")

        assert response.status_code == 409
        assert response.json() == {
            "detail": "This item is on loan. It can be deleted once it is returned."
        }
        assert Item.objects.filter(pk=people["rope"].pk).exists()


@pytest.mark.django_db
class TestBorrowing:
    def get(self, user):
        response = client_for(user).get("/api/borrowing/")
        assert response.status_code == 200
        return response.json()

    def test_lists_the_callers_requests_and_loans_with_owner_names_only(self, people):
        tent = Item.objects.create(owner=people["olive"], name="Tent")
        list_in(people["inventory"], tent)
        set_loan(people["rope"], "requested", people["mia"], people["inventory"])
        set_loan(tent, "on_loan", people["mia"], people["inventory"])
        Item.objects.create(owner=people["olive"], name="Axe")

        assert self.get(people["mia"]) == [
            {
                "id": people["rope"].id,
                "name": "Rope",
                "description": "60 m",
                "loan_status": "requested",
                "owner": {"first_name": "Adam", "last_name": "L2"},
                "loan_inventory": {"id": people["inventory"].id, "name": "Climbing"},
            },
            {
                "id": tent.id,
                "name": "Tent",
                "description": "",
                "loan_status": "on_loan",
                "owner": {"first_name": "Olive", "last_name": "L1"},
                "loan_inventory": {"id": people["inventory"].id, "name": "Climbing"},
            },
        ]
        assert self.get(people["max"]) == []

    def test_a_loan_stays_visible_after_the_borrower_leaves_and_the_inventory_goes(
        self, people
    ):
        set_loan(people["rope"], "on_loan", people["mia"], people["inventory"])
        Membership.objects.filter(user=people["mia"]).delete()
        people["inventory"].delete()

        (rope,) = self.get(people["mia"])

        assert (rope["loan_status"], rope["loan_inventory"]) == ("on_loan", None)
