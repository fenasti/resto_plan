import secrets
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

MAX_AVATAR_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


def validate_avatar_size(value):
    if value.size > MAX_AVATAR_SIZE_BYTES:
        raise ValidationError("Image file too large. Max size is 5MB.")

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

    # Every member can do everything by default (horizontal kitchen
    # workflow). These flags exist to let an OWNER/ADMIN restrict a
    # specific person later, not to lock things down by default.
    can_manage_menu = models.BooleanField(default=True)      # dishes/components/dishcomponents
    can_manage_recipes = models.BooleanField(default=True)   # recipes CRUD
    can_manage_team = models.BooleanField(default=False)     # member roles, rotate code, etc.

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "team"], name="uniq_user_team_membership")
        ]

    @property
    def is_team_admin(self) -> bool:
        """High rank within this team: manage members, roles, and the join code."""
        return self.can_manage_team or self.role != self.Role.MEMBER

    @property
    def can_edit_menu(self) -> bool:
        """The can_manage_menu flag, or being OWNER/ADMIN (same fallback as can_manage_team)."""
        return self.can_manage_menu or self.role != self.Role.MEMBER

    def __str__(self):
        return f"{self.user} in {self.team} ({self.role})"


class CookProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cookprofile")
    avatar = models.ImageField(blank=True, null=True, validators=[validate_avatar_size])
    display_name = models.CharField(max_length=150, blank=True)

    def __str__(self):
        return self.display_name or self.user.username