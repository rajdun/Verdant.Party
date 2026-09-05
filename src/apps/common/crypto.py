"""Szyfrowanie danych wrażliwych at-rest.

Sekrety integracji (client_secret, tokeny OAuth) nigdy nie trafiają do bazy
jawnym tekstem — całość jest serializowana do JSON i szyfrowana Fernetem
(AES-128-CBC + HMAC) przed zapisem do kolumny tekstowej.

Klucz pochodzi z `settings.FIELD_ENCRYPTION_KEY` — pojedynczy klucz albo lista.
Przy liście używany jest `MultiFernet`: szyfruje zawsze pierwszy klucz,
odszyfrować potrafi każdy — dzięki temu rotacja klucza nie wymaga migracji
danych (stary klucz zostaje na końcu listy do czasu przepisania wierszy).
"""

import json

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


def get_fernet():
    """Zwraca instancję (Multi)Fernet zbudowaną z FIELD_ENCRYPTION_KEY."""
    keys = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
    if not keys:
        raise ImproperlyConfigured(
            "Brak FIELD_ENCRYPTION_KEY — ustaw zmienną środowiskową "
            "DJANGO_FIELD_ENCRYPTION_KEY (wygeneruj: manage.py generate_encryption_key)."
        )
    if isinstance(keys, (str, bytes)):
        keys = [keys]

    try:
        return MultiFernet([Fernet(key) for key in keys])
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured(f"Nieprawidłowy FIELD_ENCRYPTION_KEY: {exc}") from exc


class EncryptedJSONField(models.TextField):
    """Pole trzymające dowolną strukturę JSON zaszyfrowaną w kolumnie tekstowej.

    Świadomie `TextField`, nie `JSONField` — po zaszyfrowaniu zawartość jest
    nieprzezroczystym ciągiem znaków, więc filtrowanie/indeksowanie po kluczach
    JSON i tak nie działa. Nie da się po tym polu wyszukiwać w bazie.
    """

    description = "Zaszyfrowana struktura JSON"

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return None
        try:
            return json.loads(get_fernet().decrypt(value.encode()).decode())
        except InvalidToken as exc:
            raise ValueError(
                "Nie udało się odszyfrować danych — zmieniony lub brakujący "
                "FIELD_ENCRYPTION_KEY."
            ) from exc

    def to_python(self, value):
        # Wartość odszyfrowana (dict/list) albo już None — przechodzi bez zmian.
        if value is None or isinstance(value, (dict, list)):
            return value
        # Ciphertext trafiający tu np. z formularza — spróbuj odszyfrować.
        return self.from_db_value(value, None, None)

    def get_prep_value(self, value):
        if value is None:
            return None
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        return get_fernet().encrypt(payload.encode()).decode()

    def value_to_string(self, obj):
        # Serializacja (dumpdata) świadomie eksportuje ciphertext, nie sekrety.
        return self.value_from_object(obj) and self.get_prep_value(self.value_from_object(obj))
