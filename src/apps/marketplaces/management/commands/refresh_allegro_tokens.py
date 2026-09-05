"""Odświeżanie tokenów Allegro. Do uruchamiania z crona: */30 * * * *"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.marketplaces.allegro.oauth import refresh_token
from apps.marketplaces.models import (
    Marketplace,
    MarketplaceType,
    SyncKind,
    SyncRun,
    SyncStatus,
)


class Command(BaseCommand):
    help = "Odświeża tokeny Allegro wygasające w ciągu najbliższych 2 godzin."

    def add_arguments(self, parser):
        parser.add_argument(
            "--marketplace", type=int, help="ID integracji — domyślnie wszystkie aktywne."
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Wypisz integracje wymagające odświeżenia bez wywoływania Allegro.",
        )

    def handle(self, *args, **options):
        marketplaces = Marketplace.objects.filter(
            type=MarketplaceType.ALLEGRO, is_active=True
        )
        if options["marketplace"]:
            marketplaces = marketplaces.filter(pk=options["marketplace"])

        # Termin wygaśnięcia siedzi w zaszyfrowanej kolumnie, więc filtrujemy w Pythonie.
        due = [m for m in marketplaces if m.has_credentials() and m.needs_token_refresh()]

        if not due:
            self.stdout.write("Żadna integracja nie wymaga odświeżenia tokenu.")
            return

        for marketplace in due:
            if options["dry_run"]:
                expires = marketplace.access_token_expires_at
                self.stdout.write(
                    f"[dry-run] {marketplace.name} (wygasa: {expires or 'brak tokenu'})"
                )
                continue
            self._refresh(marketplace)

    def _refresh(self, marketplace):
        run = SyncRun.objects.create(marketplace=marketplace, kind=SyncKind.TOKEN_REFRESH)
        try:
            refresh_token(marketplace)
        except Exception as exc:  # noqa: BLE001 — awaria jednej integracji nie blokuje reszty
            run.finish(SyncStatus.FAILED, str(exc))
            self.stdout.write(self.style.ERROR(f"{marketplace.name}: {exc}"))
            return

        expires = marketplace.access_token_expires_at
        run.finish(SyncStatus.OK, f"Token ważny do {expires:%Y-%m-%d %H:%M}.")
        self.stdout.write(
            self.style.SUCCESS(
                f"{marketplace.name}: token odświeżony "
                f"(ważny {timezone.localtime(expires):%Y-%m-%d %H:%M})"
            )
        )
