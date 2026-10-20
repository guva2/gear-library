from django.urls import path
from rest_framework.routers import SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter

from . import views

router = SimpleRouter(use_regex_path=False)
router.register("auth", views.AuthViewSet, basename="auth")
# Registered before the list views on the same prefix: the nested routes take their
# inventory lookup from the first viewset registered there.
router.register("inventories", views.InventoryViewSet, basename="inventory")
router.register("inventories", views.InventoryListViewSet, basename="inventories")
router.register("invites", views.InviteViewSet, basename="invite")
router.register("connections", views.ConnectionViewSet, basename="connection")
router.register("items", views.ItemViewSet, basename="item")
router.register("borrowing", views.BorrowingViewSet, basename="borrowing")

inventory_router = NestedSimpleRouter(
    router, "inventories", lookup="inventory", use_regex_path=False
)
inventory_router.register("members", views.MemberViewSet, basename="member")
inventory_router.register("invites", views.InventoryInviteViewSet, basename="inventory-invite")
inventory_router.register("items", views.ListingViewSet, basename="listing")

urlpatterns = [
    path("health/", views.health, name="health"),
    *router.urls,
    *inventory_router.urls,
]
