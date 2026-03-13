from django import template

from staticware.contrib.django import get_static

register = template.Library()


@register.simple_tag
def hashed_static(path):
    return get_static().url(path)
