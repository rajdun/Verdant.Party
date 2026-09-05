from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.marketplaces.tests.factories import make_marketplace, make_product
from apps.orders.models import Order, OrderLine, OrderStatus


def make_order(marketplace, external_order_id="ORDER-1", **overrides):
    defaults = dict(
        buyer_full_name="Anna Kowalska",
        buyer_login="kupujacy1",
        delivery_recipient_name="Anna Kowalska",
        delivery_city="Kraków",
        total_to_pay=Decimal("214.80"),
        platform_commission=Decimal("13.80"),
        placed_at=timezone.now(),
    )
    defaults.update(overrides)
    return Order.objects.create(
        marketplace=marketplace, external_order_id=external_order_id, **defaults
    )


class OrderListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="magazyn", password="tajne123")
        cls.marketplace = make_marketplace()
        cls.other_marketplace = make_marketplace(name="Allegro produkcja")
        cls.product = make_product()

        cls.first = make_order(cls.marketplace, "ORDER-1")
        cls.second = make_order(
            cls.other_marketplace,
            "ORDER-2",
            buyer_full_name="Jan Nowak",
            status=OrderStatus.SHIPPED,
            placed_at=timezone.now() - timedelta(days=10),
            total_to_pay=Decimal("50.00"),
            platform_commission=Decimal("5.00"),
        )
        OrderLine.objects.create(
            order=cls.first,
            product=cls.product,
            external_offer_id="12345",
            external_offer_name="Ficus lyrata 12cm",
            quantity=2,
            unit_price=Decimal("99.90"),
        )
        OrderLine.objects.create(
            order=cls.second,
            product=None,
            external_offer_id="99999",
            external_offer_name="Doniczka ceramiczna",
            quantity=1,
            unit_price=Decimal("19.00"),
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()

        response = self.client.get(reverse("orders:order_list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("users:login"), response["Location"])

    def test_lists_all_orders(self):
        response = self.client.get(reverse("orders:order_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["orders"]), 2)

    def test_search_matches_buyer_and_offer_name(self):
        by_buyer = self.client.get(reverse("orders:order_list"), {"q": "Nowak"})
        by_offer = self.client.get(reverse("orders:order_list"), {"q": "Ficus"})

        self.assertEqual([o.pk for o in by_buyer.context["orders"]], [self.second.pk])
        self.assertEqual([o.pk for o in by_offer.context["orders"]], [self.first.pk])

    def test_filter_by_marketplace_and_status(self):
        by_marketplace = self.client.get(
            reverse("orders:order_list"), {"marketplace": self.marketplace.pk}
        )
        by_status = self.client.get(
            reverse("orders:order_list"), {"status": OrderStatus.SHIPPED}
        )

        self.assertEqual([o.pk for o in by_marketplace.context["orders"]], [self.first.pk])
        self.assertEqual([o.pk for o in by_status.context["orders"]], [self.second.pk])

    def test_filter_by_date_range(self):
        yesterday = (timezone.localtime() - timedelta(days=1)).date().isoformat()

        response = self.client.get(reverse("orders:order_list"), {"date_from": yesterday})

        self.assertEqual([o.pk for o in response.context["orders"]], [self.first.pk])

    def test_unmapped_filter_finds_orders_missing_a_product(self):
        response = self.client.get(reverse("orders:order_list"), {"unmapped": "true"})

        self.assertEqual([o.pk for o in response.context["orders"]], [self.second.pk])

    def test_totals_cover_filtered_set_without_double_counting(self):
        response = self.client.get(reverse("orders:order_list"))

        totals = response.context["totals"]
        self.assertEqual(totals["count"], 2)
        self.assertEqual(totals["revenue"], Decimal("264.80"))
        self.assertEqual(totals["commission"], Decimal("18.80"))

    def test_sorting_by_allowed_field(self):
        response = self.client.get(
            reverse("orders:order_list"), {"sort": "total_to_pay", "order": "asc"}
        )

        self.assertEqual(
            [o.pk for o in response.context["orders"]], [self.second.pk, self.first.pk]
        )

    def test_unknown_sort_field_is_ignored(self):
        response = self.client.get(reverse("orders:order_list"), {"sort": "credentials"})

        self.assertEqual(response.status_code, 200)


class OrderDetailAndStatusTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="magazyn", password="tajne123")
        self.client.force_login(self.user)
        self.marketplace = make_marketplace()
        self.order = make_order(self.marketplace)

    def test_detail_renders(self):
        response = self.client.get(reverse("orders:order_detail", args=[self.order.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["order"], self.order)

    def test_status_flow_new_to_shipped(self):
        self.client.post(reverse("orders:order_start_fulfillment", args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.IN_FULFILLMENT)

        self.client.post(reverse("orders:order_mark_shipped", args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.SHIPPED)

    def test_shipped_order_cannot_be_cancelled(self):
        self.order.status = OrderStatus.SHIPPED
        self.order.save(update_fields=["status"])

        response = self.client.post(
            reverse("orders:order_cancel", args=[self.order.pk]), follow=True
        )

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.SHIPPED)
        self.assertContains(response, "Nie można anulować")

    def test_status_change_requires_post(self):
        response = self.client.get(reverse("orders:order_cancel", args=[self.order.pk]))

        self.assertEqual(response.status_code, 405)
