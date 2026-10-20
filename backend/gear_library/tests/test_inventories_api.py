import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from gear_library.models import Connection, Inventory, Membership, ordered_pair

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


def connect(user, other):
    first, second = ordered_pair(user, other)
    return Connection.objects.create(
        first_user_id=first, second_user_id=second, requested_by=user, status="accepted"
    )


def add_pending(inventory, user, invited_by):
    return Membership.objects.create(
        inventory=inventory, user=user, role="member", status="pending", invited_by=invited_by
    )


@pytest.fixture
def people():
    """An inventory with one user in each role, a user invited by the admin, and a
    stranger outside it."""
    names = ["Olive", "Adam", "Mia", "Pat", "Stan"]
    owner, admin, member, pending, stranger = (
        make_user(n, name) for n, name in enumerate(names, 1)
    )
    inventory = Inventory.objects.create(name="Climbing")
    for user, role in [(owner, "owner"), (admin, "admin"), (member, "member")]:
        Membership.objects.create(inventory=inventory, user=user, role=role, status="active")
    add_pending(inventory, pending, admin)
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
        Membership.objects.create(
            inventory=other, user=people["stranger"], role="owner", status="active"
        )
        add_pending(other, people["admin"], people["stranger"])

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
    @pytest.mark.parametrize("viewer", ["stranger", "pending"])
    def test_a_non_member_or_invited_user_gets_not_found(self, people, method, suffix, viewer):
        client = client_for(people[viewer])
        url = inventory_url(people["inventory"], suffix)

        response = getattr(client, method)(
            url, {"name": "x", "role": "member", "user_id": people["stranger"].id}, format="json"
        )

        assert response.status_code == 404
        assert Inventory.objects.get().name == "Climbing"
        assert Membership.objects.count() == 4

    def test_an_invited_user_cannot_leave(self, people):
        url = inventory_url(people["inventory"], f"members/{people['pending'].id}/")

        response = client_for(people["pending"]).delete(url)

        assert response.status_code == 404
        assert Membership.objects.get(user=people["pending"]).status == "pending"

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
        response = client_for(people["owner"]).delete(inventory_url(people["inventory"]))

        assert response.status_code == 204
        assert not Inventory.objects.exists()
        assert not Membership.objects.exists()


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

    @pytest.mark.parametrize("target", ["stranger", "pending"])
    def test_setting_the_role_of_a_non_member_is_not_found(self, people, target):
        response = client_for(people["owner"]).patch(
            self.member_url(people, people[target]), {"role": "admin"}, format="json"
        )

        assert response.status_code == 404

    def test_removing_an_invited_user_as_a_member_is_not_found(self, people):
        response = client_for(people["owner"]).delete(self.member_url(people, people["pending"]))

        assert response.status_code == 404
        assert Membership.objects.get(user=people["pending"]).status == "pending"

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
    @pytest.fixture(autouse=True)
    def connections(self, people):
        """The owner and the admin are connected to everyone else."""
        for actor in ("owner", "admin"):
            for person in ("member", "pending", "stranger"):
                connect(people[actor], people[person])

    def invite(self, people, actor, body):
        return client_for(people[actor]).post(
            inventory_url(people["inventory"], "invites/"), body, format="json"
        )

    @pytest.mark.parametrize("actor", ["admin", "owner"])
    def test_admins_and_owners_invite_a_connection(self, people, actor):
        response = self.invite(people, actor, {"user_id": people["stranger"].id})

        assert response.status_code == 201
        invite = Membership.objects.get(user=people["stranger"])
        assert (invite.status, invite.role) == ("pending", "member")
        assert response.json() == {
            "id": invite.id,
            "invitee": {"phone_number": "5551230005"},
            "invited_by": name_of(people[actor]),
        }

    def test_a_member_cannot_invite(self, people):
        response = self.invite(people, "member", {"user_id": people["stranger"].id})

        assert response.status_code == 403
        assert not Membership.objects.filter(user=people["stranger"]).exists()

    def test_access_is_checked_before_the_body(self, people):
        assert self.invite(people, "member", {"user_id": "x"}).status_code == 403
        assert self.invite(people, "stranger", {}).status_code == 404

    @pytest.mark.parametrize(
        "who", ["no such user", "not connected", "pending request", "the caller"]
    )
    def test_anyone_but_a_connection_gets_one_message(self, people, who):
        other = make_user(6)
        if who == "pending request":
            first, second = ordered_pair(people["owner"], other)
            Connection.objects.create(
                first_user_id=first, second_user_id=second, requested_by=other, status="pending"
            )
        user_id = {"no such user": 999999, "the caller": people["owner"].id}.get(who, other.id)

        response = self.invite(people, "owner", {"user_id": user_id})

        assert response.status_code == 400
        assert response.json() == {"user_id": ["You can invite only your connections."]}

    @pytest.mark.parametrize(
        "body, message",
        [
            ({}, "This field is required."),
            ({"user_id": "x"}, "A valid integer is required."),
            ({"phone_number": "5551230005"}, "This field is required."),
        ],
    )
    def test_rejects_a_missing_or_invalid_user_id(self, people, body, message):
        response = self.invite(people, "owner", body)

        assert response.status_code == 400
        assert response.json() == {"user_id": [message]}

    @pytest.mark.parametrize("user_id", [-1, 0, 2**63, 10**30])
    def test_an_id_out_of_range_gets_the_same_message(self, people, user_id):
        response = self.invite(people, "owner", {"user_id": user_id})

        assert response.status_code == 400
        assert response.json() == {"user_id": ["You can invite only your connections."]}

    @pytest.mark.parametrize("person", ["member", "pending"])
    def test_inviting_a_member_or_someone_already_invited_conflicts(self, people, person):
        response = self.invite(people, "owner", {"user_id": people[person].id})

        assert response.status_code == 409
        assert response.json() == {
            "detail": "This user is already a member or has a pending invite."
        }

    @pytest.mark.parametrize("actor", ["admin", "owner"])
    def test_admins_and_owners_list_only_the_pending_invites(self, people, actor):
        response = client_for(people[actor]).get(inventory_url(people["inventory"], "invites/"))

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": Membership.objects.get(user=people["pending"]).id,
                "invitee": {"phone_number": people["pending"].phone_number},
                "invited_by": name_of(people["admin"]),
            }
        ]

    def test_a_pending_invite_shows_the_invitee_only_by_phone_number(self, people):
        created = self.invite(people, "owner", {"user_id": people["stranger"].id}).json()
        listed = client_for(people["owner"]).get(inventory_url(people["inventory"], "invites/"))

        for body in [created, *listed.json()]:
            assert set(body["invitee"]) == {"phone_number"}
            assert "Stan" not in str(body) and "Pat" not in str(body)

    def test_a_member_cannot_list_invites(self, people):
        url = inventory_url(people["inventory"], "invites/")
        response = client_for(people["member"]).get(url)

        assert response.status_code == 403


@pytest.mark.django_db
class TestMyInvites:
    @pytest.fixture
    def invite(self, people):
        return Membership.objects.get(user=people["pending"])

    def answer(self, user, invite, action):
        return client_for(user).post(f"{INVITES_URL}{invite.id}/{action}/")

    def test_the_invitee_sees_the_inventory_name_and_who_invited_them(self, people, invite):
        response = client_for(people["pending"]).get(INVITES_URL)

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": invite.id,
                "inventory_name": "Climbing",
                "invited_by": name_of(people["admin"]),
            }
        ]
        assert client_for(people["owner"]).get(INVITES_URL).json() == []

    def test_an_invitee_sees_neither_the_inventory_nor_it_in_their_list(self, people, invite):
        client = client_for(people["pending"])

        assert client.get(inventory_url(people["inventory"])).status_code == 404
        assert client.get(INVENTORIES_URL).json() == []

    def test_accepting_joins_as_member(self, people, invite):
        response = self.answer(people["pending"], invite, "accept")

        assert response.status_code == 200
        assert response.json() == {
            "id": people["inventory"].id,
            "name": "Climbing",
            "role": "member",
        }
        members = client_for(people["owner"]).get(inventory_url(people["inventory"], "members/"))
        assert full(people["pending"], "member") in members.json()

    def test_accepting_twice_returns_the_inventory_again(self, people, invite):
        first = self.answer(people["pending"], invite, "accept")

        again = self.answer(people["pending"], invite, "accept")

        assert again.status_code == 200
        assert again.json() == first.json()

    def test_declining_deletes_the_invite(self, people, invite):
        response = self.answer(people["pending"], invite, "decline")

        assert response.status_code == 204
        assert not Membership.objects.filter(pk=invite.pk).exists()

    @pytest.mark.parametrize("actor", ["admin", "owner"])
    def test_admins_and_owners_revoke(self, people, invite, actor):
        response = self.answer(people[actor], invite, "revoke")

        assert response.status_code == 204
        assert not Membership.objects.filter(pk=invite.pk).exists()

    @pytest.mark.parametrize("action, by", [("decline", "pending"), ("revoke", "owner")])
    def test_declining_or_revoking_after_an_accept_conflicts(self, people, invite, action, by):
        self.answer(people["pending"], invite, "accept")

        response = self.answer(people[by], invite, action)

        assert response.status_code == 409
        assert response.json() == {"detail": "This is not a pending invite."}

    def test_answering_a_declined_invite_is_not_found(self, people, invite):
        self.answer(people["pending"], invite, "decline")

        response = self.answer(people["pending"], invite, "accept")

        assert response.status_code == 404
        assert response.json() == {"detail": "Invite not found."}

    @pytest.mark.parametrize("action", ["accept", "decline", "revoke"])
    @pytest.mark.parametrize("state", ["pending", "active", "gone"])
    def test_a_non_party_gets_not_found_whatever_the_state(self, people, invite, action, state):
        if state == "active":
            self.answer(people["pending"], invite, "accept")
        elif state == "gone":
            self.answer(people["pending"], invite, "decline")

        other_invitee = make_user(6)
        add_pending(people["inventory"], other_invitee, people["owner"])
        owner_elsewhere = make_user(7)
        elsewhere = Inventory.objects.create(name="Camping")
        Membership.objects.create(
            inventory=elsewhere, user=owner_elsewhere, role="owner", status="active"
        )

        for user in [people["member"], people["stranger"], other_invitee, owner_elsewhere]:
            response = self.answer(user, invite, action)
            assert (response.status_code, response.json()) == (
                404,
                {"detail": "Invite not found."},
            )

    @pytest.mark.parametrize(
        "who, action", [("pending", "revoke"), ("admin", "accept"), ("admin", "decline")]
    )
    def test_the_invitee_cannot_revoke_and_an_admin_cannot_answer(
        self, people, invite, who, action
    ):
        response = self.answer(people[who], invite, action)

        assert (response.status_code, response.json()) == (
            403,
            {"detail": "You cannot do this with this invite."},
        )
        assert Membership.objects.get(pk=invite.pk).status == "pending"

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
