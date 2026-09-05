from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render

from apps.common.csv_import import (
    decode_csv_bytes,
    field_specs_from_form,
    import_rows,
    parse_csv,
    suggest_mapping,
)


class CsvImportWizardMixin(LoginRequiredMixin):
    """Kreator importu CSV w dwóch krokach: upload pliku, mapowanie kolumn i zapis.

    Konfiguracja przez atrybuty klasy w widoku-podklasie:
      form_class, session_key, upload_template, mapping_template,
      results_template, upload_url_name, mapping_url_name, cancel_url_name,
      display_fields.
    """

    form_class = None
    session_key = None
    upload_template = None
    mapping_template = None
    results_template = None
    upload_url_name = None
    mapping_url_name = None
    cancel_url_name = None
    display_fields = ()

    def handle_upload(self, request):
        if request.method == "POST":
            uploaded_file = request.FILES.get("csv_file")
            if not uploaded_file:
                messages.error(request, "Wybierz plik CSV do zaimportowania.")
            else:
                try:
                    text = decode_csv_bytes(uploaded_file.read())
                except UnicodeDecodeError:
                    messages.error(request, "Nie udało się odczytać pliku — zapisz go jako CSV (UTF-8) i spróbuj ponownie.")
                else:
                    if not text.strip():
                        messages.error(request, "Plik CSV jest pusty.")
                    else:
                        request.session[self.session_key] = {"filename": uploaded_file.name, "text": text}
                        return redirect(self.mapping_url_name)
        return render(request, self.upload_template, {"cancel_url_name": self.cancel_url_name})

    def handle_mapping(self, request):
        stored = request.session.get(self.session_key)
        if not stored:
            messages.info(request, "Sesja importu wygasła — wgraj plik ponownie.")
            return redirect(self.upload_url_name)

        parsed = parse_csv(stored["text"])
        field_specs = field_specs_from_form(self.form_class)

        if request.method == "POST":
            mapping = {
                header: request.POST.get(f"map_{index}", "")
                for index, header in enumerate(parsed.fieldnames)
            }
            created_count, results = import_rows(parsed, mapping, self.form_class, field_specs, list(self.display_fields))
            del request.session[self.session_key]
            return render(
                request,
                self.results_template,
                {
                    "created_count": created_count,
                    "results": results,
                    "total_count": len(results),
                    "cancel_url_name": self.cancel_url_name,
                },
            )

        suggested_mapping = suggest_mapping(parsed.fieldnames, field_specs)
        columns = [
            {"index": index, "header": header, "suggested": suggested_mapping.get(header, "")}
            for index, header in enumerate(parsed.fieldnames)
        ]
        return render(
            request,
            self.mapping_template,
            {
                "filename": stored.get("filename", ""),
                "columns": columns,
                "field_specs": field_specs,
                "preview_rows": parsed.rows[:3],
                "csv_headers": parsed.fieldnames,
                "upload_url_name": self.upload_url_name,
                "cancel_url_name": self.cancel_url_name,
            },
        )
