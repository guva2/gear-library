import re

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.permissions import SAFE_METHODS

from gear_library import urls
from gear_library.models import Connection, Item, Membership, ordered_pair

from .test_items_api import client_for, list_in, make_inventory, make_user

ROUTES = {
    ("health/", "GET"),
    ("auth/csrf/", "GET"),
    ("auth/register/", "POST"),
    ("auth/login/", "POST"),
    ("auth/logout/", "POST"),
    ("auth/me/", "GET"),
    ("inventories/", "GET"),
    ("inventories/", "POST"),
    ("inventories/{id}/", "GET"),
    ("inventories/{id}/", "PATCH"),
    ("inventories/{id}/", "DELETE"),
    ("inventories/{id}/members/", "GET"),
    ("inventories/{id}/members/{id}/", "PATCH"),
    ("inventories/{id}/members/{id}/", "DELETE"),
    ("inventories/{id}/invites/", "GET"),
    ("inventories/{id}/invites/", "POST"),
    ("inventories/{id}/items/", "GET"),
    ("inventories/{id}/items/", "POST"),
    ("inventories/{id}/items/{id}/", "DELETE"),
    ("inventories/{id}/items/{id}/borrow/", "POST"),
    ("inventories/{id}/items/{id}/approve/", "POST"),
    ("inventories/{id}/items/{id}/decline/", "POST"),
    ("inventories/{id}/items/{id}/return/", "POST"),
    ("invites/", "GET"),
    ("invites/{id}/accept/", "POST"),
    ("invites/{id}/decline/", "POST"),
    ("invites/{id}/revoke/", "POST"),
    ("connections/", "GET"),
    ("connections/", "POST"),
    ("connections/requests/", "GET"),
    ("connections/{id}/", "DELETE"),
    ("connections/{id}/accept/", "POST"),
    ("connections/{id}/decline/", "POST"),
    ("connections/{id}/cancel/", "POST"),
    ("items/", "GET"),
    ("items/", "POST"),
    ("items/{id}/", "PATCH"),
    ("items/{id}/", "DELETE"),
    ("items/{id}/return/", "POST"),
    ("borrowing/", "GET"),
    ("borrowing/{id}/cancel/", "POST"),
}


def methods_of(callback):
    """The HTTP methods a URL pattern's view answers, apart from HEAD and OPTIONS."""
    actions = getattr(callback, "actions", None)
    if actions is not None:
        methods = set(actions)
    else:
        view = callback.cls
        methods = {m for m in view.http_method_names if hasattr(view, m)}
    return {m.upper() for m in methods - {"head", "options"}}


def routes():
    """Every (path, method) the API answers, with each `<int:…>` written as `{id}`."""
    found = []
    for pattern in urls.urlpatterns:
        path = re.sub(r"<int:\w+>", "{id}", str(pattern.pattern))
        found += [(path, method) for method in methods_of(pattern.callback)]
    return found


def test_the_api_answers_exactly_these_paths_and_methods():
    found = routes()

    assert len(found) == len(set(found))
    assert set(found) == ROUTES


def is_savepoint(sql):
    return sql.startswith(("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT"))


def queries_of(send):
    with CaptureQueriesContext(connection) as captured:
        send()
    return [q["sql"] for q in captured.captured_queries if not is_savepoint(q["sql"])]


def locks(sql, inventory):
    return (
        sql.startswith('SELECT "gear_library_inventory".')
        and f'"gear_library_inventory"."id" = {inventory.id}' in sql
        and sql.endswith("FOR UPDATE")
    )


SCOPED = sorted(route for route in ROUTES if route[0].startswith("inventories/{id}/"))


def fill(path, inventory_id, other_id):
    """`path` with its first `{id}` set to `inventory_id` and any other to `other_id`."""
    return path.replace("{id}", str(inventory_id), 1).replace("{id}", str(other_id))


def scoped_url(path, inventory):
    return "/api/" + fill(path, inventory.id, 999999)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path, method", [route for route in SCOPED if route[1] not in SAFE_METHODS]
)
def test_every_change_under_an_inventory_locks_it_before_any_other_query(path, method):
    owner = make_user(1)
    inventory = make_inventory("Climbing", [(owner, "owner")])
    client = client_for(owner)

    sent = queries_of(
        lambda: getattr(client, method.lower())(scoped_url(path, inventory), {}, format="json")
    )

    assert sent and locks(sent[0], inventory), sent[:1]


@pytest.mark.django_db
@pytest.mark.parametrize("path, method", [route for route in SCOPED if route[1] == "GET"])
def test_reads_under_an_inventory_take_no_lock(path, method):
    owner = make_user(1)
    inventory = make_inventory("Climbing", [(owner, "owner")])

    sent = queries_of(lambda: client_for(owner).get(scoped_url(path, inventory)))

    assert not any("FOR UPDATE" in sql for sql in sent)


@pytest.mark.django_db
@pytest.mark.parametrize("accept", ["application/json", "text/html"])
def test_options_and_the_browsable_api_take_no_lock(accept):
    owner = make_user(1)
    inventory = make_inventory("Climbing", [(owner, "owner")])
    client = client_for(owner)
    url = f"/api/inventories/{inventory.id}/items/"
    responses = []

    sent = queries_of(
        lambda: responses.extend(
            [client.options(url, HTTP_ACCEPT=accept), client.get(url, HTTP_ACCEPT=accept)]
        )
    )

    assert [r.status_code for r in responses] == [200, 200]
    assert not any("FOR UPDATE" in sql for sql in sent)


def connect(user, other, status="accepted"):
    first, second = ordered_pair(user, other)
    return Connection.objects.create(
        first_user_id=first, second_user_id=second, requested_by=user, status=status
    )


@pytest.fixture
def people():
    """Climbing: Olive owns it, the admin Adam and the member Mia. Olive's rope is listed
    there, her tent is not. Pat is invited by Olive, Stan is a stranger, Ada and Bob are
    connected."""
    names = ["Olive", "Adam", "Mia", "Pat", "Stan", "Ada", "Bob"]
    olive, adam, mia, pat, stan, ada, bob = (
        make_user(n, name) for n, name in enumerate(names, 1)
    )
    inventory = make_inventory("Climbing", [(olive, "owner"), (adam, "admin"), (mia, "member")])
    rope = Item.objects.create(owner=olive, name="Rope")
    tent = Item.objects.create(owner=olive, name="Tent")
    list_in(inventory, rope)
    invite = Membership.objects.create(
        inventory=inventory, user=pat, role="member", status="pending", invited_by=olive
    )
    return {
        "inventory": inventory,
        "olive": olive,
        "adam": adam,
        "mia": mia,
        "pat": pat,
        "stan": stan,
        "rope": rope,
        "tent": tent,
        "invite": invite,
        "connection": connect(ada, bob),
    }


INVENTORY_NOT_FOUND = "Inventory not found."
MEMBER_NOT_FOUND = "This user is not a member of the inventory."
NOT_LISTED = "This item is not listed in this inventory."
ITEM_NOT_FOUND = "Item not found."
INVITE_NOT_FOUND = "Invite not found."
CONNECTION_NOT_FOUND = "Connection not found."
REQUEST_NOT_FOUND = "Request not found."

# (caller, method, path, body, detail). `{inv}`, `{rope}`, `{tent}`, `{stan}`, `{invite}` and
# `{connection}` are filled in from the fixture; `{none}` is an id nothing has.
NOT_FOUND_CASES = [
    *(
        ("stan", method, fill(path, "{inv}", "{rope}"), {}, INVENTORY_NOT_FOUND)
        for path, method in SCOPED
    ),
    ("olive", "get", "inventories/{none}/", {}, INVENTORY_NOT_FOUND),
    ("olive", "patch", "inventories/{none}/", {"name": "X"}, INVENTORY_NOT_FOUND),
    ("pat", "delete", "inventories/{inv}/members/{pat}/", {}, INVENTORY_NOT_FOUND),
    ("olive", "patch", "inventories/{inv}/members/{stan}/", {"role": "admin"}, MEMBER_NOT_FOUND),
    ("olive", "delete", "inventories/{inv}/members/{stan}/", {}, MEMBER_NOT_FOUND),
    ("olive", "delete", "inventories/{inv}/members/{pat}/", {}, MEMBER_NOT_FOUND),
    ("olive", "delete", "inventories/{inv}/items/{tent}/", {}, NOT_LISTED),
    ("mia", "post", "inventories/{inv}/items/{tent}/borrow/", {}, NOT_LISTED),
    *(
        ("adam", "post", f"inventories/{{inv}}/items/{{tent}}/{action}/", {"borrower_id": 1},
         NOT_LISTED)
        for action in ["approve", "decline", "return"]
    ),
    ("adam", "patch", "items/{rope}/", {"name": "Mine"}, ITEM_NOT_FOUND),
    ("adam", "delete", "items/{rope}/", {}, ITEM_NOT_FOUND),
    ("adam", "post", "items/{rope}/return/", {"borrower_id": 1}, ITEM_NOT_FOUND),
    ("olive", "patch", "items/{none}/", {"name": "Mine"}, ITEM_NOT_FOUND),
    ("olive", "delete", "items/{none}/", {}, ITEM_NOT_FOUND),
    ("olive", "post", "items/{none}/return/", {"borrower_id": 1}, ITEM_NOT_FOUND),
    *(
        (who, "post", f"invites/{{{invite}}}/{action}/", {}, INVITE_NOT_FOUND)
        for who in ["mia", "stan"]
        for invite in ["invite", "none"]
        for action in ["accept", "decline", "revoke"]
    ),
    *(
        ("stan", method, f"connections/{{{connection}}}/{suffix}", {}, CONNECTION_NOT_FOUND)
        for connection in ["connection", "none"]
        for method, suffix in [
            ("delete", ""),
            ("post", "accept/"),
            ("post", "decline/"),
            ("post", "cancel/"),
        ]
    ),
    ("mia", "post", "borrowing/{rope}/cancel/", {}, REQUEST_NOT_FOUND),
    ("mia", "post", "borrowing/{none}/cancel/", {}, REQUEST_NOT_FOUND),
]


@pytest.mark.django_db
@pytest.mark.parametrize("who, method, path, body, detail", NOT_FOUND_CASES)
def test_every_not_found_has_its_own_message(people, who, method, path, body, detail):
    ids = {
        "inv": people["inventory"].id,
        "rope": people["rope"].id,
        "tent": people["tent"].id,
        "stan": people["stan"].id,
        "pat": people["pat"].id,
        "invite": people["invite"].id,
        "connection": people["connection"].id,
        "none": 999999,
    }
    url = "/api/" + path.format(**ids)

    response = getattr(client_for(people[who]), method.lower())(url, body, format="json")

    assert (response.status_code, response.json()) == (404, {"detail": detail})


def members_url(people, user):
    return f"/api/inventories/{people['inventory'].id}/members/{user.id}/"


@pytest.mark.django_db
class TestMembersLeavingAndRemoving:
    def test_a_member_leaves(self, people):
        response = client_for(people["mia"]).delete(members_url(people, people["mia"]))

        assert response.status_code == 204
        assert not Membership.objects.filter(user=people["mia"]).exists()

    @pytest.mark.parametrize("who", ["mia", "adam"])
    def test_anyone_but_an_owner_removing_someone_else_is_forbidden(self, people, who):
        target = people["adam" if who == "mia" else "mia"]

        response = client_for(people[who]).delete(members_url(people, target))

        assert response.status_code == 403
        assert response.json() == {"detail": "Only owners can do this."}
        assert Membership.objects.filter(user=target).exists()


@pytest.mark.django_db
class TestActingOnAnotherMembersItem:
    """Only removing a listing is limited to the caller's own items."""

    def post(self, people, who, action, body=None):
        url = f"/api/inventories/{people['inventory'].id}/items/{people['rope'].id}/{action}/"
        return client_for(people[who]).post(url, body or {}, format="json")

    def set_loan(self, people, status):
        Item.objects.filter(pk=people["rope"].pk).update(
            loan_status=status, borrower=people["mia"], loan_inventory=people["inventory"]
        )

    def test_a_member_borrows_another_members_item(self, people):
        assert self.post(people, "mia", "borrow").status_code == 204

    @pytest.mark.parametrize(
        "action, status",
        [("approve", "requested"), ("decline", "requested"), ("return", "on_loan")],
    )
    def test_an_admin_acts_on_a_loan_of_another_members_item(self, people, action, status):
        self.set_loan(people, status)

        response = self.post(people, "adam", action, {"borrower_id": people["mia"].id})

        assert response.status_code == 204

    def test_an_admin_cannot_remove_another_members_listing(self, people):
        url = f"/api/inventories/{people['inventory'].id}/items/{people['rope'].id}/"

        response = client_for(people["adam"]).delete(url)

        assert response.status_code == 403
        assert response.json() == {"detail": "Only owners can remove other people's items."}
