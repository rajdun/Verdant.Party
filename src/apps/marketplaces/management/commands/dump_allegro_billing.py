"""Podgląd surowych wpisów rozliczeniowych zamówienia.

Allegro nie publikuje pełnej listy identyfikatorów typów rozliczeniowych, a to
one decydują, który wpis jest opłatą za przesyłkę. Ta komenda pokazuje, co
naprawdę zwraca konto — na tej podstawie ustawia się
`ALLEGRO_SHIPPING_BILLING_TYPES`. Narzędzie diagnostyczne, nie dla crona.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.marketplaces.allegro.client import AllegroClient
from apps.marketplaces.allegro.oauth import ensure_access_token
from apps.marketplaces.allegro.shipping import is_shipping_entry
from apps.marketplaces.models import Marketplace, MarketplaceType
from apps.orders.models import Order


class Command(BaseCommand):
    help = "Wypisuje wpisy rozliczeniowe Allegro dla zamówienia (typ, nazwa, kwota)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--order", required=True, help="Identyfikator zamówienia w Allegro."
        )
        parser.add_argument(
            "--marketplace",
            type=int,
            help="ID integracji — domyślnie brana z zaimportowanego zamówienia.",
        )

    def handle(self, *args, **options):
        external_id = options["order"]
        marketplace = self._resolve_marketplace(external_id, options["marketplace"])

        ensure_access_token(marketplace)
        entries = AllegroClient(marketplace).get_billing_entries(external_id)

        if not entries:
            self.stdout.write(f"Brak wpisów rozliczeniowych dla {external_id}.")
            return

        self.stdout.write(f"{marketplace.name} — zamówienie {external_id}:")
        for entry in entries:
            entry_type = entry.get("type") or {}
            value = entry.get("value") or {}
            marker = "PRZESYŁKA" if is_shipping_entry(entry) else "         "
            line = (
                f"  {marker}  id={entry_type.get('id') or '-':<12} "
                f"{value.get('amount') or '-':>10} {value.get('currency') or ''} "
                f"— {entry_type.get('name') or '-'}"
            )
            self.stdout.write(line)

    def _resolve_marketplace(self, external_id, marketplace_id):
        if marketplace_id:
            try:
                return Marketplace.objects.get(pk=marketplace_id)
            except Marketplace.DoesNotExist as exc:
                raise CommandError(f"Nie ma integracji o ID {marketplace_id}.") from exc

        order = Order.objects.filter(external_order_id=external_id).first()
        if order:
            return order.marketplace

        marketplaces = list(
            Marketplace.objects.filter(type=MarketplaceType.ALLEGRO, is_active=True)
        )
        if len(marketplaces) != 1:
            raise CommandError(
                "Nie da się ustalić integracji — podaj --marketplace <id>."
            )
        return marketplaces[0]
