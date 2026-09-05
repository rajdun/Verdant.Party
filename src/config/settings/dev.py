from .base import *  # noqa: F401,F403

DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1']

# Klucz deweloperski — wyłącznie na lokalną bazę. Produkcja wymaga
# DJANGO_FIELD_ENCRYPTION_KEY z secret managera (patrz prod.py).
if not FIELD_ENCRYPTION_KEY:  # noqa: F405
    FIELD_ENCRYPTION_KEY = ['PhPoL0s_cvP8EhCUjw221arcfS-fzL_9UZNz-03Scc4=']

if not ALLEGRO.get('redirect_uri'):  # noqa: F405
    ALLEGRO['redirect_uri'] = 'http://localhost:8000/marketplaces/oauth/callback/'  # noqa: F405
