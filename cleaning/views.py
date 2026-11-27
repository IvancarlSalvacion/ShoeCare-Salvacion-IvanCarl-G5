from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.db import IntegrityError, transaction
from accounts.decorators import role_required
from accounts.models import User

from .forms import (CreateItemFormSet, EditItemFormSet, PickupForm, RequestFilterForm, ServiceForm)
from .models import STATUS_FLOW, Payment, Service, ServiceRequest

Status = ServiceRequest.Status
MANAGERS = (User.Role.STAFF, User.Role.ADMIN)


def _is_manager(user):
    return user.role in MANAGERS


def _get_request(user, pk):
    """Customers can only reach their own requests (others give a 404); staff/admin can reach all."""
    qs = ServiceRequest.objects.select_related("user", "payment").prefetch_related("items__service")
    if user.role == User.Role.CUSTOMER:
        qs = qs.filter(user=user)
    return get_object_or_404(qs, pk=pk)


# =========================== Services (catalog + admin CRUD) ===========================
@login_required
def service_list(request):
    is_admin = request.user.role == User.Role.ADMIN
    show_all = is_admin and request.GET.get("show") == "all"
    services = Service.objects.all()
    if not show_all:
        services = services.filter(is_active=True)
    q = request.GET.get("q", "").strip()
    if q:
        services = services.filter(Q(service_name__icontains=q) | Q(description__icontains=q))
    return render(request, "cleaning/service_list.html",
                  {"services": services, "q": q, "show_all": show_all, "is_admin": is_admin})


def _save_service(form):
    """Save inside a transaction; a duplicate name that slips past validation becomes a form error, not a 500."""
    try:
        with transaction.atomic():
            form.save()
        return True
    except IntegrityError:
        form.add_error("service_name", "A service with this name already exists.")
        return False


@role_required(User.Role.ADMIN)
def service_create(request):
    form = ServiceForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid() and _save_service(form):
            messages.success(request, f"Service “{form.instance.service_name}” added.")
            return redirect("service_list")
        messages.error(request, "We couldn't save the service. Fix the highlighted fields.")
    return render(request, "cleaning/service_form.html", {"form": form, "title": "Add service"})


@role_required(User.Role.ADMIN)
def service_edit(request, pk):
    service = get_object_or_404(Service, pk=pk)
    form = ServiceForm(request.POST or None, instance=service)
    if request.method == "POST":
        if form.is_valid() and _save_service(form):
            messages.success(request, "Service updated.")
            return redirect("service_list")
        messages.error(request, "We couldn't save the service. Fix the highlighted fields.")
    return render(request, "cleaning/service_form.html", {"form": form, "title": "Edit service"})


@role_required(User.Role.ADMIN)
@require_POST
def service_toggle(request, pk):
    service = get_object_or_404(Service, pk=pk)
    service.is_active = not service.is_active
    service.save(update_fields=["is_active"])
    messages.success(request, f"“{service.service_name}” is now {'active' if service.is_active else 'hidden from the catalog'}.")
    return redirect("service_list")


@role_required(User.Role.ADMIN)
def service_delete(request, pk):
    service = get_object_or_404(Service, pk=pk)
    if request.method == "POST":
        try:
            service.delete()
            messages.success(request, "Service deleted.")
        except ProtectedError:  # BR-08
            messages.error(request, "This service is used by existing requests and can't be deleted. Hide it instead.")
        return redirect("service_list")
    return render(request, "cleaning/confirm_delete.html", {
        "heading": "Delete this service?", "object_label": service.service_name,
        "warning": "This can't be undone. Services used by any request can't be deleted; hide them instead.",
        "back_url": "service_list", "back_args": []})


# =========================== Requests ===========================
@login_required
def request_list(request):
    user = request.user
    qs = ServiceRequest.objects.select_related("user").prefetch_related("items")
    if user.role == User.Role.CUSTOMER:
        qs = qs.filter(user=user)

    form = RequestFilterForm(request.GET or None)
    if form.is_valid():
        q, status, day = form.cleaned_data["q"].strip(), form.cleaned_data["status"], form.cleaned_data["date"]
        if q:
            cond = Q(user__full_name__icontains=q) | Q(user__email__icontains=q)
            if q.lstrip("#").isdigit():
                cond |= Q(pk=int(q.lstrip("#")))
            qs = qs.filter(cond)
        if status:
            qs = qs.filter(status=status)
        if day:
            qs = qs.filter(request_date__date=day)

    page = Paginator(qs, 10).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "cleaning/request_list.html", {
        "form": form, "page": page, "query": params.urlencode(), "is_manager": _is_manager(user)})


@role_required(User.Role.CUSTOMER)
def request_create(request):
    if not Service.objects.filter(is_active=True).exists():
        messages.error(request, "No services are available yet. Please check back soon.")
        return redirect("service_list")

    sr = ServiceRequest(user=request.user)
    initial = []
    wanted = request.GET.get("service")
    if wanted and wanted.isdigit() and Service.objects.filter(pk=wanted, is_active=True).exists():
        initial = [{"service": int(wanted)}]
    formset = CreateItemFormSet(request.POST or None, request.FILES or None, instance=sr, prefix="items", initial=initial)

    if request.method == "POST":
        if formset.is_valid():
            with transaction.atomic():
                sr.save()
                _apply_prices(formset)
                formset.save()
                sr.recalc_total()
                sr.log(request.user, "", Status.PENDING)
            messages.success(request, f"Request #{sr.request_id} submitted. We'll update its status as your shoes move along.")
            return redirect("request_detail", pk=sr.pk)
        messages.error(request, "We couldn't submit your request. Fix the highlighted fields.")
    return render(request, "cleaning/request_form.html", {"formset": formset, "title": "New cleaning request", "editing": False})


@role_required(User.Role.CUSTOMER)
def request_edit(request, pk):
    sr = _get_request(request.user, pk)
    if not sr.is_pending:
        messages.error(request, "You can only change a request while it is still Pending.")
        return redirect("request_detail", pk=pk)

    formset = EditItemFormSet(request.POST or None, request.FILES or None, instance=sr, prefix="items")
    if request.method == "POST":
        if formset.is_valid():
            with transaction.atomic():
                _apply_prices(formset)
                formset.save()
                sr.recalc_total()
            messages.success(request, "Request updated.")
            return redirect("request_detail", pk=pk)
        messages.error(request, "We couldn't save your changes. Fix the highlighted fields.")
    return render(request, "cleaning/request_form.html", {"formset": formset, "title": f"Edit request #{sr.pk}", "editing": True, "sr": sr})


def _apply_prices(formset):
    """BR-06: store the service price at submission. Existing items keep their price unless the service changes."""
    for form in formset.forms:
        if not form.has_changed() or form.cleaned_data.get("DELETE"):
            continue
        item = form.instance
        if item.pk is None or "service" in form.changed_data:
            item.unit_price = item.service.base_price


def _steps(sr):
    if sr.status not in STATUS_FLOW:
        return []
    labels = dict(Status.choices)
    idx = STATUS_FLOW.index(sr.status)
    return [{"label": labels[s], "state": "done" if i < idx else "current" if i == idx else "todo"}
            for i, s in enumerate(STATUS_FLOW)]


@login_required
def request_detail(request, pk):
    sr = _get_request(request.user, pk)
    user = request.user
    manager = _is_manager(user)
    owner = sr.user_id == user.pk
    return render(request, "cleaning/request_detail.html", {
        "sr": sr, "items": sr.items.all(), "logs": sr.logs.select_related("updated_by"),
        "payment": getattr(sr, "payment", None), "steps": _steps(sr), "is_manager": manager,
        "can_edit": owner and user.role == User.Role.CUSTOMER and sr.is_pending,
        "can_cancel": sr.is_pending and (owner or manager),
        "can_delete": sr.is_cancelled and (owner or user.role == User.Role.ADMIN),
        "can_advance": manager and sr.is_open and sr.next_status is not None,
        "can_schedule": manager and sr.status in (Status.RECEIVED, Status.CLEANING, Status.READY),
        "pickup_form": PickupForm(initial={"scheduled_pickup": sr.scheduled_pickup}),
        "payment_methods": Payment.Method.choices,
    })


@role_required(User.Role.CUSTOMER, *MANAGERS)
@require_POST
def request_cancel(request, pk):
    sr = _get_request(request.user, pk)
    if not sr.is_pending:  # BR-07
        messages.error(request, "A request can only be cancelled while it is Pending.")
        return redirect("request_detail", pk=pk)
    with transaction.atomic():
        sr.status = Status.CANCELLED
        sr.save(update_fields=["status"])
        sr.log(request.user, Status.PENDING, Status.CANCELLED)
    messages.success(request, f"Request #{sr.pk} cancelled.")
    return redirect("request_detail", pk=pk)


@role_required(User.Role.CUSTOMER, User.Role.ADMIN)
def request_delete(request, pk):
    sr = _get_request(request.user, pk)
    if not sr.is_cancelled:
        messages.error(request, "Only cancelled requests can be deleted. Cancel it first.")
        return redirect("request_detail", pk=pk)
    if request.method == "POST":
        sr.delete()
        messages.success(request, "Request deleted.")
        return redirect("request_list")
    return render(request, "cleaning/confirm_delete.html", {
        "heading": "Delete this request?", "object_label": f"Request #{sr.pk}",
        "warning": "The request, its shoe items and its status history will be removed for good.",
        "back_url": "request_detail", "back_args": [sr.pk]})


@role_required(*MANAGERS)
@require_POST
def request_advance(request, pk):
    sr = _get_request(request.user, pk)
    nxt = sr.next_status
    if not sr.is_open or nxt is None:
        messages.error(request, "This request can't be moved to another status.")
        return redirect("request_detail", pk=pk)
    old = sr.status
    with transaction.atomic():
        sr.status = nxt
        sr.save(update_fields=["status"])
        sr.log(request.user, old, nxt)
        if nxt == Status.COMPLETED:  # record the in-store payment at pickup
            method = request.POST.get("payment_method")
            if method not in Payment.Method.values:
                method = Payment.Method.CASH
            Payment.objects.update_or_create(request=sr, defaults={
                "amount_paid": sr.total_amount, "payment_method": method, "payment_status": Payment.PayStatus.PAID})
    messages.success(request, f"Request #{sr.pk} moved to {sr.get_status_display()}.")
    return redirect("request_detail", pk=pk)


@role_required(*MANAGERS)
@require_POST
def request_pickup(request, pk):
    sr = _get_request(request.user, pk)
    if sr.status not in (Status.RECEIVED, Status.CLEANING, Status.READY):
        messages.error(request, "A pickup date can be set once the shoes are Received and until they are picked up.")
        return redirect("request_detail", pk=pk)
    form = PickupForm(request.POST)
    if form.is_valid():
        sr.scheduled_pickup = form.cleaned_data["scheduled_pickup"]
        sr.save(update_fields=["scheduled_pickup"])
        messages.success(request, f"Pickup scheduled for {sr.scheduled_pickup:%B %d, %Y}.")
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return redirect("request_detail", pk=pk)