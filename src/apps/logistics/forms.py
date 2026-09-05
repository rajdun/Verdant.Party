from django import forms

from apps.logistics.models import FulfillmentBatch


class FulfillmentBatchForm(forms.ModelForm):
    """Opis fali — same zamówienia wybierane są checkboxami poza formularzem."""

    class Meta:
        model = FulfillmentBatch
        fields = ["note"]
        labels = {"note": "Opis fali"}
        widgets = {
            "note": forms.TextInput(attrs={"placeholder": "np. wysyłka poranna"}),
        }


class ShippingCostForm(forms.Form):
    shipping_cost = forms.DecimalField(
        label="Koszt wysyłki (zł)",
        min_value=0,
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
    )
