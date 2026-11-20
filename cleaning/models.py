from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import DecimalField, F, Q, Sum

# The five stages a request moves through (CANCELLED is a side exit from PENDING).
STATUS_FLOW = ["PENDING", "RECEIVED", "CLEANING", "READY", "COMPLETED"]


class Service(models.Model):
    """services table: cleaning / restoration services the shop offers."""

    service_id = models.AutoField(primary_key=True)
    service_name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)])
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "services"
        ordering = ["service_name"]
        constraints = [models.CheckConstraint(condition=Q(base_price__gt=0), name="services_base_price_gt_0")]  # BR-03

    def __str__(self):
        return self.service_name


class ServiceRequest(models.Model):
    """service_requests table: one order placed by a customer."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RECEIVED = "RECEIVED", "Received"
        CLEANING = "CLEANING", "Cleaning"
        READY = "READY", "Ready for pickup"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    request_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="service_requests")
    request_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    scheduled_pickup = models.DateField(null=True, blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        db_table = "service_requests"
        ordering = ["-request_date", "-request_id"]
        constraints = [
            models.CheckConstraint(  # BR-04
                condition=Q(status__in=["PENDING", "RECEIVED", "CLEANING", "READY", "COMPLETED", "CANCELLED"]),
                name="service_requests_status_check",
            ),
            models.CheckConstraint(condition=Q(total_amount__gte=0), name="service_requests_total_gte_0"),
        ]

    def __str__(self):
        return f"Request #{self.request_id}"

    # ---- workflow helpers ----
    @property
    def next_status(self):
        if self.status not in STATUS_FLOW:
            return None
        i = STATUS_FLOW.index(self.status)
        return STATUS_FLOW[i + 1] if i + 1 < len(STATUS_FLOW) else None

    @property
    def next_status_label(self):
        return self.Status(self.next_status).label if self.next_status else ""

    @property
    def is_pending(self):
        return self.status == self.Status.PENDING

    @property
    def is_cancelled(self):
        return self.status == self.Status.CANCELLED

    @property
    def is_open(self):
        return self.status not in (self.Status.COMPLETED, self.Status.CANCELLED)

    @property
    def pair_count(self):
        return sum(item.quantity for item in self.items.all())

    def recalc_total(self):
        # Always read fresh from the database (the cached/prefetched items can be stale after an edit).
        total = RequestItem.objects.filter(request=self).aggregate(
            t=Sum(F("quantity") * F("unit_price"), output_field=DecimalField(max_digits=12, decimal_places=2)))["t"]
        self.total_amount = total or 0
        self.save(update_fields=["total_amount"])

    def log(self, by_user, old, new):
        return StatusLog.objects.create(request=self, updated_by=by_user, status_from=old, status_to=new)


class RequestItem(models.Model):
    """request_items table: one shoe item (brand, colour, photo, service) in a request."""

    item_id = models.AutoField(primary_key=True)
    request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name="items")
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="request_items")  # BR-08
    shoe_brand = models.CharField(max_length=50)
    shoe_color = models.CharField(max_length=50)
    photo = models.ImageField(upload_to="shoe_photos/", max_length=255, null=True, blank=True, db_column="image_url")
    quantity = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)  # BR-06: price at submission time

    class Meta:
        db_table = "request_items"
        ordering = ["item_id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gte=1), name="request_items_quantity_gte_1"),  # BR-05
            models.CheckConstraint(condition=Q(unit_price__gt=0), name="request_items_unit_price_gt_0"),
        ]

    def __str__(self):
        return f"{self.shoe_brand} ({self.shoe_color}) x{self.quantity}"

    @property
    def line_total(self):
        return self.quantity * self.unit_price


class StatusLog(models.Model):
    """status_logs table: audit trail of every status change."""

    log_id = models.AutoField(primary_key=True)
    request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name="logs")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="status_updates")
    status_from = models.CharField(max_length=20, blank=True)
    status_to = models.CharField(max_length=20)
    log_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "status_logs"
        ordering = ["log_time", "log_id"]

    def __str__(self):
        return f"#{self.request_id}: {self.status_from or 'new'} -> {self.status_to}"


class Payment(models.Model):
    """payments table: in-store / cash settlement recorded when a request is completed."""

    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        IN_STORE = "IN_STORE", "In-store"

    class PayStatus(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PAID = "PAID", "Paid"

    payment_id = models.AutoField(primary_key=True)
    request = models.OneToOneField(ServiceRequest, on_delete=models.CASCADE, related_name="payment")
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    payment_method = models.CharField(max_length=20, choices=Method.choices, default=Method.CASH)
    payment_status = models.CharField(max_length=20, choices=PayStatus.choices, default=PayStatus.UNPAID)

    class Meta:
        db_table = "payments"
        constraints = [models.CheckConstraint(condition=Q(amount_paid__gte=0), name="payments_amount_gte_0")]

    def __str__(self):
        return f"Payment for request #{self.request_id}"