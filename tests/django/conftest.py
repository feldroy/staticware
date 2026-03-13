import django
from django.conf import settings


def pytest_configure() -> None:
    settings.configure(
        SECRET_KEY="staticware-test-key",
        INSTALLED_APPS=[
            "staticware.contrib.django",
        ],
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": True,
                "OPTIONS": {},
            },
        ],
    )
    django.setup()
