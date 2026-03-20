import secrets
from django.conf import settings
from django.db import models

class Team(models.Model):
    name = models.CharField(max_length=200, unique=True)
    join_code = models.CharField(max_length=12, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="teams_created")
    created_at = models.DateTimeField(auto_now_add=True)

    def rotate_join_code(self) -> None:
        self.join_code = Team.generate_join_code()
        self.save(update_fields=["join_code"])

    @staticmethod
    def generate_join_code() -> str:
        # 6-digit numeric code, kitchen-friendly
        return f"{secrets.randbelow(1_000_000):06d}"

    def __str__(self):
        return self.name


class TeamMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        ADMIN = "ADMIN", "Admin"
        MEMBER = "MEMBER", "Member"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    # Fine-grained permissions (what you asked for)
    can_manage_menu = models.BooleanField(default=False)     # dishes/components/dishcomponents
    can_manage_recipes = models.BooleanField(default=False)  # recipes CRUD
    can_manage_team = models.BooleanField(default=False)     # member roles, rotate code, etc.

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "team"], name="uniq_user_team_membership")
        ]

    def __str__(self):
        return f"{self.user} in {self.team} ({self.role})"


class CookProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cookprofile")
    avatar = models.ImageField(blank=True, null=True)
    display_name = models.CharField(max_length=150, blank=True)

    def __str__(self):
        return self.display_name or self.user.username