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
    path("invites/", views.my_invites, name="my-invites"),
    path("invites/<int:invite_id>/accept/", views.accept_invite, name="accept-invite"),
    path("invites/<int:invite_id>/decline/", views.decline_invite, name="decline-invite"),
    path("invites/<int:invite_id>/revoke/", views.revoke_invite, name="revoke-invite"),
]
