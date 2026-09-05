import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

DEBUG = False

ALLOWED_HOSTS = [h for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if h]

# Fail fast — bez klucza sekrety integracji zapisałyby się nieszyfrowane.
if not FIELD_ENCRYPTION_KEY:  # noqa: F405
    raise ImproperlyConfigured(
        'DJANGO_FIELD_ENCRYPTION_KEY jest wymagany na produkcji '
        '(wygeneruj: manage.py generate_encryption_key).'
    )
