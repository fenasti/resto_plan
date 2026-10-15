from django.db import migrations


def backfill_bootstrap_marker(apps, schema_editor):
    """
    If a staff user already exists, the one-time bootstrap already happened
    in the past under the old (reusable) signal logic. Mark it done so the
    new signal can't treat the next signup as a fresh "first ever" user —
    which, without this backfill, it would: the new PlatformBootstrap row
    doesn't exist yet on an existing deployment, even though a real admin
    was already bootstrapped long ago.
    """
    User = apps.get_model("auth", "User")
    PlatformBootstrap = apps.get_model("accounts", "PlatformBootstrap")
    if User.objects.filter(is_staff=True).exists():
        PlatformBootstrap.objects.get_or_create(pk=1)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_platformbootstrap"),
    ]

    operations = [
        migrations.RunPython(backfill_bootstrap_marker, migrations.RunPython.noop),
    ]
