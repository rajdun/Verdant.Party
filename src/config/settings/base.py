"""
Base Django settings for config project.

Shared by dev.py and prod.py. Nothing environment-specific lives here.
"""

import os
from pathlib import Path

# src/config/settings/base.py -> src/
BASE_DIR = Path(__file__).resolve().parent.parent.parent


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-9^w0@22$!z!0wb&yxaq&_d$v%cgb_wc(x$fcdbqsc9yagm1q4r')

DEBUG = False

ALLOWED_HOSTS = []


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Verdant domain apps
    'apps.common',
    'apps.catalog',
    'apps.inventory',
    'apps.orders',
    'apps.users',
    'apps.finance',
    'apps.logistics',
    'apps.marketplaces',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'verdant'),
        'USER': os.environ.get('POSTGRES_USER', 'verdant'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'verdant'),
        'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
    }
}


# Custom user model (apps/users)

AUTH_USER_MODEL = 'users.User'

LOGIN_URL = 'users:login'
LOGIN_REDIRECT_URL = 'catalog:product_list'
LOGOUT_REDIRECT_URL = 'users:login'


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'pl'

TIME_ZONE = 'Europe/Warsaw'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'


# Email
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

DEFAULT_FROM_EMAIL = os.environ.get('DJANGO_DEFAULT_FROM_EMAIL', 'noreply@verdant.party')

# Adres, na który idą powiadomienia o błędach importu, gdy integracja
# nie ma własnego notification_email.
ADMIN_NOTIFICATION_EMAIL = os.environ.get('DJANGO_ADMIN_NOTIFICATION_EMAIL', '')


# Szyfrowanie danych wrażliwych at-rest (apps.common.crypto)
# Wygeneruj klucz: python manage.py generate_encryption_key
# Rotacja: podaj klucze po przecinku, nowy jako pierwszy.

FIELD_ENCRYPTION_KEY = [
    key.strip()
    for key in os.environ.get('DJANGO_FIELD_ENCRYPTION_KEY', '').split(',')
    if key.strip()
]


# Integracja Allegro (apps.marketplaces.allegro)
# Sandbox i produkcja różnią się wyłącznie adresami — client_id/secret siedzą
# per integracja w bazie, tutaj tylko stałe wspólne dla całego systemu.

ALLEGRO = {
    'sandbox': {
        'base_url': 'https://allegro.pl.allegrosandbox.pl',
        'api_base_url': 'https://api.allegro.pl.allegrosandbox.pl',
    },
    'production': {
        'base_url': 'https://allegro.pl',
        'api_base_url': 'https://api.allegro.pl',
    },
    'app_name': 'Verdant.Party',
    'rate_limit_per_minute': int(os.environ.get('ALLEGRO_RATE_LIMIT_PER_MINUTE', '1000')),
    'rate_limit_window_seconds': int(os.environ.get('ALLEGRO_RATE_LIMIT_WINDOW_SECONDS', '60')),
    'timeout_seconds': int(os.environ.get('ALLEGRO_TIMEOUT_SECONDS', '30')),
    # Musi być identyczne w kroku authorize i token exchange oraz zarejestrowane
    # w panelu deweloperskim Allegro — osobno dla sandboxa i produkcji.
    'redirect_uri': os.environ.get('ALLEGRO_REDIRECT_URI', ''),
    # Identyfikatory typów wpisów rozliczeniowych oznaczających opłatę za
    # przesyłkę (Allegro Delivery). Konfigurowalne, bo Allegro dokłada nowe typy
    # bez zapowiedzi — właściwe ID dla konta sprawdzisz komendą
    # `manage.py dump_allegro_billing --order <id>`. Gdy żaden nie pasuje,
    # `allegro/shipping.py` próbuje jeszcze dopasowania po nazwie typu.
    'shipping_billing_types': [
        code.strip()
        for code in os.environ.get(
            'ALLEGRO_SHIPPING_BILLING_TYPES',
            'SUC,SUC_COR,DEL,DEL_COR',
        ).split(',')
        if code.strip()
    ],
}


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
