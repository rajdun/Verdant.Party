import os

from .base import *  # noqa: F401,F403

DEBUG = False

ALLOWED_HOSTS = [h for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if h]
