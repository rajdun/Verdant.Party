from django import forms

from apps.catalog.models import Product, ProductImage


class ProductForm(forms.ModelForm):
    plant_fields = ["species", "latin_name", "genus", "variety", "pot_size", "low_stock_threshold"]
    material_fields = ["length", "width", "height", "dimension_unit", "material_unit"]

    class Meta:
        model = Product
        fields = [
            "sku", "name", "item_type", "is_active", "price",
            "species", "latin_name", "genus", "variety", "pot_size", "low_stock_threshold",
            "length", "width", "height", "dimension_unit", "material_unit",
        ]
        widgets = {
            "item_type": forms.Select(attrs={"data-type-toggle": "item_type"}),
        }
        labels = {
            "sku": "SKU",
            "name": "Nazwa",
            "item_type": "Typ produktu",
            "is_active": "Aktywny",
            "price": "Cena (zł)",
            "species": "Gatunek",
            "latin_name": "Nazwa łacińska",
            "genus": "Rodzaj",
            "variety": "Odmiana",
            "pot_size": "Rozmiar donicy",
            "low_stock_threshold": "Próg niskiego stanu magazynowego",
            "length": "Długość",
            "width": "Szerokość",
            "height": "Wysokość",
            "dimension_unit": "Jednostka wymiaru",
            "material_unit": "Jednostka materiału",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.plant_fields:
            self.fields[name].required = False
            self.fields[name].widget.attrs["data-group"] = "plant"
        for name in self.material_fields:
            self.fields[name].required = False
            self.fields[name].widget.attrs["data-group"] = "material"


class ProductImageForm(forms.ModelForm):
    class Meta:
        model = ProductImage
        fields = ["image", "alt_text", "is_primary"]
        labels = {
            "image": "Plik zdjęcia",
            "alt_text": "Opis (alt)",
            "is_primary": "Zdjęcie główne",
        }
