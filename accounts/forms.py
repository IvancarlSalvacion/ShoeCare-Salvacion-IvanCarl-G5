import re

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from .models import User

PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-]{6,18}$")
MAX_PHOTO_BYTES = 2 * 1024 * 1024  # 2 MB


def _clean_email(form, value, exclude_pk=None):
    email = value.strip().lower()
    qs = User.objects.filter(email__iexact=email)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise forms.ValidationError("An account with this email already exists.")
    return email


def _clean_phone(value):
    value = (value or "").strip()
    if value and not PHONE_RE.match(value):
        raise forms.ValidationError("Enter a valid contact number, e.g. 0917 123 4567.")
    return value


class RegistrationForm(forms.ModelForm):
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="At least 8 characters. Avoid common or all-number passwords.",
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = User
        fields = ("full_name", "email", "contact_number")
        labels = {"full_name": "Full name", "contact_number": "Contact number (optional)"}
        widgets = {
            "full_name": forms.TextInput(attrs={"autocomplete": "name", "autofocus": True}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "contact_number": forms.TextInput(attrs={"autocomplete": "tel"}),
        }
        error_messages = {
            "full_name": {"required": "Enter your full name."},
            "email": {"required": "Enter your email address.", "invalid": "Enter a valid email address."},
        }

    def clean_full_name(self):
        name = " ".join(self.cleaned_data["full_name"].split())
        if len(name) < 2:
            raise forms.ValidationError("Enter your full name.")
        return name

    def clean_email(self):
        return _clean_email(self, self.cleaned_data["email"])

    def clean_contact_number(self):
        return _clean_phone(self.cleaned_data.get("contact_number"))

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords don't match.")
        elif p1:
            try:
                password_validation.validate_password(p1, User(email=cleaned.get("email", ""), full_name=cleaned.get("full_name", "")))
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.CUSTOMER  # public sign-ups are always customers
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
        error_messages={"required": "Enter your email address.", "invalid": "Enter a valid email address."},
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
        error_messages={"required": "Enter your password."},
    )
    error_messages = {
        "invalid_login": "Incorrect email or password. Check your details and try again.",
        "inactive": "This account is inactive. Contact the shop to get it reactivated.",
    }

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class ProfileForm(forms.ModelForm):
    remove_photo = forms.BooleanField(required=False, label="Remove current photo")

    class Meta:
        model = User
        fields = ("full_name", "email", "contact_number", "profile_photo")
        labels = {"full_name": "Full name", "contact_number": "Contact number", "profile_photo": "Profile photo"}
        widgets = {
            "profile_photo": forms.FileInput(attrs={"accept": "image/*"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
        }
        error_messages = {
            "full_name": {"required": "Enter your full name."},
            "email": {"required": "Enter your email address.", "invalid": "Enter a valid email address."},
        }

    def clean_full_name(self):
        name = " ".join(self.cleaned_data["full_name"].split())
        if len(name) < 2:
            raise forms.ValidationError("Enter your full name.")
        return name

    def clean_email(self):
        return _clean_email(self, self.cleaned_data["email"], exclude_pk=self.instance.pk)

    def clean_contact_number(self):
        return _clean_phone(self.cleaned_data.get("contact_number"))

    def clean_profile_photo(self):
        photo = self.cleaned_data.get("profile_photo")
        if photo and hasattr(photo, "size") and photo.size > MAX_PHOTO_BYTES:
            raise forms.ValidationError("Photo is too large. Choose an image under 2 MB.")
        return photo

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("remove_photo") and not self.files.get("profile_photo"):
            user.profile_photo = None
        if commit:
            user.save()
        return user
