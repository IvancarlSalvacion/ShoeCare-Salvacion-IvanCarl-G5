from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("register/", views.register, name="register"),
    path("login/", views.ShoeCareLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/customer/", views.customer_dashboard, name="customer_dashboard"),
    path("dashboard/staff/", views.staff_dashboard, name="staff_dashboard"),
    path("dashboard/admin/", views.admin_dashboard, name="admin_dashboard"),
    path("profile/", views.profile, name="profile"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("coming-soon/<slug:feature>/", views.coming_soon, name="coming_soon"),
]
