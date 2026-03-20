from django import template

register = template.Library()

@register.filter
def splitlines(value: str):
    if not value:
        return []
    out = []
    for line in value.splitlines():
        s = line.strip()
        if s:
            out.append(s)
    return out