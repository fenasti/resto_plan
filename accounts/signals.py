from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import CookProfile

User = get_user_model()

@receiver(post_save, sender=User)
def ensure_profile_and_bootstrap_staff(sender, instance, created, **kwargs):
    """
    Creates CookProfile for every user.
    Bootstraps the first staff user automatically so you don't need Django admin.
    """
    if created:
        CookProfile.objects.create(user=instance)

        # Bootstrap: if no staff exists yet, make the first user staff
        if not User.objects.filter(is_staff=True).exists():
            instance.is_staff = True
            instance.save(update_fields=["is_staff"])
    else:
        CookProfile.objects.get_or_create(user=instance)