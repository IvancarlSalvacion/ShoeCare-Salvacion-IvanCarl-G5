import io
import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import User

from .models import Service, ServiceRequest

PW = "Clean-Kicks-2026"


def mk(email, role=User.Role.CUSTOMER, name="Test User"):
    return User.objects.create_user(email=email, password=PW, full_name=name, role=role)


def formset_post(rows, prefix="items", initial=0):
    data = {f"{prefix}-TOTAL_FORMS": len(rows), f"{prefix}-INITIAL_FORMS": initial,
            f"{prefix}-MIN_NUM_FORMS": 1, f"{prefix}-MAX_NUM_FORMS": 10}
    for i, row in enumerate(rows):
        for k, v in row.items():
            data[f"{prefix}-{i}-{k}"] = v
    return data


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CoreBase(TestCase):
    @classmethod
    def tearDownClass(cls):
        from django.conf import settings
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.cust = mk("c@x.test", name="Ana Reyes")
        self.cust2 = mk("c2@x.test", name="Ben Cruz")
        self.staff = mk("s@x.test", User.Role.STAFF, "Sam Staff")
        self.admin = mk("a@x.test", User.Role.ADMIN, "Ada Admin")
        self.deep = Service.objects.create(service_name="Deep Clean", base_price=Decimal("350.00"))
        self.suede = Service.objects.create(service_name="Suede Care", base_price=Decimal("500.00"))

    def make_request(self, user=None, rows=None):
        self.client.force_login(user or self.cust)
        rows = rows or [{"service": self.deep.pk, "shoe_brand": "Nike Air Force 1", "shoe_color": "White", "quantity": 2}]
        resp = self.client.post(reverse("request_create"), formset_post(rows))
        return ServiceRequest.objects.latest("request_id"), resp


class CreateReadTests(CoreBase):
    def test_customer_creates_request_with_logged_status_and_total(self):
        sr, resp = self.make_request(rows=[
            {"service": self.deep.pk, "shoe_brand": "Nike AF1", "shoe_color": "White", "quantity": 2},
            {"service": self.suede.pk, "shoe_brand": "Vans Old Skool", "shoe_color": "Black", "quantity": 1},
            {"service": "", "shoe_brand": "", "shoe_color": "", "quantity": 1},
        ])
        self.assertRedirects(resp, reverse("request_detail", args=[sr.pk]))
        self.assertEqual(sr.user, self.cust)
        self.assertEqual(sr.status, "PENDING")
        self.assertEqual(sr.items.count(), 2)
        self.assertEqual(sr.total_amount, Decimal("1200.00"))
        log = sr.logs.get()
        self.assertEqual((log.status_from, log.status_to, log.updated_by), ("", "PENDING", self.cust))

    def test_photo_upload(self):
        buf = io.BytesIO(); Image.new("RGB", (30, 30), "teal").save(buf, "PNG")
        rows = [{"service": self.deep.pk, "shoe_brand": "Adidas", "shoe_color": "Grey", "quantity": 1,
                 "photo": SimpleUploadedFile("s.png", buf.getvalue(), content_type="image/png")}]
        sr, _ = self.make_request(rows=rows)
        self.assertTrue(sr.items.get().photo)

    def test_validation_errors(self):
        self.client.force_login(self.cust)
        cases = {
            "no items": [{"service": "", "shoe_brand": "", "shoe_color": "", "quantity": 1}],
            "zero qty": [{"service": self.deep.pk, "shoe_brand": "A", "shoe_color": "B", "quantity": 0}],
            "too many": [{"service": self.deep.pk, "shoe_brand": "A", "shoe_color": "B", "quantity": 21}],
            "missing brand": [{"service": self.deep.pk, "shoe_brand": "", "shoe_color": "B", "quantity": 1}],
        }
        for name, rows in cases.items():
            resp = self.client.post(reverse("request_create"), formset_post(rows))
            self.assertEqual(resp.status_code, 200, name)
        self.assertFalse(ServiceRequest.objects.exists())

    def test_inactive_service_not_accepted(self):
        self.suede.is_active = False; self.suede.save()
        self.client.force_login(self.cust)
        resp = self.client.post(reverse("request_create"), formset_post(
            [{"service": self.suede.pk, "shoe_brand": "A", "shoe_color": "B", "quantity": 1}]))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ServiceRequest.objects.exists())

    def test_price_snapshot_unchanged_after_price_change(self):  # BR-06
        sr, _ = self.make_request()
        self.deep.base_price = Decimal("999.00"); self.deep.save()
        self.assertEqual(sr.items.get().unit_price, Decimal("350.00"))
        sr.refresh_from_db()
        self.assertEqual(sr.total_amount, Decimal("700.00"))

    def test_customer_only_sees_own_requests(self):
        sr, _ = self.make_request()
        self.client.force_login(self.cust2)
        self.assertEqual(self.client.get(reverse("request_detail", args=[sr.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("request_list")), "Ana Reyes")
        self.assertEqual(self.client.post(reverse("request_cancel", args=[sr.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("request_edit", args=[sr.pk])).status_code, 404)

    def test_login_required_and_roles(self):
        for name in ["request_list", "request_create", "service_list"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)
        self.client.force_login(self.staff)
        self.assertRedirects(self.client.get(reverse("request_create")), reverse("staff_dashboard"))

    def test_staff_sees_all_and_can_filter(self):
        self.make_request(self.cust)
        self.make_request(self.cust2)
        self.client.force_login(self.staff)
        page = self.client.get(reverse("request_list"))
        self.assertContains(page, "Ana Reyes"); self.assertContains(page, "Ben Cruz")
        by_name = self.client.get(reverse("request_list"), {"q": "ben"})
        self.assertContains(by_name, "Ben Cruz"); self.assertNotContains(by_name, "Ana Reyes")
        by_status = self.client.get(reverse("request_list"), {"status": "READY"})
        self.assertNotContains(by_status, "Ana Reyes")
        by_date = self.client.get(reverse("request_list"), {"date": timezone.localdate().isoformat()})
        self.assertContains(by_date, "Ana Reyes")


class UpdateDeleteTests(CoreBase):
    def test_edit_pending_updates_items_and_total(self):
        sr, _ = self.make_request()
        item = sr.items.get()
        data = formset_post([
            {"item_id": item.pk, "request": sr.pk, "service": self.deep.pk, "shoe_brand": "Nike AF1", "shoe_color": "White", "quantity": 1},
            {"service": self.suede.pk, "shoe_brand": "Vans", "shoe_color": "Black", "quantity": 1},
        ], initial=1)
        resp = self.client.post(reverse("request_edit", args=[sr.pk]), data)
        self.assertRedirects(resp, reverse("request_detail", args=[sr.pk]))
        sr.refresh_from_db()
        self.assertEqual(sr.items.count(), 2)
        self.assertEqual(sr.total_amount, Decimal("850.00"))

    def test_cannot_edit_after_received(self):
        sr, _ = self.make_request()
        sr.status = "RECEIVED"; sr.save()
        resp = self.client.get(reverse("request_edit", args=[sr.pk]))
        self.assertRedirects(resp, reverse("request_detail", args=[sr.pk]))

    def test_cancel_then_delete(self):
        sr, _ = self.make_request()
        self.client.post(reverse("request_cancel", args=[sr.pk]))
        sr.refresh_from_db()
        self.assertEqual(sr.status, "CANCELLED")
        self.assertEqual(sr.logs.count(), 2)
        self.client.post(reverse("request_delete", args=[sr.pk]))
        self.assertFalse(ServiceRequest.objects.filter(pk=sr.pk).exists())

    def test_cannot_cancel_after_pending(self):  # BR-07
        sr, _ = self.make_request()
        sr.status = "CLEANING"; sr.save()
        self.client.post(reverse("request_cancel", args=[sr.pk]))
        sr.refresh_from_db()
        self.assertEqual(sr.status, "CLEANING")

    def test_cannot_delete_active_request(self):
        sr, _ = self.make_request()
        self.client.post(reverse("request_delete", args=[sr.pk]))
        self.assertTrue(ServiceRequest.objects.filter(pk=sr.pk).exists())


class WorkflowTests(CoreBase):
    def test_staff_moves_through_all_stages_and_payment_recorded(self):
        sr, _ = self.make_request()
        self.client.force_login(self.staff)
        for expected in ["RECEIVED", "CLEANING", "READY"]:
            self.client.post(reverse("request_advance", args=[sr.pk]))
            sr.refresh_from_db()
            self.assertEqual(sr.status, expected)
        self.client.post(reverse("request_advance", args=[sr.pk]), {"payment_method": "IN_STORE"})
        sr.refresh_from_db()
        self.assertEqual(sr.status, "COMPLETED")
        pay = sr.payment
        self.assertEqual((pay.amount_paid, pay.payment_method, pay.payment_status), (Decimal("700.00"), "IN_STORE", "PAID"))
        self.assertEqual([l.status_to for l in sr.logs.all()], ["PENDING", "RECEIVED", "CLEANING", "READY", "COMPLETED"])
        self.client.post(reverse("request_advance", args=[sr.pk]))  # nothing after Completed
        sr.refresh_from_db(); self.assertEqual(sr.status, "COMPLETED")

    def test_customer_cannot_advance(self):
        sr, _ = self.make_request()
        resp = self.client.post(reverse("request_advance", args=[sr.pk]))
        self.assertRedirects(resp, reverse("customer_dashboard"))
        sr.refresh_from_db(); self.assertEqual(sr.status, "PENDING")

    def test_cancelled_cannot_advance(self):
        sr, _ = self.make_request()
        sr.status = "CANCELLED"; sr.save()
        self.client.force_login(self.staff)
        self.client.post(reverse("request_advance", args=[sr.pk]))
        sr.refresh_from_db(); self.assertEqual(sr.status, "CANCELLED")

    def test_pickup_schedule_rules(self):
        sr, _ = self.make_request()
        self.client.force_login(self.staff)
        url = reverse("request_pickup", args=[sr.pk])
        tomorrow = timezone.localdate() + timedelta(days=1)
        self.client.post(url, {"scheduled_pickup": tomorrow.isoformat()})
        sr.refresh_from_db(); self.assertIsNone(sr.scheduled_pickup)  # still Pending
        sr.status = "RECEIVED"; sr.save()
        self.client.post(url, {"scheduled_pickup": (timezone.localdate() - timedelta(days=1)).isoformat()})
        sr.refresh_from_db(); self.assertIsNone(sr.scheduled_pickup)  # past date
        self.client.post(url, {"scheduled_pickup": tomorrow.isoformat()})
        sr.refresh_from_db(); self.assertEqual(sr.scheduled_pickup, tomorrow)


class ServiceCrudTests(CoreBase):
    def test_admin_crud_and_customer_blocked(self):
        self.client.force_login(self.cust)
        self.assertRedirects(self.client.get(reverse("service_create")), reverse("customer_dashboard"))
        self.client.force_login(self.admin)
        self.client.post(reverse("service_create"), {"service_name": "Sole Whitening", "base_price": "250", "is_active": "on", "description": "x"})
        s = Service.objects.get(service_name="Sole Whitening")
        self.client.post(reverse("service_edit", args=[s.pk]), {"service_name": "Sole Whitening", "base_price": "300", "is_active": "on"})
        s.refresh_from_db(); self.assertEqual(s.base_price, Decimal("300.00"))
        self.client.post(reverse("service_toggle", args=[s.pk])); s.refresh_from_db(); self.assertFalse(s.is_active)
        self.client.post(reverse("service_delete", args=[s.pk]))
        self.assertFalse(Service.objects.filter(pk=s.pk).exists())

    def test_service_validation(self):
        self.client.force_login(self.admin)
        for price in ["0", "-5", "abc", ""]:
            self.client.post(reverse("service_create"), {"service_name": "Bad", "base_price": price})
        self.assertFalse(Service.objects.filter(service_name="Bad").exists())
        resp = self.client.post(reverse("service_create"), {"service_name": "deep clean", "base_price": "100"})
        self.assertContains(resp, "already exists")

    def test_used_service_cannot_be_deleted(self):  # BR-08
        self.make_request()
        self.client.force_login(self.admin)
        self.client.post(reverse("service_delete", args=[self.deep.pk]))
        self.assertTrue(Service.objects.filter(pk=self.deep.pk).exists())

    def test_catalog_search_and_visibility(self):
        self.suede.is_active = False; self.suede.save()
        self.client.force_login(self.cust)
        page = self.client.get(reverse("service_list"))
        self.assertContains(page, "Deep Clean"); self.assertNotContains(page, "Suede Care")
        self.assertNotContains(self.client.get(reverse("service_list"), {"q": "zzz"}), "Deep Clean")


class DashboardTests(CoreBase):
    def test_dashboards_render_with_data(self):
        sr, _ = self.make_request()
        for user, text in [(self.cust, "Active orders"), (self.staff, "Work queue"), (self.admin, "Revenue collected")]:
            self.client.force_login(user)
            resp = self.client.get(reverse(user.dashboard_url_name))
            self.assertContains(resp, text)
            self.assertContains(resp, reverse("request_detail", args=[sr.pk]))


# ============================ PD3: hardening tests ============================
class HardeningTests(CoreBase):
    def test_unknown_url_shows_custom_404_not_debug_page(self):
        resp = self.client.get("/this/does/not/exist/")
        self.assertContains(resp, "404 - Page not found", status_code=404)
        self.assertNotContains(resp, "Traceback", status_code=404)

    def test_invalid_and_huge_ids_do_not_crash(self):
        self.client.force_login(self.staff)
        for url in ["/requests/0/", "/requests/99999999999999999999/", "/services/99999999999999999999/edit/"]:
            self.assertIn(self.client.get(url).status_code, (302, 404), url)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/services/99999999999999999999/edit/").status_code, 404)
        self.assertEqual(self.client.get(reverse("request_list"), {"q": "#99999999999999999999"}).status_code, 200)
        self.assertEqual(self.client.get(reverse("request_list"), {"page": "abc", "status": "NOPE", "date": "x"}).status_code, 200)
        self.client.force_login(self.cust)
        self.assertEqual(self.client.get(reverse("request_create"), {"service": "99999999999999999999"}).status_code, 200)

    def test_server_error_shows_custom_500(self):
        safe = Client(raise_request_exception=False)
        safe.force_login(self.cust)
        with mock.patch("cleaning.views.render", side_effect=RuntimeError("boom")):
            resp = safe.get(reverse("service_list"))
        self.assertContains(resp, "500 - Something went wrong", status_code=500)
        self.assertNotContains(resp, "boom", status_code=500)

    def test_state_changing_views_reject_get(self):
        sr, _ = self.make_request()
        self.client.force_login(self.admin)
        for name, args in [("request_cancel", [sr.pk]), ("request_advance", [sr.pk]),
                           ("request_pickup", [sr.pk]), ("service_toggle", [self.deep.pk])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 405, name)
        sr.refresh_from_db(); self.assertEqual(sr.status, "PENDING")
        self.deep.refresh_from_db(); self.assertTrue(self.deep.is_active)

    def test_csrf_token_is_enforced_with_custom_403(self):
        sr, _ = self.make_request()
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.cust)
        resp = strict.post(reverse("request_cancel", args=[sr.pk]))
        self.assertContains(resp, "403 - Access denied", status_code=403)
        sr.refresh_from_db(); self.assertEqual(sr.status, "PENDING")

    def test_duplicate_service_name_blocked_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Service.objects.create(service_name="DEEP CLEAN", base_price=Decimal("100"))

    def test_delete_asks_for_confirmation_before_deleting(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse("service_delete", args=[self.suede.pk]))
        self.assertContains(page, "Yes, delete")
        self.assertTrue(Service.objects.filter(pk=self.suede.pk).exists())
        sr, _ = self.make_request()
        sr.status = "CANCELLED"; sr.save()
        self.client.force_login(self.cust)
        self.assertContains(self.client.get(reverse("request_delete", args=[sr.pk])), "Yes, delete")
        self.assertTrue(ServiceRequest.objects.filter(pk=sr.pk).exists())

    def test_request_list_query_count_does_not_grow(self):
        row = [{"service": self.deep.pk, "shoe_brand": "A", "shoe_color": "B", "quantity": 1}]
        self.make_request(rows=row)
        self.client.force_login(self.staff)
        with CaptureQueriesContext(connection) as few:
            self.client.get(reverse("request_list"))
        for _ in range(4):
            self.make_request(rows=row)
        self.client.force_login(self.staff)
        with CaptureQueriesContext(connection) as many:
            self.client.get(reverse("request_list"))
        self.assertEqual(len(few), len(many))

    def test_admin_dashboard_links_to_add_staff(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("admin_dashboard")), "Add staff account")

    def test_no_placeholder_menu_items(self):
        for user in (self.cust, self.staff, self.admin):
            self.client.force_login(user)
            page = self.client.get(reverse(user.dashboard_url_name))
            self.assertNotContains(page, "coming-soon")
            self.assertNotContains(page, "Reports")