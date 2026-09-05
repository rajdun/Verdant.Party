from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Generuje klucz do DJANGO_FIELD_ENCRYPTION_KEY (szyfrowanie sekretów at-rest)."

    def handle(self, *args, **options):
        key = Fernet.generate_key().decode()
        self.stdout.write(f"DJANGO_FIELD_ENCRYPTION_KEY={key}")
        self.stdout.write(
            self.style.WARNING(
                "Zapisz klucz w secret managerze. Jego utrata = brak dostępu do "
                "zapisanych danych dostępowych integracji."
            )
        )
