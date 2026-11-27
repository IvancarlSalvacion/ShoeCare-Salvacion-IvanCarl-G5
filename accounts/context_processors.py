from django.urls import reverse

from .models import User


def navigation(request):
    """Role-specific navigation. Every item opens a real page."""
    user = request.user
    if not user.is_authenticated:
        return {}

    match = request.resolver_match
    current = match.url_name if match else ""

    def real(label, url_name, *names):
        return {"label": label, "url": reverse(url_name), "active": current in (url_name, *names)}

    services = real("Services", "service_list", "service_create", "service_edit", "service_delete")
    requests_link = real("Requests", "request_list", "request_detail", "request_delete")
    if user.role == User.Role.CUSTOMER:
        items = [real("Dashboard", "customer_dashboard"), services,
                 real("New request", "request_create"),
                 real("My requests", "request_list", "request_detail", "request_edit", "request_delete")]
    elif user.role == User.Role.STAFF:
        items = [real("Dashboard", "staff_dashboard"), requests_link, services]
    else:
        items = [real("Dashboard", "admin_dashboard"), requests_link, services]
    items.append(real("Profile", "profile", "profile_edit"))
    return {"nav_items": items}