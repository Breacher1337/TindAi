"""Django settings for TindAI project.

Generated for TindAI mobile-first sari-sari store management.
"""

from pathlib import Path
import os
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

try:
    import dotenv
    dotenv.load_dotenv(BASE_DIR.parent / '.env')
    dotenv.load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-tindai-super-secret-key-change-in-prod')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in ('true', '1', 't')

ALLOWED_HOSTS = ['*']

# Application definition
INSTALLED_APPS = [
    'unfold',
    'unfold.contrib.filters',
    'unfold.contrib.forms',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'corsheaders',

    # Local apps
    'core',
]

import django.conf.locale

EXTRA_LANG_INFO = {
    'fil': {
        'bidi': False,
        'code': 'fil',
        'name': 'Filipino',
        'name_local': 'Filipino',
    },
    'tl': {
        'bidi': False,
        'code': 'tl',
        'name': 'Tagalog',
        'name_local': 'Tagalog',
    },
}
django.conf.locale.LANG_INFO.update(EXTRA_LANG_INFO)

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
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
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.i18n',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Database
# Using SQLite by default for zero-setup local dev
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        'OPTIONS': {
            'timeout': 20,
        },
    }
}

# Password validation
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
LANGUAGE_CODE = 'en'
TIME_ZONE = 'Asia/Manila'
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ('en', _('English')),
    ('fil', _('Filipino')),
    ('tl', _('Tagalog')),
]

LOCALE_PATHS = [
    BASE_DIR / 'locale',
]

# 1-year language preference cookie persistence
LANGUAGE_COOKIE_AGE = 60 * 60 * 24 * 365

LOGIN_URL = '/admin/login/'

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# CORS Headers Settings
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://localhost:[0-9]+$",
    r"^http://127\.0\.0\.1:[0-9]+$",
]

# Django Unfold Configuration
UNFOLD = {
    "SITE_TITLE": "TindAI Admin",
    "SITE_HEADER": "TindAI Sari-Sari Store Management",
    "SITE_SUBHEADER": "Store Administration & Inventory Control",
    "SITE_SYMBOL": "storefront",
    "THEME": "auto",
    "DASHBOARD_CALLBACK": "core.admin.dashboard_callback",
    "COLORS": {
        "primary": {
            "50": "#ecfdf5",
            "100": "#d1fae5",
            "200": "#a7f3d0",
            "300": "#6ee7b7",
            "400": "#34d399",
            "500": "#10b981",
            "600": "#059669",
            "700": "#047857",
            "800": "#065f46",
            "900": "#064e3b",
            "950": "#022c22",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": _("POS & Checkout"),
                "separator": True,
                "items": [
                    {
                        "title": _("Transactions"),
                        "icon": "receipt_long",
                        "link": reverse_lazy("admin:core_transaction_changelist"),
                    },
                ],
            },
            {
                "title": _("Inventory Control"),
                "separator": True,
                "items": [
                    {
                        "title": _("Products"),
                        "icon": "inventory_2",
                        "link": reverse_lazy("admin:core_product_changelist"),
                    },
                    {
                        "title": _("Restock Runs"),
                        "icon": "local_shipping",
                        "link": reverse_lazy("admin:core_restockrun_changelist"),
                    },
                ],
            },
            {
                "title": _("Credit & Utang Ledger"),
                "separator": True,
                "items": [
                    {
                        "title": _("Customers"),
                        "icon": "groups",
                        "link": reverse_lazy("admin:core_customer_changelist"),
                    },
                    {
                        "title": _("Utang Payments"),
                        "icon": "payments",
                        "link": reverse_lazy("admin:core_customerpayment_changelist"),
                    },
                ],
            },
            {
                "title": _("Access & System"),
                "separator": True,
                "items": [
                    {
                        "title": _("Users"),
                        "icon": "person",
                        "link": reverse_lazy("admin:auth_user_changelist"),
                    },
                    {
                        "title": _("Groups"),
                        "icon": "shield",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                    },
                    {
                        "title": _("Store Configuration"),
                        "icon": "settings",
                        "link": reverse_lazy("admin:core_storeconfig_changelist"),
                    },
                ],
            },
        ],
    },
}

# Google Gemini API Configuration
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')

DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760 # 10MB

