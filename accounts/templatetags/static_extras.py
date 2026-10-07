import os

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def static_v(path):
    """
    Like {% static %}, but appends ?v=<mtime> in DEBUG so a browser never
    serves a stale cached copy of a file that just changed on disk. In
    production, WhiteNoise's ManifestStaticFilesStorage already bakes a
    content hash into the filename itself, so this is a no-op there —
    busting is already handled at the URL level.
    """
    url = static(path)
    if settings.DEBUG:
        found = finders.find(path)
        if found:
            try:
                url = f"{url}?v={int(os.path.getmtime(found))}"
            except OSError:
                pass
    return url
