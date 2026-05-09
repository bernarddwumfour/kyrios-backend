# apps/packages/urls.py
from django.urls import path
from . import views

urlpatterns = [

    path("",                   views.list_packages,   name="list_packages"),
    path("create/",            views.create_package,  name="create_package"),
    path("<str:id>/update/",   views.update_package,  name="update_package"),
    path("<str:id>/delete/",   views.delete_package,  name="delete_package"),

    path("subscriptions/subscribe/",    views.subscribe,              name="subscribe"),
    path("subscriptions/me/",           views.my_subscription,        name="my_subscription"),
    path("subscriptions/cancel/",       views.cancel_subscription,    name="cancel_subscription"),
    path("subscriptions/history/",      views.subscription_history,   name="subscription_history"),

    path("subscriptions/",                      views.admin_list_subscriptions,   name="admin_list_subscriptions"),
    path("subscriptions/<str:id>/update/",      views.admin_update_subscription,  name="admin_update_subscription"),
    path("<str:id>/",          views.package_detail,  name="package_detail"),
]