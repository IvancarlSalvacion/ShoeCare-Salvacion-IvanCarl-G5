from django.template.defaultfilters import slugify
from django.urls import reverse

from .models import User


def navigation(request):
    """Role-specific navigation. Features not built yet point to a 'Coming soon' page."""
    user = request.user
    if not user.is_authenticated:
        return {}

    match = request.resolver_match
    current = match.url_name if match else ""
    current_feature = match.kwargs.get("feature") if match else None

    def real(label, url_name, *names):
        return {"label": label, "url": reverse(url_name), "active": current in (url_name, *names)}

    def soon(label):
        slug = slugify(label)
        return {"label": label, "url": reverse("coming_soon", args=[slug]),
                "active": current == "coming_soon" and current_feature == slug}

    services = real("Services", "service_list", "service_create", "service_edit", "service_delete")
    if user.role == User.Role.CUSTOMER:
        items = [real("Dashboard", "customer_dashboard"), services,
                 real("New request", "request_create"),
                 real("My requests", "request_list", "request_detail", "request_edit", "request_delete")]
    elif user.role == User.Role.STAFF:
        items = [real("Dashboard", "staff_dashboard"),
                 real("Requests", "request_list", "request_detail", "request_delete"), services]
    else:
        items = [real("Dashboard", "admin_dashboard"),
                 real("Requests", "request_list", "request_detail", "request_delete"), services, soon("Reports")]
    items.append(real("Profile", "profile", "profile_edit"))
    return {"nav_items": items}