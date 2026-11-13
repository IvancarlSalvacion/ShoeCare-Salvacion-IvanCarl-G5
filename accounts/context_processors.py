from django.template.defaultfilters import slugify
from django.urls import reverse

from .models import User

ICONS = {
    "Services": "droplet",
    "New request": "plus",
    "My requests": "list",
    "Requests": "list",
    "Reports": "chart",
}


def navigation(request):
    """Role-specific navigation. Unbuilt features point to a 'Coming soon' page."""
    user = request.user
    if not user.is_authenticated:
        return {}

    match = request.resolver_match
    current = match.url_name if match else ""
    current_feature = match.kwargs.get("feature") if match else None

    items = [{"label": "Dashboard", "icon": "home", "url": reverse(user.dashboard_url_name),
              "active": current == user.dashboard_url_name}]

    extras = {
        User.Role.CUSTOMER: ["Services", "New request", "My requests"],
        User.Role.STAFF: ["Requests", "Services"],
        User.Role.ADMIN: ["Requests", "Services", "Reports"],
    }[user.role]
    for label in extras:
        slug = slugify(label)
        items.append({"label": label, "icon": ICONS[label], "url": reverse("coming_soon", args=[slug]),
                      "active": current == "coming_soon" and current_feature == slug})

    items.append({"label": "Profile", "icon": "user", "url": reverse("profile"),
                  "active": current in ("profile", "profile_edit")})
    return {"nav_items": items}