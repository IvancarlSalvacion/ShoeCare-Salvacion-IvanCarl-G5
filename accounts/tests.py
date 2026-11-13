import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import User

PW = "Clean-Kicks-2026"


def make_user(email="cust@example.com", role=User.Role.CUSTOMER, name="Casey Customer"):
    return User.objects.create_user(email=email, password=PW, full_name=name, role=role)


class RegistrationTests(TestCase):
    data = {"full_name": "Ana Reyes", "email": "Ana@Example.com", "contact_number": "0917 123 4567",
            "password1": PW, "password2": PW}

    def test_register_creates_hashed_customer(self):
        resp = self.client.post(reverse("register"), self.data, follow=True)
        self.assertRedirects(resp, reverse("login"))
        user = User.objects.get(email="ana@example.com")
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertNotEqual(user.password, PW)
        self.assertTrue(user.check_password(PW))
        self.assertContains(resp, "Account created")

    def test_duplicate_email_rejected_case_insensitive(self):
        make_user("ana@example.com")
        resp = self.client.post(reverse("register"), self.data)
        self.assertContains(resp, "already exists")
        self.assertEqual(User.objects.count(), 1)

    def test_password_mismatch(self):
        resp = self.client.post(reverse("register"), {**self.data, "password2": "different"})
        self.assertContains(resp, "don&#x27;t match")
        self.assertFalse(User.objects.exists())

    def test_required_fields_and_email_format(self):
        resp = self.client.post(reverse("register"), {"email": "not-an-email"})
        self.assertContains(resp, "Enter a valid email address")
        self.assertContains(resp, "Enter your full name")
        self.assertFalse(User.objects.exists())

    def test_weak_password_rejected(self):
        resp = self.client.post(reverse("register"), {**self.data, "password1": "12345678", "password2": "12345678"})
        self.assertFalse(User.objects.exists())
        self.assertEqual(resp.status_code, 200)

    def test_cannot_self_register_as_admin(self):
        self.client.post(reverse("register"), {**self.data, "role": "ADMIN"})
        self.assertEqual(User.objects.get().role, User.Role.CUSTOMER)


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_login_success_goes_to_role_dashboard(self):
        resp = self.client.post(reverse("login"), {"username": "CUST@example.com", "password": PW}, follow=True)
        self.assertRedirects(resp, reverse("customer_dashboard"))

    def test_login_invalid_shows_error(self):
        resp = self.client.post(reverse("login"), {"username": "cust@example.com", "password": "wrong"})
        self.assertContains(resp, "Incorrect email or password")

    def test_logout_ends_session(self):
        self.client.force_login(self.user)
        self.client.post(reverse("logout"))
        self.assertRedirects(self.client.get(reverse("customer_dashboard")),
                             f"{reverse('login')}?next={reverse('customer_dashboard')}")

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)

    def test_protected_pages_redirect_to_login(self):
        for name in ["dashboard", "customer_dashboard", "staff_dashboard", "admin_dashboard", "profile", "profile_edit"]:
            url = reverse(name)
            self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}", msg_prefix=name)


class RoleDashboardTests(TestCase):
    def setUp(self):
        self.users = {
            User.Role.CUSTOMER: make_user("c@example.com", User.Role.CUSTOMER),
            User.Role.STAFF: make_user("s@example.com", User.Role.STAFF, "Sam Staff"),
            User.Role.ADMIN: make_user("a@example.com", User.Role.ADMIN, "Ada Admin"),
        }

    def test_dashboard_redirects_by_role(self):
        expected = {User.Role.CUSTOMER: "customer_dashboard", User.Role.STAFF: "staff_dashboard",
                    User.Role.ADMIN: "admin_dashboard"}
        for role, user in self.users.items():
            self.client.force_login(user)
            self.assertRedirects(self.client.get(reverse("dashboard")), reverse(expected[role]))

    def test_cannot_open_other_roles_dashboards(self):
        names = {User.Role.CUSTOMER: "customer_dashboard", User.Role.STAFF: "staff_dashboard",
                 User.Role.ADMIN: "admin_dashboard"}
        for role, user in self.users.items():
            self.client.force_login(user)
            for other_role, name in names.items():
                if other_role == role:
                    self.assertEqual(self.client.get(reverse(name)).status_code, 200)
                else:
                    resp = self.client.get(reverse(name))
                    self.assertRedirects(resp, reverse(names[role]), msg_prefix=f"{role}->{name}")

    def test_admin_flags(self):
        self.assertTrue(self.users[User.Role.ADMIN].is_superuser)
        self.assertFalse(self.users[User.Role.STAFF].is_staff)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ProfileTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        from django.conf import settings
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = make_user()
        self.other = make_user("other@example.com", name="Other Person")
        self.client.force_login(self.user)

    def test_view_own_profile_only(self):
        resp = self.client.get(reverse("profile"))
        self.assertContains(resp, "cust@example.com")
        self.assertNotContains(resp, "other@example.com")

    def test_update_profile(self):
        resp = self.client.post(reverse("profile_edit"), {
            "full_name": "Casey C. Customer", "email": "new@example.com", "contact_number": "09171234567"}, follow=True)
        self.assertRedirects(resp, reverse("profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.full_name, "Casey C. Customer")
        self.assertEqual(self.user.email, "new@example.com")
        self.other.refresh_from_db()
        self.assertEqual(self.other.full_name, "Other Person")

    def test_cannot_take_someone_elses_email(self):
        resp = self.client.post(reverse("profile_edit"), {"full_name": "Casey", "email": "other@example.com"})
        self.assertContains(resp, "already exists")

    def test_role_cannot_be_changed_via_profile(self):
        self.client.post(reverse("profile_edit"), {"full_name": "Casey", "email": "cust@example.com", "role": "ADMIN"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.CUSTOMER)

    def test_upload_photo(self):
        buf = io.BytesIO()
        Image.new("RGB", (20, 20), "teal").save(buf, "PNG")
        photo = SimpleUploadedFile("me.png", buf.getvalue(), content_type="image/png")
        self.client.post(reverse("profile_edit"), {"full_name": "Casey", "email": "cust@example.com", "profile_photo": photo})
        self.user.refresh_from_db()
        self.assertTrue(self.user.profile_photo)

    def test_invalid_photo_rejected(self):
        bad = SimpleUploadedFile("x.png", b"not an image", content_type="image/png")
        resp = self.client.post(reverse("profile_edit"), {"full_name": "Casey", "email": "cust@example.com", "profile_photo": bad})
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.profile_photo)
