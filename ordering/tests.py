import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

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
