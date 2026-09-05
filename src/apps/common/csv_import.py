"""Silnik importu CSV: parsowanie, sugerowanie mapowania kolumn i zapis wierszy.

Współdzielone między apps.catalog (Produkty) i apps.inventory (Lokalizacje) —
logika jest niezależna od konkretnego modelu, sterowana wyłącznie przez
przekazaną klasę ModelForm.
"""

import csv
import io
import unicodedata
from dataclasses import dataclass
from django import forms
from django.db import IntegrityError, transaction

UNMAPPED = ""

TRUTHY_TOKENS = {"1", "tak", "yes", "true", "x", "prawda"}


def decode_csv_bytes(raw: bytes) -> str:
    return raw.decode("utf-8-sig")


def sniff_dialect(sample_text: str):
    try:
        return csv.Sniffer().sniff(sample_text, delimiters=",;\t")
    except csv.Error:
        pass
    first_line = sample_text.splitlines()[0] if sample_text.splitlines() else ""
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    dialect = csv.excel()
    dialect.delimiter = delimiter
    return dialect


@dataclass
class ParsedCsv:
    fieldnames: list
    rows: list


def parse_csv(text: str) -> ParsedCsv:
    dialect = sniff_dialect(text[:4096])
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    fieldnames = [(name or "").strip() for name in (reader.fieldnames or [])]
    rows = []
    for raw_row in reader:
        row = {(key or "").strip(): (value or "").strip() for key, value in raw_row.items() if key is not None}
        if any(row.values()):
            rows.append(row)
    return ParsedCsv(fieldnames=fieldnames, rows=rows)


@dataclass
class FieldSpec:
    name: str
    label: str
    is_boolean: bool
    choices: list = None


def field_specs_from_form(form_class) -> list:
    form = form_class()
    specs = []
    for name, field in form.fields.items():
        choices = list(field.choices) if hasattr(field, "choices") and field.choices else None
        if choices:
            choices = [(value, label) for value, label in choices if value not in ("", None)]
        specs.append(
            FieldSpec(
                name=name,
                label=field.label or name,
                is_boolean=isinstance(field, forms.BooleanField),
                choices=choices or None,
            )
        )
    return specs


_DIACRITICS_MAP = str.maketrans({
    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
    "ó": "o", "ś": "s", "ź": "z", "ż": "z",
})


def normalize_label(value: str) -> str:
    value = (value or "").strip().casefold().translate(_DIACRITICS_MAP)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(value.split())


def suggest_mapping(csv_headers, field_specs) -> dict:
    mapping = {}
    for header in csv_headers:
        normalized_header = normalize_label(header)
        match = UNMAPPED
        for spec in field_specs:
            if normalized_header == normalize_label(spec.name) or normalized_header == normalize_label(spec.label):
                match = spec.name
                break
        mapping[header] = match
    return mapping


def coerce_row(raw_row: dict, mapping: dict, field_specs_by_name: dict) -> dict:
    data = {}
    for header, field_name in mapping.items():
        if field_name == UNMAPPED:
            continue
        raw_value = raw_row.get(header, "")
        spec = field_specs_by_name.get(field_name)
        if spec is None:
            continue

        if spec.is_boolean:
            if raw_value.strip().casefold() in TRUTHY_TOKENS:
                data[field_name] = "on"
            continue

        if spec.choices:
            normalized = raw_value.strip().casefold()
            matched = None
            for stored_value, display_label in spec.choices:
                if normalized == stored_value.casefold() or normalize_label(raw_value) == normalize_label(display_label):
                    matched = stored_value
                    break
            data[field_name] = matched if matched is not None else raw_value
            continue

        data[field_name] = raw_value
    return data


@dataclass
class RowResult:
    row_number: int
    success: bool
    errors: dict
    display: dict


def import_rows(parsed: ParsedCsv, mapping: dict, form_class, field_specs: list, display_fields: list):
    field_specs_by_name = {spec.name: spec for spec in field_specs}
    inverse_mapping = {field_name: header for header, field_name in mapping.items() if field_name != UNMAPPED}

    created = 0
    results = []
    for row_number, raw_row in enumerate(parsed.rows, start=1):
        data = coerce_row(raw_row, mapping, field_specs_by_name)
        display = {field: raw_row.get(inverse_mapping.get(field, ""), "") for field in display_fields}
        form = form_class(data=data)
        try:
            with transaction.atomic():
                if form.is_valid():
                    form.save()
                    created += 1
                    results.append(RowResult(row_number, True, None, display))
                else:
                    results.append(RowResult(row_number, False, form.errors.get_json_data(), display))
        except IntegrityError:
            results.append(
                RowResult(
                    row_number,
                    False,
                    {"__all__": [{"message": "Rekord narusza unikalność (np. duplikat SKU/nazwy)."}]},
                    display,
                )
            )
    return created, results
