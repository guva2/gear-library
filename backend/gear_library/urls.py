from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("auth/csrf/", views.csrf, name="csrf"),
    path("auth/register/", views.register, name="register"),
    path("auth/login/", views.login_view, name="login"),
    path("auth/logout/", views.logout_view, name="logout"),
    path("auth/me/", views.me, name="me"),
    path("inventories/", views.inventory_list, name="inventory-list"),
    path("inventories/<int:inventory_id>/", views.inventory_detail, name="inventory-detail"),
    path("inventories/<int:inventory_id>/members/", views.member_list, name="member-list"),
    path(
        "inventories/<int:inventory_id>/members/<int:user_id>/",
        views.member_detail,
        name="member-detail",
    ),
    path(
        "inventories/<int:inventory_id>/invites/",
        views.inventory_invites,
        name="inventory-invites",
    ),
    path(
        "inventories/<int:inventory_id>/items/",
        views.inventory_items,
        name="inventory-items",
    ),
    path(
        "inventories/<int:inventory_id>/items/<int:item_id>/",
        views.inventory_item_detail,
        name="inventory-item-detail",
    ),
    path("invites/", views.my_invites, name="my-invites"),
    path("invites/<int:invite_id>/accept/", views.accept_invite, name="accept-invite"),
    path("invites/<int:invite_id>/decline/", views.decline_invite, name="decline-invite"),
    path("invites/<int:invite_id>/revoke/", views.revoke_invite, name="revoke-invite"),
    path("connections/", views.connection_list, name="connection-list"),
    path("connections/requests/", views.connection_requests, name="connection-requests"),
    path(
        "connections/<int:connection_id>/",
        views.connection_detail,
        name="connection-detail",
    ),
    path(
        "connections/<int:connection_id>/accept/",
        views.accept_connection,
        name="accept-connection",
    ),
    path(
        "connections/<int:connection_id>/decline/",
        views.decline_connection,
        name="decline-connection",
    ),
    path(
        "connections/<int:connection_id>/cancel/",
        views.cancel_connection,
        name="cancel-connection",
    ),
    path("items/", views.item_list, name="item-list"),
    path("items/<int:item_id>/", views.item_detail, name="item-detail"),
]
