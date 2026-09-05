"""Import zamówień z Allegro. Do uruchamiania z crona: */5 * * * *"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.utils import OperationalError

from apps.marketplaces.allegro.importer import fetch_events
from apps.marketplaces.models import Marketplace, MarketplaceType, SyncStatus


class Command(BaseCommand):
    help = "Pobiera nowe zamówienia z Allegro dla aktywnych integracji."

    def add_arguments(self, parser):
        parser.add_argument(
            "--marketplace", type=int, help="ID integracji — domyślnie wszystkie aktywne."
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Wypisz integracje do przetworzenia bez odpytywania Allegro.",
        )

    def handle(self, *args, **options):
        marketplaces = Marketplace.objects.filter(
            type=MarketplaceType.ALLEGRO, is_active=True
        )
        if options["marketplace"]:
            marketplaces = marketplaces.filter(pk=options["marketplace"])

        marketplaces = [m for m in marketplaces if m.has_credentials()]

        if not marketplaces:
            self.stdout.write("Brak aktywnych integracji z danymi dostępowymi.")
            return

        for marketplace in marketplaces:
            if options["dry_run"]:
                self.stdout.write(
                    f"[dry-run] {marketplace.name} "
                    f"(kursor: {marketplace.last_event_id or 'brak'})"
                )
                continue
            self._sync(marketplace)

    def _sync(self, marketplace):
        try:
            # Blokada wiersza chroni przed nakładaniem się przebiegów, gdy
            # poprzedni cron jeszcze pracuje.
            with transaction.atomic():
                locked = (
                    Marketplace.objects.select_for_update(nowait=True)
                    .get(pk=marketplace.pk)
                )
                run = fetch_events(locked)
        except OperationalError:
            self.stdout.write(
                self.style.WARNING(f"{marketplace.name}: synchronizacja już trwa — pomijam.")
            )
            return

        summary = (
            f"{marketplace.name}: zdarzeń {run.events_seen}, "
            f"zaimportowano {run.orders_imported}, pominięto {run.orders_skipped}"
        )
        if run.status == SyncStatus.OK:
            self.stdout.write(self.style.SUCCESS(summary))
        elif run.status == SyncStatus.PARTIAL:
            self.stdout.write(self.style.WARNING(f"{summary}\n{run.message}"))
        else:
            self.stdout.write(self.style.ERROR(f"{marketplace.name}: {run.message}"))
