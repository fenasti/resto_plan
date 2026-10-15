from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import CookProfile, PlatformBootstrap

User = get_user_model()

@receiver(post_save, sender=User)
def ensure_profile_and_bootstrap_staff(sender, instance, created, **kwargs):
    """
    Creates CookProfile for every user.
    Bootstraps the very first user ever created as staff, exactly once, so
    you don't need Django admin just to get started. See PlatformBootstrap's
    docstring for why this can't simply check "no staff exists right now".
    """
    if created:
        CookProfile.objects.create(user=instance)

        try:
            with transaction.atomic():
                PlatformBootstrap.objects.create(pk=1)
        except IntegrityError:
            pass  # Already bootstrapped, ever — never re-arm.
        else:
            instance.is_staff = True
            instance.save(update_fields=["is_staff"])
    else:
        CookProfile.objects.get_or_create(user=instance)