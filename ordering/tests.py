import datetime
import io

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from accounts.models import Team, TeamMembership
from ordering.models import OrderList, OrderListItem, PurchaseItem
from ordering import services

User = get_user_model()


class OrderDetailMobileTouchUsabilityTests(TestCase):
    """
    Same mobile-usability pass applied to the Prep List screens: a back
    link instead of relying on the hamburger menu, and the primary
    actions (Save Draft/Finalize, or Reopen once finalized) living in a
    fixed bottom bar reachable without scrolling back up past the table.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000200", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.purchase_item = PurchaseItem.objects.create(team=self.team, name="Onions", category="Produce")
        self.order, _ = services.get_or_create_order(
            self.team, datetime.date(2026, 3, 1), self.user, blank=True
        )
        OrderListItem.objects.create(order_list=self.order, purchase_item=self.purchase_item, sort_order=1)

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_detail_has_a_back_link_to_the_order_list(self):
        resp = self.client.get(reverse("ordering:order_detail", args=[str(self.order.order_date)]))
        self.assertContains(resp, reverse("ordering:order_list"))
        self.assertContains(resp, "btn-back")

    def test_draft_primary_actions_live_in_the_sticky_bar_outside_the_form(self):
        resp = self.client.get(reverse("ordering:order_detail", args=[str(self.order.order_date)]))
        content = resp.content.decode()
        self.assertIn('class="prep-sticky-actions"', content)
        self.assertIn('form="order-form"', content)
        sticky_html = content.split('class="prep-sticky-actions"')[1]
        self.assertIn("Save Draft", sticky_html)
        self.assertIn("Finalize Order", sticky_html)

    def test_finalized_order_shows_reopen_in_the_sticky_bar(self):
        services.finalize_order(self.order, self.user)
        resp = self.client.get(reverse("ordering:order_detail", args=[str(self.order.order_date)]))
        content = resp.content.decode()
        sticky_html = content.split('class="prep-sticky-actions"')[1]
        self.assertIn("Reopen for Editing", sticky_html)
        self.assertNotIn("Save Draft", sticky_html)

    def test_save_draft_still_works_from_outside_the_form_via_form_attribute(self):
        # End-to-end proof the form= association actually submits the
        # formset correctly now that the buttons live outside <form
        # id="order-form">.
        resp = self.client.post(
            reverse("ordering:order_detail", args=[str(self.order.order_date)]),
            {
                "action": "save",
                "form-TOTAL_FORMS": "1",
                "form-INITIAL_FORMS": "1",
                "form-MIN_NUM_FORMS": "0",
                "form-MAX_NUM_FORMS": "1000",
                "form-0-id": str(OrderListItem.objects.get(order_list=self.order).id),
                "form-0-quantity_text": "3 kg",
                "form-0-note": "",
            },
        )
        self.assertRedirects(resp, reverse("ordering:order_detail", args=[str(self.order.order_date)]))
        item = OrderListItem.objects.get(order_list=self.order)
        self.assertEqual(item.quantity_text, "3 kg")

    def test_reopen_from_the_sticky_bar_form_works(self):
        services.finalize_order(self.order, self.user)
        resp = self.client.post(
            reverse("ordering:order_detail", args=[str(self.order.order_date)]),
            {"action": "reopen"},
        )
        self.assertRedirects(resp, reverse("ordering:order_detail", args=[str(self.order.order_date)]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.state, OrderList.OrderState.DRAFT)

    def test_erase_stays_out_of_the_sticky_bar(self):
        resp = self.client.get(reverse("ordering:order_detail", args=[str(self.order.order_date)]))
        content = resp.content.decode()
        sticky_html = content.split('class="prep-sticky-actions"')[1]
        self.assertNotIn("Erase Order", sticky_html)
        self.assertIn("Erase Order", content)


class OrderListPaginationTests(TestCase):
    """
    Pre-launch performance audit: OrderListView loaded every historical
    order unbounded (no paginate_by, unlike PlanListView). After months of
    daily orders this becomes a steadily growing full-table load on every
    visit to Order Lists.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000220", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        for i in range(25):
            services.get_or_create_order(
                self.team, datetime.date(2026, 1, 1) + datetime.timedelta(days=i), self.user, blank=True
            )

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_order_list_is_paginated(self):
        resp = self.client.get(reverse("ordering:order_list"))
        self.assertEqual(len(resp.context["orders"]), 20)
        self.assertTrue(resp.context["is_paginated"])

        resp = self.client.get(reverse("ordering:order_list") + "?page=2")
        self.assertEqual(len(resp.context["orders"]), 5)


class CloneOrderResetsQuantitiesTests(TestCase):
    """
    Regression: clone_order_items used to copy quantity_text verbatim, so
    starting a new order "from" a previous one pre-filled every quantity
    with last time's number — easy to miss and leave stale, risking over-
    or under-ordering. The item list and notes are still worth keeping;
    only the quantity itself should come back blank for fresh input.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000230", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.onions = PurchaseItem.objects.create(team=self.team, name="Onions", category="Produce")
        self.source_order, _ = services.get_or_create_order(
            self.team, datetime.date(2026, 4, 1), self.user, blank=True
        )
        OrderListItem.objects.create(
            order_list=self.source_order,
            purchase_item=self.onions,
            quantity_text="5 kg",
            note="ask for the ripe ones",
            sort_order=1,
        )

    def test_cloned_item_keeps_name_and_note_but_blanks_quantity(self):
        target, _ = services.get_or_create_order(
            self.team, datetime.date(2026, 4, 2), self.user, source_order=self.source_order
        )
        cloned = OrderListItem.objects.get(order_list=target)
        self.assertEqual(cloned.purchase_item, self.onions)
        self.assertEqual(cloned.note, "ask for the ripe ones")
        self.assertEqual(cloned.quantity_text, "")

    def test_source_orders_own_quantity_is_untouched(self):
        services.get_or_create_order(
            self.team, datetime.date(2026, 4, 2), self.user, source_order=self.source_order
        )
        self.source_order.refresh_from_db()
        source_item = OrderListItem.objects.get(order_list=self.source_order)
        self.assertEqual(source_item.quantity_text, "5 kg")


class SupplierExportTests(TestCase):
    """
    PurchaseItem now has a supplier field so an order can be split per
    vendor instead of one undifferentiated sheet you have to re-sort by
    hand before sending to anyone.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000231", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.produce_item = PurchaseItem.objects.create(
            team=self.team, name="Onions", category="Produce", supplier="Jim's Produce"
        )
        self.meat_item = PurchaseItem.objects.create(
            team=self.team, name="Chicken", category="Protein", supplier="City Meats"
        )
        self.unassigned_item = PurchaseItem.objects.create(team=self.team, name="Napkins")

        self.order, _ = services.get_or_create_order(
            self.team, datetime.date(2026, 4, 5), self.user, blank=True
        )
        OrderListItem.objects.create(
            order_list=self.order, purchase_item=self.produce_item, quantity_text="5 kg", sort_order=1
        )
        OrderListItem.objects.create(
            order_list=self.order, purchase_item=self.meat_item, quantity_text="10 kg", sort_order=2
        )
        OrderListItem.objects.create(
            order_list=self.order, purchase_item=self.unassigned_item, quantity_text="2 boxes", sort_order=3
        )

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_export_creates_one_sheet_per_supplier(self):
        resp = self.client.get(reverse("ordering:order_export", args=[str(self.order.order_date)]))
        self.assertEqual(resp.status_code, 200)

        wb = load_workbook(io.BytesIO(resp.content))
        self.assertEqual(
            set(wb.sheetnames), {"Jim's Produce", "City Meats", "No Supplier Set"}
        )

    def test_each_sheet_only_lists_its_own_supplier_items(self):
        resp = self.client.get(reverse("ordering:order_export", args=[str(self.order.order_date)]))
        wb = load_workbook(io.BytesIO(resp.content))

        produce_ws = wb["Jim's Produce"]
        produce_values = [cell.value for row in produce_ws.iter_rows() for cell in row if cell.value]
        self.assertIn("Onions", produce_values)
        self.assertNotIn("Chicken", produce_values)
        self.assertNotIn("Napkins", produce_values)

    def test_single_supplier_order_still_exports_one_sheet(self):
        single_order, _ = services.get_or_create_order(
            self.team, datetime.date(2026, 4, 6), self.user, blank=True
        )
        OrderListItem.objects.create(
            order_list=single_order, purchase_item=self.produce_item, quantity_text="3 kg", sort_order=1
        )
        resp = self.client.get(reverse("ordering:order_export", args=[str(single_order.order_date)]))
        wb = load_workbook(io.BytesIO(resp.content))
        self.assertEqual(wb.sheetnames, ["Jim's Produce"])
