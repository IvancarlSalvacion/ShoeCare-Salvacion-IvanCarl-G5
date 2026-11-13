from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models import Q


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email).lower(), **extra_fields)
        user.set_password(password)  # hashes the password (PBKDF2 by default)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", User.Role.CUSTOMER)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields["role"] = User.Role.ADMIN
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Maps to the `users` table in the SDD (Section 4.4), plus profile fields."""

    class Role(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Customer"
        STAFF = "STAFF", "Staff"
        ADMIN = "ADMIN", "Administrator"

    user_id = models.AutoField(primary_key=True)
    email = models.EmailField(max_length=100, unique=True)
    # The SDD names this column `password_hash`; Django still hashes it for us.
    password = models.CharField(max_length=255, db_column="password_hash")
    full_name = models.CharField(max_length=100)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CUSTOMER)
    contact_number = models.CharField(max_length=20, blank=True)
    profile_photo = models.ImageField(upload_to="profile_photos/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "users"
        constraints = [
            models.CheckConstraint(
                condition=Q(role__in=["CUSTOMER", "STAFF", "ADMIN"]),
                name="users_role_check",  # BR-02
            )
        ]

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    def save(self, *args, **kwargs):
        self.email = self.email.lower()
        # Administrators get full permissions in the Django admin site; nobody else does.
        self.is_superuser = self.role == self.Role.ADMIN
        super().save(*args, **kwargs)

    # Django admin site access is for administrators only.
    @property
    def is_staff(self):
        return self.role == self.Role.ADMIN

    @property
    def is_customer(self):
        return self.role == self.Role.CUSTOMER

    @property
    def is_shop_staff(self):
        return self.role == self.Role.STAFF

    @property
    def is_shop_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def dashboard_url_name(self):
        return {
            self.Role.CUSTOMER: "customer_dashboard",
            self.Role.STAFF: "staff_dashboard",
            self.Role.ADMIN: "admin_dashboard",
        }[self.role]

    @property
    def initials(self):
        parts = self.full_name.split()
        return "".join(p[0] for p in parts[:2]).upper() or "?"

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.full_name.split()[0] if self.full_name else self.email
