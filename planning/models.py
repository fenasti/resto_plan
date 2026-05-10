from django.conf import settings
from django.db import models
from accounts.models import Team
from menu.models import Dish, DishComponent

class PrepPlan(models.Model):
    class PlanState(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PRODUCTION = "PRODUCTION", "Production"

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="plans")
    service_date = models.DateField()
    state = models.CharField(max_length=20, choices=PlanState.choices, default=PlanState.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="plans_created")
    created_at = models.DateTimeField(auto_now_add=True)
    finalized_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="plans_finalized")
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "service_date"], name="uniq_team_plan_date")
        ]
        ordering = ["-service_date"]

    def __str__(self):
        return f"{self.team.name} {self.service_date} ({self.state})"

    @property
    def task_total(self) -> int:
        if hasattr(self, "_task_total"):
            return self._task_total
        if hasattr(self, "task_total_count"):
            return self.task_total_count
        return self.tasks.count()

    @property
    def task_done(self) -> int:
        if hasattr(self, "_task_done"):
            return self._task_done
        if hasattr(self, "task_done_count"):
            return self.task_done_count
        return self.tasks.filter(status=PrepTask.TaskStatus.DONE).count()

    @property
    def progress_percent(self) -> int:
        total = self.task_total
        if total == 0:
            return 0
        return round((self.task_done / total) * 100)

    @property
    def is_complete(self) -> bool:
        return self.task_total > 0 and self.task_done == self.task_total


class PlanDish(models.Model):
    plan = models.ForeignKey(PrepPlan, on_delete=models.CASCADE, related_name="plan_dishes")
    dish = models.ForeignKey(Dish, on_delete=models.PROTECT)
    order = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["plan", "dish"], name="uniq_plan_dish")
        ]
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.plan.service_date} -> {self.dish.name}"


class PrepTask(models.Model):
    class TaskStatus(models.TextChoices):
        NONE = "NONE", "None"
        PLANNED = "PLANNED", "Planned"
        DONE = "DONE", "Done"

    plan = models.ForeignKey(PrepPlan, on_delete=models.CASCADE, related_name="tasks")
    dish_component = models.ForeignKey(DishComponent, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=TaskStatus.choices, default=TaskStatus.NONE)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    daily_note = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["plan", "dish_component"], name="uniq_plan_dishcomponent_task")
        ]
        indexes = [
            models.Index(fields=["plan", "status"]),
        ]

    def __str__(self):
        return f"{self.plan.service_date}: {self.dish_component.component.name} ({self.status})"
