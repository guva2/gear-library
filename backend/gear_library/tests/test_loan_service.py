import threading

import pytest
from django.db import connection, transaction
from rest_framework.exceptions import NotFound, PermissionDenied

from gear_library import inventories, items, loans
from gear_library.errors import Conflict
from gear_library.models import InventoryItem, Item, Membership

from .test_inventory_service import as_, hold_after, run_in_thread, wait_for_a_blocked_lock
from .test_item_service import join, list_directly, make_user


@pytest.fixture
def people():
    """An inventory owned by Olive, where the admin Adam lists his rope and Mia and Max are
    members."""
    olive = make_user(1, "Olive")
    with transaction.atomic():
        inventory = inventories.create_inventory(olive, "Climbing").inventory
    adam = join(inventory, "admin", 2)
    mia = join(inventory, "member", 3)
    max_ = join(inventory, "member", 4)
    rope = items.create_item(adam, {"name": "Rope"})
    list_directly(inventory, rope)
    return {
        "inventory": inventory,
        "olive": olive,
        "adam": adam,
        "mia": mia,
        "max": max_,
        "rope": rope,
    }


def loan_of(item):
    item.refresh_from_db()
    return (item.loan_status, item.borrower_id, item.loan_inventory_id)


def available():
    return ("available", None, None)


def set_loan(item, status, borrower, inventory):
    Item.objects.filter(pk=item.pk).update(
        loan_status=status, borrower=borrower, loan_inventory=inventory
    )


def second_inventory(people):
    """Another inventory, owned by Adam, where the rope is listed too and Mia is a member."""
    other = inventories.create_inventory(people["adam"], "Camping").inventory
    Membership.objects.create(inventory=other, user=people["mia"], role="member", status="active")
    list_directly(other, people["rope"])
    return other


def listing_of(inventory, item):
    return InventoryItem.objects.select_related("item").get(inventory=inventory, item=item)


def request(user, inventory, item):
    loans.request_item(user, listing_of(inventory, item))


@pytest.mark.django_db
class TestRequest:
    def test_a_member_requests_a_listed_item(self, people):
        request(people["mia"], people["inventory"], people["rope"])

        assert loan_of(people["rope"]) == ("requested", people["mia"].id, people["inventory"].id)

    def test_the_owner_cannot_request_their_own_item(self, people):
        with pytest.raises(PermissionDenied):
            request(people["adam"], people["inventory"], people["rope"])
        assert loan_of(people["rope"]) == available()

    def test_a_requested_item_cannot_be_requested_again_through_any_inventory(self, people):
        other = second_inventory(people)
        request(people["max"], people["inventory"], people["rope"])

        with pytest.raises(Conflict):
            request(people["mia"], other, people["rope"])
        assert loan_of(people["rope"]) == ("requested", people["max"].id, people["inventory"].id)

    def test_an_item_on_loan_cannot_be_requested(self, people):
        set_loan(people["rope"], "on_loan", people["max"], None)

        with pytest.raises(Conflict):
            request(people["mia"], people["inventory"], people["rope"])


@pytest.mark.django_db
class TestApproveAndDecline:
    @pytest.fixture
    def requested(self, people):
        request(people["mia"], people["inventory"], people["rope"])
        return people

    def approve(self, user, people, borrower=None):
        borrower = borrower or people["mia"]
        loans.approve(user, listing_of(people["inventory"], people["rope"]), borrower.id)

    def decline(self, user, people, borrower=None):
        borrower = borrower or people["mia"]
        loans.decline(user, listing_of(people["inventory"], people["rope"]), borrower.id)

    @pytest.mark.parametrize("who", ["olive", "adam"])
    def test_admins_and_owners_approve(self, requested, who):
        self.approve(requested[who], requested)

        assert loan_of(requested["rope"]) == (
            "on_loan",
            requested["mia"].id,
            requested["inventory"].id,
        )

    @pytest.mark.parametrize("who", ["olive", "adam"])
    def test_admins_and_owners_decline(self, requested, who):
        self.decline(requested[who], requested)

        assert loan_of(requested["rope"]) == available()

    @pytest.mark.parametrize("action", ["approve", "decline"])
    def test_an_owner_cannot_approve_or_decline_their_own_request(self, people, action):
        request(people["olive"], people["inventory"], people["rope"])

        with pytest.raises(PermissionDenied):
            getattr(self, action)(people["olive"], people, people["olive"])
        assert loan_of(people["rope"]) == ("requested", people["olive"].id, people["inventory"].id)

    @pytest.mark.parametrize("action", ["approve", "decline"])
    def test_a_request_by_someone_else_than_the_caller_saw_conflicts(self, requested, action):
        """Mia cancelled and Max requested after the admin loaded the page."""
        set_loan(requested["rope"], "requested", requested["max"], requested["inventory"])

        with pytest.raises(Conflict):
            getattr(self, action)(requested["olive"], requested)
        assert loan_of(requested["rope"])[:2] == ("requested", requested["max"].id)

    @pytest.mark.parametrize("action", ["approve", "decline"])
    def test_a_request_through_another_inventory_conflicts(self, people, action):
        other = second_inventory(people)
        request(people["mia"], other, people["rope"])

        with pytest.raises(Conflict):
            getattr(self, action)(people["olive"], people)
        assert loan_of(people["rope"]) == ("requested", people["mia"].id, other.id)

    def test_an_item_on_loan_cannot_be_approved_again(self, requested):
        self.approve(requested["olive"], requested)

        with pytest.raises(Conflict):
            self.approve(requested["olive"], requested)


@pytest.mark.django_db
class TestMarkReturnedThroughTheInventory:
    @pytest.fixture
    def on_loan(self, people):
        set_loan(people["rope"], "on_loan", people["mia"], people["inventory"])
        return people

    def mark_returned(self, user, people, borrower=None):
        borrower = borrower or people["mia"]
        loans.mark_returned(user, listing_of(people["inventory"], people["rope"]), borrower.id)

    @pytest.mark.parametrize("who", ["olive", "adam"])
    def test_admins_and_owners_mark_it_returned(self, on_loan, who):
        self.mark_returned(on_loan[who], on_loan)

        assert loan_of(on_loan["rope"]) == available()

    def test_the_borrower_cannot_mark_their_own_loan_returned(self, people):
        set_loan(people["rope"], "on_loan", people["olive"], people["inventory"])

        with pytest.raises(PermissionDenied):
            self.mark_returned(people["olive"], people, people["olive"])
        assert loan_of(people["rope"])[0] == "on_loan"

    def test_a_pending_request_cannot_be_marked_returned(self, people):
        request(people["mia"], people["inventory"], people["rope"])

        with pytest.raises(Conflict):
            self.mark_returned(people["olive"], people)
        assert loan_of(people["rope"])[0] == "requested"

    def test_a_loan_through_another_inventory_conflicts(self, people):
        other = second_inventory(people)
        set_loan(people["rope"], "on_loan", people["mia"], other)

        with pytest.raises(Conflict):
            self.mark_returned(people["olive"], people)

    def test_a_loan_to_someone_else_than_the_caller_saw_conflicts(self, on_loan):
        with pytest.raises(Conflict):
            self.mark_returned(on_loan["olive"], on_loan, on_loan["max"])
        assert loan_of(on_loan["rope"])[0] == "on_loan"


@pytest.mark.django_db
class TestCancel:
    def test_the_requester_cancels(self, people):
        request(people["mia"], people["inventory"], people["rope"])

        loans.cancel(people["mia"], people["rope"].id)

        assert loan_of(people["rope"]) == available()

    @pytest.mark.parametrize("who", ["olive", "adam", "max"])
    def test_anyone_else_is_not_found(self, people, who):
        request(people["mia"], people["inventory"], people["rope"])

        with pytest.raises(NotFound):
            loans.cancel(people[who], people["rope"].id)
        assert loan_of(people["rope"])[0] == "requested"

    def test_an_approved_request_cannot_be_cancelled(self, people):
        set_loan(people["rope"], "on_loan", people["mia"], people["inventory"])

        with pytest.raises(Conflict):
            loans.cancel(people["mia"], people["rope"].id)
        assert loan_of(people["rope"])[0] == "on_loan"


@pytest.mark.django_db
class TestOwnerMarksReturned:
    def test_the_owner_marks_a_loan_returned_after_its_listing_and_inventory_are_gone(
        self, people
    ):
        set_loan(people["rope"], "on_loan", people["mia"], people["inventory"])
        owner = as_(people["olive"], people["inventory"])
        inventories.delete_inventory(owner)

        loans.owner_mark_returned(people["adam"], people["rope"].id, people["mia"].id)

        assert loan_of(people["rope"]) == available()

    @pytest.mark.parametrize("who", ["mia", "olive"])
    def test_anyone_but_the_owner_is_not_found(self, people, who):
        set_loan(people["rope"], "on_loan", people["mia"], people["inventory"])

        with pytest.raises(NotFound):
            loans.owner_mark_returned(people[who], people["rope"].id, people["mia"].id)
        assert loan_of(people["rope"])[0] == "on_loan"

    @pytest.mark.parametrize("status", ["requested", "on_loan"])
    def test_a_loan_the_owner_did_not_see_conflicts(self, people, status):
        set_loan(people["rope"], status, people["max"], people["inventory"])

        with pytest.raises(Conflict):
            loans.owner_mark_returned(people["adam"], people["rope"].id, people["mia"].id)
        assert loan_of(people["rope"])[:2] == (status, people["max"].id)

    def test_a_pending_request_cannot_be_marked_returned(self, people):
        request(people["mia"], people["inventory"], people["rope"])

        with pytest.raises(Conflict):
            loans.owner_mark_returned(people["adam"], people["rope"].id, people["mia"].id)


@pytest.mark.django_db
class TestAutomaticCancels:
    """A pending request ends when the item leaves its loan inventory, when the requester
    leaves it, and when that inventory is deleted. Loans stay."""

    @pytest.fixture
    def setup(self, people):
        """Mia requests the rope through Climbing. Adam's tent is lent to Max through
        Climbing, and his lamp is requested by Mia through Camping."""
        other = second_inventory(people)
        tent = items.create_item(people["adam"], {"name": "Tent"})
        lamp = items.create_item(people["adam"], {"name": "Lamp"})
        list_directly(people["inventory"], tent)
        list_directly(other, lamp)
        request(people["mia"], people["inventory"], people["rope"])
        set_loan(tent, "on_loan", people["max"], people["inventory"])
        request(people["mia"], other, lamp)
        return {**people, "other": other, "tent": tent, "lamp": lamp}

    def assert_only_the_rope_request_ended(self, setup):
        assert loan_of(setup["rope"]) == available()
        assert loan_of(setup["tent"]) == ("on_loan", setup["max"].id, setup["inventory"].id)
        assert loan_of(setup["lamp"]) == ("requested", setup["mia"].id, setup["other"].id)

    def test_removing_the_listing_from_the_loan_inventory(self, setup):
        items.remove_listing(listing_of(setup["inventory"], setup["rope"]))
        items.remove_listing(listing_of(setup["inventory"], setup["tent"]))

        self.assert_only_the_rope_request_ended(setup)

    def test_removing_the_listing_from_another_inventory_keeps_the_request(self, setup):
        items.remove_listing(listing_of(setup["other"], setup["rope"]))

        assert loan_of(setup["rope"])[0] == "requested"

    def test_the_item_owner_leaving(self, setup):
        inventories.remove_member(as_(setup["adam"], setup["inventory"]), setup["adam"].id)

        self.assert_only_the_rope_request_ended(setup)

    def test_the_item_owner_being_removed(self, setup):
        inventories.remove_member(as_(setup["olive"], setup["inventory"]), setup["adam"].id)

        self.assert_only_the_rope_request_ended(setup)

    def test_the_item_owner_taking_the_member_role(self, setup):
        owner = as_(setup["olive"], setup["inventory"])
        inventories.set_role(owner, setup["adam"].id, "member")

        self.assert_only_the_rope_request_ended(setup)

    def test_the_requester_leaving(self, setup):
        Item.objects.filter(pk=setup["tent"].pk).update(borrower=setup["mia"])

        inventories.remove_member(as_(setup["mia"], setup["inventory"]), setup["mia"].id)

        assert loan_of(setup["rope"]) == available()
        assert loan_of(setup["tent"]) == ("on_loan", setup["mia"].id, setup["inventory"].id)
        assert loan_of(setup["lamp"]) == ("requested", setup["mia"].id, setup["other"].id)

    def test_the_requester_being_removed(self, setup):
        inventories.remove_member(as_(setup["olive"], setup["inventory"]), setup["mia"].id)

        assert loan_of(setup["rope"]) == available()
        assert loan_of(setup["lamp"]) == ("requested", setup["mia"].id, setup["other"].id)

    def test_the_requester_taking_another_role_keeps_the_request(self, setup):
        owner = as_(setup["olive"], setup["inventory"])
        inventories.set_role(owner, setup["mia"].id, "admin")
        inventories.set_role(owner, setup["mia"].id, "member")

        assert loan_of(setup["rope"])[0] == "requested"

    def test_deleting_the_loan_inventory_ends_its_requests_and_keeps_its_loans(self, setup):
        owner = as_(setup["olive"], setup["inventory"])

        inventories.delete_inventory(owner)

        assert loan_of(setup["rope"]) == available()
        assert loan_of(setup["tent"]) == ("on_loan", setup["max"].id, None)
        assert loan_of(setup["lamp"]) == ("requested", setup["mia"].id, setup["other"].id)


@pytest.mark.django_db
class TestDeletingAnItem:
    def test_a_requested_item_is_deleted(self, people):
        request(people["mia"], people["inventory"], people["rope"])

        items.delete_item(people["adam"], people["rope"].id)

        assert not Item.objects.exists()

    def test_an_item_on_loan_cannot_be_deleted(self, people):
        set_loan(people["rope"], "on_loan", people["mia"], None)

        with pytest.raises(Conflict):
            items.delete_item(people["adam"], people["rope"].id)
        assert people["rope"].listings.count() == 1


UPDATE_ITEM = 'UPDATE "gear_library_item" '


@pytest.mark.django_db(transaction=True)
class TestCommittedRaces:
    def race(self, first, second, held, release):
        outcomes = {}
        threads = [run_in_thread("first", first, outcomes)]
        assert held.wait(10)
        threads.append(run_in_thread("second", second, outcomes))
        try:
            wait_for_a_blocked_lock()
        finally:
            release.set()
            for thread in threads:
                thread.join(10)
        return outcomes

    def test_a_cancel_waits_for_an_approval_and_conflicts(self, people):
        request(people["mia"], people["inventory"], people["rope"])
        held, release = threading.Event(), threading.Event()

        def approve():
            with transaction.atomic():
                with connection.execute_wrapper(hold_after(UPDATE_ITEM, held, release)):
                    listing = listing_of(people["inventory"], people["rope"])
                    loans.approve(people["olive"], listing, people["mia"].id)

        outcomes = self.race(
            approve, lambda: loans.cancel(people["mia"], people["rope"].id), held, release
        )

        assert outcomes["first"] == "ok"
        assert isinstance(outcomes["second"], Conflict)
        assert loan_of(people["rope"])[0] == "on_loan"
