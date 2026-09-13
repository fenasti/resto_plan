from django import template

register = template.Library()


@register.filter(name="add_class")
def add_class(field, css_class):
    """Render a bound field with extra CSS class(es) merged onto its widget."""
    if not hasattr(field, "as_widget"):
        return field
    existing = field.field.widget.attrs.get("class", "")
    classes = f"{existing} {css_class}".strip()
    return field.as_widget(attrs={"class": classes})


@register.filter(name="widget_type")
def widget_type(field):
    if not hasattr(field, "field"):
        return ""
    return field.field.widget.__class__.__name__.lower()


@register.filter(name="button_classes")
def button_classes(tags):
    tags = tags or []
    classes = ["btn"]
    if "danger" in tags:
        classes.append("btn-danger")
    elif "outline" in tags and "primary" in tags:
        classes.append("btn-outline-primary")
    elif "outline" in tags:
        classes.append("btn-outline-secondary")
    elif "primary" in tags or "prominent" in tags:
        classes.append("btn-primary")
    elif "secondary" in tags or "minor" in tags:
        classes.append("btn-secondary")
    elif "link" in tags:
        classes.append("btn-link")
    else:
        classes.append("btn-primary")
    if "prominent" in tags:
        classes.append("w-100")
    if "panel" in tags:
        classes.append("btn-sm")
    return " ".join(classes)


@register.filter(name="badge_classes")
def badge_classes(tags):
    tags = tags or []
    classes = ["badge"]
    if "success" in tags:
        classes.append("text-bg-success")
    elif "warning" in tags:
        classes.append("text-bg-warning")
    elif "danger" in tags:
        classes.append("text-bg-danger")
    elif "primary" in tags:
        classes.append("text-bg-primary")
    else:
        classes.append("text-bg-secondary")
    return " ".join(classes)
