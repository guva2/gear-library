import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from gear_library.models import Inventory, InventoryInvite, Membership

User = get_user_model()

INVENTORIES_URL = "/api/inventories/"
INVITES_URL = "/api/invites/"


def inventory_url(inventory, suffix=""):
    return f"{INVENTORIES_URL}{inventory.id}/{suffix}"


def make_user(n, first_name="User"):
    return User.objects.create_user(
        phone_number=f"555123{n:04d}", first_name=first_name, last_name=f"L{n}"
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def full(user, role):
    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone_number": user.phone_number,
        "role": role,
    }


def name_of(user):
    return {"first_name": user.first_name, "last_name": user.last_name}


@pytest.fixture
def people():
    """An inventory with one user in each role, and a stranger outside it."""
    names = ["Olive", "Adam", "Mia", "Stan"]
    owner, admin, member, stranger = (make_user(n, name) for n, name in enumerate(names, 1))
    inventory = Inventory.objects.create(name="Climbing")
    for user, role in [(owner, "owner"), (admin, "admin"), (member, "member")]:
        Membership.objects.create(inventory=inventory, user=user, role=role)
    return {
        "inventory": inventory,
        "owner": owner,
        "admin": admin,
        "member": member,
        "stranger": stranger,
    }


@pytest.mark.django_db
class TestAnonymous:
    @pytest.mark.parametrize(
        "method, url",
        [
            ("get", INVENTORIES_URL),
            ("post", INVENTORIES_URL),
            ("get", "/api/inventories/1/"),
            ("get", "/api/inventories/1/members/"),
            ("get", INVITES_URL),
            ("post", "/api/invites/1/accept/"),
        ],
    )
    def test_is_forbidden(self, method, url):
        assert getattr(APIClient(), method)(url, {}, format="json").status_code == 403


@pytest.mark.django_db
class TestInventories:
    def test_lists_only_the_callers_inventories_with_their_role(self, people):
        other = Inventory.objects.create(name="Elsewhere")
        Membership.objects.create(inventory=other, user=people["stranger"], role="owner")

        response = client_for(people["admin"]).get(INVENTORIES_URL)

        assert response.status_code == 200
        assert response.json() == [
            {"id": people["inventory"].id, "name": "Climbing", "role": "admin"}
        ]

    def test_creating_makes_the_caller_owner(self, people):
        response = client_for(people["stranger"]).post(
            INVENTORIES_URL, {"name": "  Camping "}, format="json"
        )

        assert response.status_code == 201
        inventory = Inventory.objects.get(name="Camping")
        assert response.json() == {"id": inventory.id, "name": "Camping", "role": "owner"}
        assert Membership.objects.get(inventory=inventory).user == people["stranger"]

    @pytest.mark.parametrize("name", ["", "   ", "x" * 33, None])
    def test_rejects_a_blank_or_long_name(self, people, name):
        response = client_for(people["owner"]).post(
            INVENTORIES_URL, {"name": name}, format="json"
        )

        assert response.status_code == 400
        assert list(response.json()) == ["name"]

    def test_a_member_reads_the_inventory(self, people):
        response = client_for(people["member"]).get(inventory_url(people["inventory"]))

        assert response.json() == {
            "id": people["inventory"].id,
            "name": "Climbing",
            "role": "member",
        }

    @pytest.mark.parametrize(
        "method, suffix",
        [
            ("get", ""),
            ("patch", ""),
            ("delete", ""),
            ("get", "members/"),
            ("patch", "members/1/"),
            ("delete", "members/1/"),
            ("get", "invites/"),
            ("post", "invites/"),
        ],
    )
    def test_a_non_member_gets_not_found(self, people, method, suffix):
        client = client_for(people["stranger"])
        url = inventory_url(people["inventory"], suffix)

        response = getattr(client, method)(url, {"name": "x", "role": "member"}, format="json")

        assert response.status_code == 404
        assert Inventory.objects.get().name == "Climbing"

    def test_an_owner_renames(self, people):
        response = client_for(people["owner"]).patch(
            inventory_url(people["inventory"]), {"name": "Bouldering"}, format="json"
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Bouldering"
        assert Inventory.objects.get().name == "Bouldering"

    @pytest.mark.parametrize("role", ["member", "admin"])
    def test_only_owners_rename_or_delete(self, people, role):
        client = client_for(people[role])
        url = inventory_url(people["inventory"])

        assert client.patch(url, {"name": "Mine"}, format="json").status_code == 403
        assert client.delete(url).status_code == 403
        assert Inventory.objects.get().name == "Climbing"

    def test_access_is_checked_before_the_body(self, people):
        client = client_for(people["admin"])

        rename = client.patch(inventory_url(people["inventory"]), {"name": ""}, format="json")
        set_role = client.patch(
            inventory_url(people["inventory"], f"members/{people['member'].id}/"),
            {"role": "boss"},
            format="json",
        )

        assert (rename.status_code, set_role.status_code) == (403, 403)

    def test_an_owner_deletes_it_with_its_memberships_and_invites(self, people):
        InventoryInvite.objects.create(
            inventory=people["inventory"], invitee=people["stranger"], invited_by=people["owner"]
        )

        response = client_for(people["owner"]).delete(inventory_url(people["inventory"]))

        assert response.status_code == 204
        assert not Inventory.objects.exists()
        assert not Membership.objects.exists()
        assert not InventoryInvite.objects.exists()


@pytest.mark.django_db
class TestMembers:
    def test_a_member_sees_only_the_names_of_admins_and_owners(self, people):
        url = inventory_url(people["inventory"], "members/")
        response = client_for(people["member"]).get(url)

        assert response.status_code == 200
        body = response.json()
        assert sorted(body, key=lambda p: p["first_name"]) == [
            name_of(people["admin"]),
            name_of(people["owner"]),
        ]

    @pytest.mark.parametrize("role", ["admin", "owner"])
    def test_admins_and_owners_see_everyone_with_phone_and_role(self, people, role):
        response = client_for(people[role]).get(inventory_url(people["inventory"], "members/"))

        assert sorted(response.json(), key=lambda p: p["first_name"]) == [
            full(people["admin"], "admin"),
            full(people["member"], "member"),
            full(people["owner"], "owner"),
        ]

    def member_url(self, people, user):
        return inventory_url(people["inventory"], f"members/{user.id}/")

    def test_an_owner_sets_a_role(self, people):
        response = client_for(people["owner"]).patch(
            self.member_url(people, people["member"]), {"role": "admin"}, format="json"
        )

        assert response.status_code == 200
        assert response.json() == full(people["member"], "admin")

    def test_an_admin_cannot_set_a_role(self, people):
        response = client_for(people["admin"]).patch(
            self.member_url(people, people["member"]), {"role": "admin"}, format="json"
        )

        assert response.status_code == 403
        assert Membership.objects.get(user=people["member"]).role == "member"

    @pytest.mark.parametrize("role", ["boss", "", None])
    def test_rejects_an_unknown_role(self, people, role):
        response = client_for(people["owner"]).patch(
            self.member_url(people, people["member"]), {"role": role}, format="json"
        )

        assert response.status_code == 400
        assert list(response.json()) == ["role"]

    def test_the_last_owner_cannot_step_down(self, people):
        response = client_for(people["owner"]).patch(
            self.member_url(people, people["owner"]), {"role": "admin"}, format="json"
        )

        assert response.status_code == 409
        assert response.json() == {"detail": "An inventory must keep at least one owner."}

    def test_setting_the_role_of_a_non_member_is_not_found(self, people):
        response = client_for(people["owner"]).patch(
            self.member_url(people, people["stranger"]), {"role": "admin"}, format="json"
        )

        assert response.status_code == 404

    def test_an_owner_removes_a_member(self, people):
        response = client_for(people["owner"]).delete(self.member_url(people, people["admin"]))

        assert response.status_code == 204
        assert not Membership.objects.filter(user=people["admin"]).exists()

    def test_an_admin_cannot_remove_a_member(self, people):
        response = client_for(people["admin"]).delete(self.member_url(people, people["member"]))

        assert response.status_code == 403

    def test_a_member_leaves(self, people):
        response = client_for(people["member"]).delete(self.member_url(people, people["member"]))

        assert response.status_code == 204
        again = client_for(people["member"]).get(inventory_url(people["inventory"]))
        assert again.status_code == 404

    def test_the_last_owner_cannot_leave(self, people):
        response = client_for(people["owner"]).delete(self.member_url(people, people["owner"]))

        assert response.status_code == 409


@pytest.mark.django_db
class TestInventoryInvites:
    def invite(self, people, actor, phone_number):
        return client_for(people[actor]).post(
            inventory_url(people["inventory"], "invites/"),
            {"phone_number": phone_number},
            format="json",
        )

    @pytest.mark.parametrize("actor", ["admin", "owner"])
    def test_admins_and_owners_invite_by_a_formatted_phone_number(self, people, actor):
        response = self.invite(people, actor, "(555) 123-0004")

        assert response.status_code == 201
        invite = InventoryInvite.objects.get()
        assert response.json() == {
            "id": invite.id,
            "invitee": {"phone_number": "5551230004"},
            "invited_by": name_of(people[actor]),
        }

    def test_a_member_cannot_invite(self, people):
        assert self.invite(people, "member", "5551230004").status_code == 403
        assert not InventoryInvite.objects.exists()

    @pytest.mark.parametrize(
        "phone_number, message",
        [
            ("555", "Enter a 10-digit US phone number."),
            ("5559999999", "No user has this phone number."),
        ],
    )
    def test_rejects_an_invalid_or_unknown_phone_number(self, people, phone_number, message):
        response = self.invite(people, "owner", phone_number)

        assert response.status_code == 400
        assert response.json() == {"phone_number": [message]}

    def test_inviting_a_member_or_someone_already_invited_conflicts(self, people):
        assert self.invite(people, "owner", people["member"].phone_number).status_code == 409
        assert self.invite(people, "owner", "5551230004").status_code == 201
        assert self.invite(people, "admin", "5551230004").status_code == 409

    @pytest.mark.parametrize("actor", ["admin", "owner"])
    def test_admins_and_owners_list_every_pending_invite(self, people, actor):
        self.invite(people, "owner", "5551230004")
        declined = make_user(5)
        InventoryInvite.objects.create(
            inventory=people["inventory"],
            invitee=declined,
            invited_by=people["admin"],
            status="declined",
        )

        response = client_for(people[actor]).get(inventory_url(people["inventory"], "invites/"))

        assert response.status_code == 200
        assert [i["invitee"] for i in response.json()] == [{"phone_number": "5551230004"}]

    def test_a_pending_invite_shows_the_invitee_only_by_phone_number(self, people):
        created = self.invite(people, "owner", "5551230004").json()
        listed = client_for(people["owner"]).get(inventory_url(people["inventory"], "invites/"))

        for body in [created, *listed.json()]:
            assert set(body["invitee"]) == {"phone_number"}
            assert "Stan" not in str(body)

    def test_a_member_cannot_list_invites(self, people):
        url = inventory_url(people["inventory"], "invites/")
        response = client_for(people["member"]).get(url)

        assert response.status_code == 403


@pytest.mark.django_db
class TestMyInvites:
    @pytest.fixture
    def invite(self, people):
        return InventoryInvite.objects.create(
            inventory=people["inventory"], invitee=people["stranger"], invited_by=people["admin"]
        )

    def answer(self, user, invite, action):
        return client_for(user).post(f"{INVITES_URL}{invite.id}/{action}/")

    def test_the_invitee_sees_the_inventory_name_and_who_invited_them(self, people, invite):
        InventoryInvite.objects.create(
            inventory=people["inventory"],
            invitee=people["stranger"],
            invited_by=people["owner"],
            status="revoked",
        )

        response = client_for(people["stranger"]).get(INVITES_URL)

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": invite.id,
                "inventory_name": "Climbing",
                "invited_by": name_of(people["admin"]),
            }
        ]
        assert client_for(people["owner"]).get(INVITES_URL).json() == []

    def test_seeing_an_invite_does_not_show_the_inventory(self, people, invite):
        response = client_for(people["stranger"]).get(inventory_url(people["inventory"]))

        assert response.status_code == 404

    def test_accepting_joins_as_member(self, people, invite):
        response = self.answer(people["stranger"], invite, "accept")

        assert response.status_code == 200
        assert response.json() == {
            "id": people["inventory"].id,
            "name": "Climbing",
            "role": "member",
        }

    def test_declining(self, people, invite):
        response = self.answer(people["stranger"], invite, "decline")

        assert response.status_code == 204
        invite.refresh_from_db()
        assert invite.status == "declined"

    @pytest.mark.parametrize("actor", ["admin", "owner"])
    def test_admins_and_owners_revoke(self, people, invite, actor):
        response = self.answer(people[actor], invite, "revoke")

        assert response.status_code == 204
        invite.refresh_from_db()
        assert invite.status == "revoked"

    def test_answering_twice_conflicts(self, people, invite):
        self.answer(people["stranger"], invite, "decline")

        response = self.answer(people["stranger"], invite, "accept")

        assert response.status_code == 409
        assert response.json() == {"detail": "This invite is no longer pending."}

    @pytest.mark.parametrize("action", ["accept", "decline", "revoke"])
    def test_a_plain_member_or_an_outsider_gets_not_found(self, people, invite, action):
        outsider = make_user(6)

        for user in [people["member"], outsider]:
            assert self.answer(user, invite, action).status_code == 404

    @pytest.mark.parametrize("action", ["accept", "decline", "revoke"])
    @pytest.mark.parametrize("status", ["declined", "revoked"])
    @pytest.mark.parametrize("viewer", ["member", "outsider"])
    def test_a_non_party_cannot_tell_a_finished_invite_from_an_unknown_one(
        self, people, invite, action, status, viewer
    ):
        invite.status = status
        invite.save()
        user = people["member"] if viewer == "member" else make_user(6)

        assert self.answer(user, invite, action).status_code == 404

    def test_the_invitee_cannot_revoke_and_an_admin_cannot_accept(self, people, invite):
        assert self.answer(people["stranger"], invite, "revoke").status_code == 403
        assert self.answer(people["admin"], invite, "accept").status_code == 403

    def test_an_unknown_invite_is_not_found(self, people):
        response = client_for(people["owner"]).post(f"{INVITES_URL}999999/accept/")

        assert response.status_code == 404


@pytest.mark.django_db
def test_unsafe_requests_need_the_csrf_token(people):
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(people["owner"])

    response = client.post(INVENTORIES_URL, {"name": "Camping"}, format="json")

    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]
