from django.contrib import admin

from .models import Payment, RequestItem, Service, ServiceRequest, StatusLog


class RequestItemInline(admin.TabularInline):
    model = RequestItem
    extra = 0


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("service_name", "base_price", "is_active")
    list_filter = ("is_active",)
    search_fields = ("service_name",)


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = ("request_id", "user", "status", "total_amount", "scheduled_pickup", "request_date")
    list_filter = ("status",)
    inlines = [RequestItemInline]


admin.site.register(StatusLog)
admin.site.register(Payment)