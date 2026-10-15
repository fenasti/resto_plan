import datetime
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from accounts.models import Team, TeamMembership
from ordering.models import OrderList, OrderListItem, PurchaseCategory, PurchaseItem, Supplier
from ordering import forms as ordering_forms
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

        self.category = PurchaseCategory.objects.create(team=self.team, name="Produce")
        self.purchase_item = PurchaseItem.objects.create(team=self.team, name="Onions", category=self.category)
        self.order, _, _ = services.get_or_create_order(
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

        self.category = PurchaseCategory.objects.create(team=self.team, name="Produce")
        self.onions = PurchaseItem.objects.create(team=self.team, name="Onions", category=self.category)
        self.source_order, _, _ = services.get_or_create_order(
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
        target, _, _ = services.get_or_create_order(
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


class CloneIntoAlreadyExistingTargetOrderTests(TestCase):
    """
    Reported bug: clicking "Create from This" on an old order, when
    today's order already exists (even as an empty shell — e.g. from an
    earlier "Start Blank Order" visit), did nothing. get_or_create_order's
    clone only ran on created=True, so an already-existing target order
    was returned completely untouched and the user just landed on
    whatever today's order already was, with no indication the clone
    hadn't happened.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000232", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)
        self.category = PurchaseCategory.objects.create(team=self.team, name="Produce")
        self.onions = PurchaseItem.objects.create(team=self.team, name="Onions", category=self.category)

        self.source_order, _, _ = services.get_or_create_order(
            self.team, datetime.date(2026, 5, 1), self.user, blank=True
        )
        OrderListItem.objects.create(order_list=self.source_order, purchase_item=self.onions, sort_order=1)

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_service_clones_into_a_target_that_already_exists_but_is_empty(self):
        # First visit starts a blank order for that day (e.g. "Start Blank
        # Order"); the second call is the later "Create from This" attempt
        # against that same, still-empty, already-existing day.
        target, created, _ = services.get_or_create_order(
            self.team, datetime.date(2026, 5, 2), self.user, blank=True
        )
        self.assertTrue(created)

        target, created, cloned = services.get_or_create_order(
            self.team, datetime.date(2026, 5, 2), self.user, source_order=self.source_order
        )
        self.assertFalse(created)
        self.assertTrue(cloned, "an existing-but-empty draft should still be eligible for cloning")
        self.assertEqual(target.items.count(), 1)

    def test_service_does_not_clone_into_a_target_that_already_has_items(self):
        target, _, _ = services.get_or_create_order(
            self.team, datetime.date(2026, 5, 3), self.user, blank=True
        )
        OrderListItem.objects.create(order_list=target, purchase_item=self.onions, quantity_text="2 kg", sort_order=1)

        target, created, cloned = services.get_or_create_order(
            self.team, datetime.date(2026, 5, 3), self.user, source_order=self.source_order
        )
        self.assertFalse(cloned)
        self.assertEqual(target.items.count(), 1)
        self.assertEqual(target.items.first().quantity_text, "2 kg")  # untouched, not merged/duplicated

    def test_create_from_this_view_clones_into_an_already_started_blank_order(self):
        # The exact reported scenario: today's order already exists (blank
        # draft, started earlier), then "Create from This" is clicked on
        # an older order.
        today = timezone.localdate()
        services.get_or_create_order(self.team, today, self.user, blank=True)

        resp = self.client.post(
            reverse("ordering:order_clone", args=[str(self.source_order.order_date)])
        )
        self.assertRedirects(resp, reverse("ordering:order_detail", args=[str(today)]))

        today_order = OrderList.objects.get(team=self.team, order_date=today)
        self.assertEqual(today_order.items.count(), 1)
        self.assertEqual(today_order.items.first().purchase_item, self.onions)

    def test_create_from_this_view_warns_instead_of_silently_doing_nothing(self):
        today = timezone.localdate()
        target, _, _ = services.get_or_create_order(self.team, today, self.user, blank=True)
        OrderListItem.objects.create(order_list=target, purchase_item=self.onions, quantity_text="2 kg", sort_order=1)

        resp = self.client.post(
            reverse("ordering:order_clone", args=[str(self.source_order.order_date)]), follow=True
        )
        messages = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any("nothing was cloned" in m for m in messages))
        target.refresh_from_db()
        self.assertEqual(target.items.count(), 1)  # unchanged, not duplicated


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

        self.produce_category = PurchaseCategory.objects.create(team=self.team, name="Produce")
        self.protein_category = PurchaseCategory.objects.create(team=self.team, name="Protein")
        self.jims_produce = Supplier.objects.create(team=self.team, name="Jim's Produce")
        self.city_meats = Supplier.objects.create(team=self.team, name="City Meats")

        self.produce_item = PurchaseItem.objects.create(
            team=self.team, name="Onions", category=self.produce_category, supplier=self.jims_produce
        )
        self.meat_item = PurchaseItem.objects.create(
            team=self.team, name="Chicken", category=self.protein_category, supplier=self.city_meats
        )
        self.unassigned_item = PurchaseItem.objects.create(team=self.team, name="Napkins")

        self.order, _, _ = services.get_or_create_order(
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
        single_order, _, _ = services.get_or_create_order(
            self.team, datetime.date(2026, 4, 6), self.user, blank=True
        )
        OrderListItem.objects.create(
            order_list=single_order, purchase_item=self.produce_item, quantity_text="3 kg", sort_order=1
        )
        resp = self.client.get(reverse("ordering:order_export", args=[str(single_order.order_date)]))
        wb = load_workbook(io.BytesIO(resp.content))
        self.assertEqual(wb.sheetnames, ["Jim's Produce"])


class OrderingSetupTests(TestCase):
    """Create/delete for Suppliers and Categories — the entities the
    supplier-first Add Item flow and the per-supplier export are organized
    around. Deleting one unassigns it from items (SET_NULL) rather than
    being blocked or cascading."""

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000240", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_create_supplier(self):
        resp = self.client.post(reverse("ordering:ordering_setup"), {
            "action": "add_supplier", "name": "Jim's Produce",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Supplier.objects.filter(team=self.team, name="Jim's Produce").exists())

    def test_create_duplicate_supplier_case_insensitive_shows_error_not_duplicate(self):
        Supplier.objects.create(team=self.team, name="Jim's Produce")
        resp = self.client.post(reverse("ordering:ordering_setup"), {
            "action": "add_supplier", "name": "jim's produce",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already exists")
        self.assertEqual(Supplier.objects.filter(team=self.team).count(), 1)

    def test_delete_supplier_unassigns_rather_than_blocks(self):
        supplier = Supplier.objects.create(team=self.team, name="Jim's Produce")
        item = PurchaseItem.objects.create(team=self.team, name="Onions", supplier=supplier)

        resp = self.client.post(reverse("ordering:ordering_setup"), {
            "action": "delete_supplier", "supplier_id": supplier.id,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Supplier.objects.filter(id=supplier.id).exists())
        item.refresh_from_db()
        self.assertIsNone(item.supplier_id)

    def test_create_category(self):
        resp = self.client.post(reverse("ordering:ordering_setup"), {
            "action": "add_category", "name": "Produce",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(PurchaseCategory.objects.filter(team=self.team, name="Produce").exists())

    def test_delete_category_unassigns_rather_than_blocks(self):
        category = PurchaseCategory.objects.create(team=self.team, name="Produce")
        item = PurchaseItem.objects.create(team=self.team, name="Onions", category=category)

        resp = self.client.post(reverse("ordering:ordering_setup"), {
            "action": "delete_category", "category_id": category.id,
        })
        self.assertEqual(resp.status_code, 302)
        item.refresh_from_db()
        self.assertIsNone(item.category_id)

    def test_setup_page_lists_existing_suppliers_and_categories(self):
        Supplier.objects.create(team=self.team, name="Jim's Produce")
        PurchaseCategory.objects.create(team=self.team, name="Produce")
        resp = self.client.get(reverse("ordering:ordering_setup"))
        self.assertContains(resp, "Jim&#x27;s Produce")
        self.assertContains(resp, "Produce")


class ConcurrentDuplicateSupplierCreateTests(TransactionTestCase):
    """
    Unlike test_create_duplicate_supplier_case_insensitive_shows_error_not_duplicate
    above (which exercises the normal clean_name() pre-check), this
    simulates the actual race: two near-simultaneous submits of the same
    new supplier name, where the pre-check passes for both and only the
    DB's real UniqueConstraint catches the second save(). Uses
    TransactionTestCase — see ConcurrentDuplicateNameCreateTests in
    menu/tests.py for why plain TestCase can't be used here.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000241", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)
        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_create_supplier_race_shows_error_instead_of_500(self):
        Supplier.objects.create(team=self.team, name="Jim's Produce")
        with patch.object(ordering_forms.SupplierForm, "clean_name", lambda self: self.cleaned_data["name"]):
            resp = self.client.post(reverse("ordering:ordering_setup"), {
                "action": "add_supplier", "name": "Jim's Produce",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already exists")
        self.assertEqual(Supplier.objects.filter(team=self.team).count(), 1)


class CreateNewItemAttachesSupplierTests(TestCase):
    """
    Regression: the "Create New Catalog Item" form used to accept a
    supplier but silently never save it — create_purchase_item_and_add_to_
    order never read it from cleaned_data. Matters a lot for the new
    supplier-scoped Add Item flow specifically: Step 2 locks the form's
    supplier to whichever one you picked in Step 1, so if this plumbing
    gap weren't fixed, every item created there would still land
    unassigned despite looking scoped.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000241", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.supplier = Supplier.objects.create(team=self.team, name="Jim's Produce")
        self.category = PurchaseCategory.objects.create(team=self.team, name="Produce")
        self.order, _, _ = services.get_or_create_order(
            self.team, datetime.date(2026, 5, 1), self.user, blank=True
        )

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_created_item_is_attached_to_the_selected_supplier(self):
        url = reverse("ordering:order_detail", args=[str(self.order.order_date)]) + f"?supplier={self.supplier.id}"
        resp = self.client.post(url, {
            "action": "add_new",
            "name": "Onions",
            "category": self.category.id,
            "default_unit": "kg",
        })
        self.assertEqual(resp.status_code, 302)
        item = PurchaseItem.objects.get(team=self.team, name="Onions")
        self.assertEqual(item.supplier_id, self.supplier.id)
        self.assertEqual(item.category_id, self.category.id)


class SupplierFirstAddItemFlowTests(TestCase):
    """
    Regression for the core UX complaint: Add Item used to show one flat
    dropdown mixing every supplier's items together with no guidance. Now
    it's two steps — pick a supplier first, then a form scoped to that
    supplier — and the choice must survive redirects/re-renders so adding
    several items doesn't mean re-picking the supplier every time.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000242", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.jims = Supplier.objects.create(team=self.team, name="Jim's Produce")
        self.citymeats = Supplier.objects.create(team=self.team, name="City Meats")
        self.onions = PurchaseItem.objects.create(team=self.team, name="Onions", supplier=self.jims)
        self.chicken = PurchaseItem.objects.create(team=self.team, name="Chicken", supplier=self.citymeats)

        self.order, _, _ = services.get_or_create_order(
            self.team, datetime.date(2026, 5, 2), self.user, blank=True
        )
        self.detail_url = reverse("ordering:order_detail", args=[str(self.order.order_date)])

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_no_supplier_param_shows_the_picker_not_a_blind_form(self):
        resp = self.client.get(self.detail_url)
        self.assertContains(resp, "Jim&#x27;s Produce")
        self.assertContains(resp, "City Meats")
        self.assertNotContains(resp, 'value="add_existing"')
        self.assertNotContains(resp, 'value="add_new"')

    def test_zero_suppliers_shows_a_link_to_setup_not_a_blind_form(self):
        self.jims.delete()
        self.citymeats.delete()
        resp = self.client.get(self.detail_url)
        self.assertContains(resp, reverse("ordering:ordering_setup"))
        self.assertNotContains(resp, 'value="add_existing"')

    def test_supplier_param_scopes_the_existing_item_dropdown(self):
        resp = self.client.get(self.detail_url + f"?supplier={self.jims.id}")
        content = resp.content.decode()
        self.assertIn("Onions", content)
        # The dropdown's <option> for Chicken shouldn't appear, though the
        # name could theoretically appear elsewhere — scope the check to
        # the actual <select> options via the form's queryset instead.
        self.assertNotIn(
            str(self.chicken.id),
            [str(o.pk) for o in resp.context["add_existing_form"].fields["purchase_item"].queryset],
        )

    def test_add_existing_without_a_supplier_selected_is_rejected(self):
        resp = self.client.post(self.detail_url, {"action": "add_existing", "purchase_item": self.onions.id})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, self.detail_url)
        self.assertFalse(OrderListItem.objects.filter(order_list=self.order).exists())

    def test_successful_add_redirect_preserves_the_supplier_param(self):
        url = self.detail_url + f"?supplier={self.jims.id}"
        resp = self.client.post(url, {"action": "add_existing", "purchase_item": self.onions.id})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, url)

    def test_failed_create_rerender_keeps_the_selected_supplier_context(self):
        url = self.detail_url + f"?supplier={self.jims.id}"
        # Empty name fails QuickCreatePurchaseItemForm validation.
        resp = self.client.post(url, {"action": "add_new", "name": "", "category": "", "default_unit": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Jim&#x27;s Produce")


class OrderTableGroupedBySupplierTests(TestCase):
    """The on-screen Order Table now groups by supplier first, then
    category — matching export_order_excel's per-supplier-sheet structure
    exactly, so what you see while building the list is what each vendor
    gets sent."""

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000243", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.jims = Supplier.objects.create(team=self.team, name="Jim's Produce")
        self.produce = PurchaseCategory.objects.create(team=self.team, name="Produce")
        self.onions = PurchaseItem.objects.create(
            team=self.team, name="Onions", supplier=self.jims, category=self.produce
        )

        self.order, _, _ = services.get_or_create_order(
            self.team, datetime.date(2026, 5, 3), self.user, blank=True
        )
        OrderListItem.objects.create(order_list=self.order, purchase_item=self.onions, sort_order=1)

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_table_shows_supplier_section_header(self):
        resp = self.client.get(reverse("ordering:order_detail", args=[str(self.order.order_date)]))
        self.assertContains(resp, "order-supplier-header")
        self.assertContains(resp, "Jim&#x27;s Produce")
