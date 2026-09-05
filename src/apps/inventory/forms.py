from django import forms

from apps.inventory.models import Location, StockBatch


class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ["name", "code", "description", "is_active"]
        labels = {
            "name": "Nazwa",
            "code": "Kod",
            "description": "Opis",
            "is_active": "Aktywna",
        }


class StockBatchForm(forms.ModelForm):
    """Formularz przyjęcia. Na tworzeniu ilość pozostała = przyjęta (ustawiane w widoku),
    na edycji pole jest dostępne jako korekta stanu."""

    class Meta:
        model = StockBatch
        fields = [
            "product",
            "location",
            "quantity_received",
            "quantity_remaining",
            "unit_cost",
            "received_at",
            "supplier_name",
            "document_reference",
            "note",
        ]
        widgets = {
            "received_at": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {
            "product": "Towar",
            "location": "Lokalizacja",
            "quantity_received": "Przyjęta ilość",
            "quantity_remaining": "Ilość pozostała (korekta)",
            "unit_cost": "Cena zakupu za sztukę (zł)",
            "received_at": "Data przyjęcia",
            "supplier_name": "Dostawca",
            "document_reference": "Dokument / faktura",
            "note": "Notatka",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.objects.filter(is_active=True)
        if self.instance.pk is None or self.instance.is_locked:
            del self.fields["quantity_remaining"]


class StockBatchRelocateForm(forms.Form):
    location = forms.ModelChoiceField(queryset=Location.objects.none(), label="Nowa lokalizacja")
    quantity = forms.IntegerField(min_value=1, label="Ilość do przeniesienia")

    def __init__(self, *args, source=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.source = source
        self.fields["location"].queryset = Location.objects.filter(is_active=True).exclude(
            pk=source.location_id
        )
        self.fields["quantity"].initial = source.quantity_remaining

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity > self.source.quantity_remaining:
            raise forms.ValidationError(
                "Ilość do przeniesienia nie może przekraczać ilości pozostałej w partii."
            )
        return quantity
