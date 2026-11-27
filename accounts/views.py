from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db.models import Count, Sum
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from cleaning.models import Payment, ServiceRequest

from .decorators import role_required
from .forms import LoginForm, ProfileForm, RegistrationForm
from .models import User

Status = ServiceRequest.Status
CLOSED = [Status.COMPLETED, Status.CANCELLED]


def home(request):
    if request.user.is_authenticated:
        return redirect(request.user.dashboard_url_name)
    return redirect("login")


def register(request):
    if request.user.is_authenticated:
        return redirect(request.user.dashboard_url_name)

    form = RegistrationForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "Account created. Log in with your email and password.")
            return redirect("login")
        messages.error(request, "We couldn't create your account. Fix the highlighted fields and try again.")
    return render(request, "accounts/register.html", {"form": form})


class ShoeCareLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Welcome back, {form.get_user().get_short_name()}.")
        return response


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, "You've been logged out.")
    return redirect("login")


@login_required
def dashboard(request):
    """Send each user to the dashboard that matches their role."""
    return redirect(request.user.dashboard_url_name)


@role_required(User.Role.CUSTOMER)
def customer_dashboard(request):
    mine = ServiceRequest.objects.filter(user=request.user)
    return render(request, "dashboards/customer.html", {
        "active_count": mine.exclude(status__in=CLOSED).count(),
        "completed_count": mine.filter(status=Status.COMPLETED).count(),
        "recent_requests": mine.prefetch_related("items")[:5],
    })


@role_required(User.Role.STAFF)
def staff_dashboard(request):
    counts = {row["status"]: row["n"] for row in ServiceRequest.objects.values("status").annotate(n=Count("pk"))}
    return render(request, "dashboards/staff.html", {
        "pending_count": counts.get(Status.PENDING, 0),
        "received_count": counts.get(Status.RECEIVED, 0),
        "cleaning_count": counts.get(Status.CLEANING, 0),
        "ready_count": counts.get(Status.READY, 0),
        "queue": ServiceRequest.objects.exclude(status__in=CLOSED).select_related("user")
                 .prefetch_related("items").order_by("request_date")[:8],
    })


@role_required(User.Role.ADMIN)
def admin_dashboard(request):
    counts = {row["role"]: row["n"] for row in User.objects.values("role").annotate(n=Count("pk"))}
    revenue = Payment.objects.filter(payment_status=Payment.PayStatus.PAID).aggregate(t=Sum("amount_paid"))["t"] or 0
    context = {
        "customer_count": counts.get(User.Role.CUSTOMER, 0),
        "staff_count": counts.get(User.Role.STAFF, 0),
        "admin_count": counts.get(User.Role.ADMIN, 0),
        "open_count": ServiceRequest.objects.exclude(status__in=CLOSED).count(),
        "completed_count": ServiceRequest.objects.filter(status=Status.COMPLETED).count(),
        "revenue": revenue,
        "recent_requests": ServiceRequest.objects.select_related("user").prefetch_related("items")[:5],
        "recent_users": User.objects.order_by("-created_at")[:5],
    }
    return render(request, "dashboards/admin.html", context)


# Profile views never take a user id: they always act on request.user,
# so nobody can view or edit someone else's profile.
@login_required
def profile(request):
    return render(request, "accounts/profile.html")


@login_required
def profile_edit(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("profile")
        messages.error(request, "We couldn't save your changes. Fix the highlighted fields and try again.")
    return render(request, "accounts/profile_edit.html", {"form": form})


@login_required
def csrf_failure(request, reason=""):
    """Shown when a form's CSRF token is missing or expired."""
    return render(request, "403.html", {"csrf": True}, status=403)