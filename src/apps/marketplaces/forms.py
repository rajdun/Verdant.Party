from django import forms

from apps.catalog.models import Product
from apps.marketplaces.models import Marketplace, MarketplaceListing


class MarketplaceForm(forms.ModelForm):
    class Meta:
        model = Marketplace
        fields = ["name", "type", "environment", "is_active", "notification_email"]
        labels = {
            "name": "Nazwa",
            "type": "Typ",
            "environment": "Środowisko",
            "is_active": "Aktywna",
            "notification_email": "E-mail do powiadomień o błędach",
        }
        help_texts = {
            "environment": "Sandbox i produkcja wymagają osobnych danych dostępowych.",
        }


class MarketplaceCredentialsForm(forms.Form):
    """Dane z panelu deweloperskiego Allegro — zapisywane zaszyfrowane."""

    client_id = forms.CharField(max_length=200, label="Client ID")
    client_secret = forms.CharField(
        max_length=200,
        label="Client Secret",
        widget=forms.PasswordInput(render_value=False),
        help_text="Zapisywany zaszyfrowany. Po zapisie nie jest nigdzie wyświetlany.",
    )

    def clean_client_id(self):
        return self.cleaned_data["client_id"].strip()

    def clean_client_secret(self):
        return self.cleaned_data["client_secret"].strip()


class MarketplaceListingForm(forms.ModelForm):
    class Meta:
        model = MarketplaceListing
        fields = ["product", "current_price", "currency", "status"]
        labels = {
            "product": "Produkt w katalogu",
            "current_price": "Cena na Allegro",
            "currency": "Waluta",
            "status": "Status",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(is_active=True)


class ListingMappingForm(forms.Form):
    """Mapowanie jednej oferty pobranej z Allegro na produkt."""

    external_id = forms.CharField(max_length=50, widget=forms.HiddenInput)
    title = forms.CharField(max_length=200, widget=forms.HiddenInput)
    picture_url = forms.CharField(max_length=500, required=False, widget=forms.HiddenInput)
    current_price = forms.DecimalField(max_digits=10, decimal_places=2, widget=forms.HiddenInput)
    currency = forms.CharField(max_length=3, widget=forms.HiddenInput)
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(), required=False, label="Produkt"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(is_active=True)
