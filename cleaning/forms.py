from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils import timezone

from .models import RequestItem, Service, ServiceRequest

MAX_PHOTO_BYTES = 3 * 1024 * 1024  # 3 MB
MAX_PAIRS = 20


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = ("service_name", "description", "base_price", "is_active")
        labels = {"service_name": "Service name", "base_price": "Price per pair (PHP)", "is_active": "Show in catalog"}
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "base_price": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
        }
        error_messages = {
            "service_name": {"required": "Enter a service name."},
            "base_price": {"required": "Enter a price.", "invalid": "Enter a valid price."},
        }

    def clean_service_name(self):
        name = " ".join(self.cleaned_data["service_name"].split())
        taken = Service.objects.filter(service_name__iexact=name).exclude(pk=self.instance.pk)
        if taken.exists():
            raise ValidationError("A service with this name already exists.")
        return name

    def clean_base_price(self):
        price = self.cleaned_data["base_price"]
        if price <= 0:
            raise ValidationError("Price must be greater than zero.")  # BR-03
        return price


class RequestItemForm(forms.ModelForm):
    quantity = forms.IntegerField(
        label="Pairs", min_value=1, max_value=MAX_PAIRS, initial=1,
        error_messages={"min_value": "At least 1 pair.", "max_value": f"At most {MAX_PAIRS} pairs.",
                        "required": "Enter the number of pairs.", "invalid": "Enter a whole number."},
    )

    class Meta:
        model = RequestItem
        fields = ("service", "shoe_brand", "shoe_color", "quantity", "photo")
        labels = {"shoe_brand": "Brand and model", "shoe_color": "Color", "photo": "Photo of the shoes (optional)"}
        widgets = {"photo": forms.FileInput(attrs={"accept": "image/*"})}
        error_messages = {
            "service": {"required": "Choose a service."},
            "shoe_brand": {"required": "Enter the shoe brand and model."},
            "shoe_color": {"required": "Enter the shoe color."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Service.objects.filter(is_active=True)
        if self.instance.pk:  # keep an already-chosen service even if it was deactivated later
            qs = Service.objects.filter(is_active=True) | Service.objects.filter(pk=self.instance.service_id)
        self.fields["service"].queryset = qs.order_by("service_name")
        self.fields["service"].empty_label = "Choose a service"

    def clean_shoe_brand(self):
        return " ".join(self.cleaned_data["shoe_brand"].split())

    def clean_shoe_color(self):
        return " ".join(self.cleaned_data["shoe_color"].split())

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and hasattr(photo, "size") and photo.size > MAX_PHOTO_BYTES:
            raise ValidationError("Photo is too large. Choose an image under 3 MB.")
        return photo


class BaseItemFormSet(BaseInlineFormSet):
    default_error_messages = {
        "too_few_forms": "Add at least one pair of shoes.",
        "too_many_forms": "You can add up to 10 shoe items per request.",
    }

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        total = sum(
            f.cleaned_data.get("quantity", 0)
            for f in self.forms
            if f.cleaned_data and not f.cleaned_data.get("DELETE")
        )
        if total > MAX_PAIRS:
            raise ValidationError(f"A single request can include up to {MAX_PAIRS} pairs in total.")


_common = dict(form=RequestItemForm, formset=BaseItemFormSet, min_num=1, validate_min=True, max_num=10, validate_max=True)
CreateItemFormSet = inlineformset_factory(ServiceRequest, RequestItem, extra=2, can_delete=False, **_common)
EditItemFormSet = inlineformset_factory(ServiceRequest, RequestItem, extra=1, can_delete=True, **_common)


class PickupForm(forms.Form):
    scheduled_pickup = forms.DateField(
        label="Pickup date",
        widget=forms.DateInput(attrs={"type": "date"}),
        error_messages={"required": "Choose a pickup date.", "invalid": "Enter a valid date."},
    )

    def clean_scheduled_pickup(self):
        day = self.cleaned_data["scheduled_pickup"]
        today = timezone.localdate()
        if day < today:
            raise ValidationError("The pickup date can't be in the past.")
        if day > today + timedelta(days=90):
            raise ValidationError("Choose a pickup date within the next 90 days.")
        return day


class RequestFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Search")
    status = forms.ChoiceField(required=False, label="Status", choices=[("", "All statuses")] + ServiceRequest.Status.choices)
    date = forms.DateField(required=False, label="Submitted on", widget=forms.DateInput(attrs={"type": "date"}))