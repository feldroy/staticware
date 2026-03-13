from django.apps import AppConfig


class StaticwareDjangoConfig(AppConfig):
    name = "staticware.contrib.django"
    label = "staticware_django"
    verbose_name = "Staticware"
    default_auto_field = "django.db.models.BigAutoField"
