from django.urls import path

from . import views

urlpatterns = [
    path("services/", views.service_list, name="service_list"),
    path("services/new/", views.service_create, name="service_create"),
    path("services/<int:pk>/edit/", views.service_edit, name="service_edit"),
    path("services/<int:pk>/toggle/", views.service_toggle, name="service_toggle"),
    path("services/<int:pk>/delete/", views.service_delete, name="service_delete"),
    path("requests/", views.request_list, name="request_list"),
    path("requests/new/", views.request_create, name="request_create"),
    path("requests/<int:pk>/", views.request_detail, name="request_detail"),
    path("requests/<int:pk>/edit/", views.request_edit, name="request_edit"),
    path("requests/<int:pk>/cancel/", views.request_cancel, name="request_cancel"),
    path("requests/<int:pk>/delete/", views.request_delete, name="request_delete"),
    path("requests/<int:pk>/advance/", views.request_advance, name="request_advance"),
    path("requests/<int:pk>/pickup/", views.request_pickup, name="request_pickup"),
]