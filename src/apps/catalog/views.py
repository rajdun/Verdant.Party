from django.contrib import messages
from django.db.models import ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from apps.catalog.forms import ProductForm, ProductImageForm
from apps.catalog.models import Product, ProductImage

FILTERABLE_FIELDS = ("sku", "name", "item_type", "latin_name", "genus", "variety", "pot_size")
SORTABLE_FIELDS = FILTERABLE_FIELDS


class ProductListView(ListView):
    model = Product
    context_object_name = "products"
    template_name = "catalog/product_list.html"
    paginate_by = 24

    def get_queryset(self):
        qs = Product.objects.prefetch_related("images")
        params = self.request.GET

        query = params.get("q")
        if query:
            text_filter = Q()
            for field in FILTERABLE_FIELDS:
                text_filter |= Q(**{f"{field}__icontains": query})
            qs = qs.filter(text_filter)

        is_active = params.get("is_active")
        if is_active in ("true", "false"):
            qs = qs.filter(is_active=(is_active == "true"))

        for field in FILTERABLE_FIELDS:
            if value := params.get(field):
                qs = qs.filter(**{field: value})
            if value := params.get(f"{field}__ne"):
                qs = qs.exclude(**{field: value})
            if value := params.get(f"{field}__contains"):
                qs = qs.filter(**{f"{field}__icontains": value})
            if value := params.get(f"{field}__startswith"):
                qs = qs.filter(**{f"{field}__istartswith": value})
            if value := params.get(f"{field}__in"):
                qs = qs.filter(**{f"{field}__in": [v.strip() for v in value.split(",") if v.strip()]})
            if value := params.get(f"{field}__notin"):
                qs = qs.exclude(**{f"{field}__in": [v.strip() for v in value.split(",") if v.strip()]})
            if (value := params.get(f"{field}__isnull")) in ("true", "false"):
                qs = qs.filter(**{f"{field}__isnull": value == "true"})

        sort = params.get("sort")
        order = params.get("order", "asc")
        if sort in SORTABLE_FIELDS:
            qs = qs.order_by(sort if order != "desc" else f"-{sort}")

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["sortable_fields"] = SORTABLE_FIELDS
        context["item_types"] = Product.ItemType.choices
        context["current_params"] = self.request.GET
        return context


class ProductDetailView(DetailView):
    model = Product
    slug_field = "slug"
    slug_url_kwarg = "slug"
    context_object_name = "product"
    template_name = "catalog/product_detail.html"

    def get_queryset(self):
        return Product.objects.prefetch_related("images")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["image_form"] = ProductImageForm()

        images = list(self.object.images.all())
        ids = [image.pk for image in images]
        rows = []
        for index, image in enumerate(images):
            up_order = None
            down_order = None
            if index > 0:
                up_order = ids.copy()
                up_order[index - 1], up_order[index] = up_order[index], up_order[index - 1]
            if index < len(images) - 1:
                down_order = ids.copy()
                down_order[index], down_order[index + 1] = down_order[index + 1], down_order[index]
            rows.append({"image": image, "up_order": up_order, "down_order": down_order})
        context["image_rows"] = rows
        return context


class ProductCreateView(CreateView):
    model = Product
    form_class = ProductForm
    template_name = "catalog/product_form.html"

    def get_success_url(self):
        return reverse("catalog:product_detail", kwargs={"slug": self.object.slug})


class ProductUpdateView(UpdateView):
    model = Product
    form_class = ProductForm
    slug_field = "slug"
    slug_url_kwarg = "slug"
    template_name = "catalog/product_form.html"

    def get_success_url(self):
        return reverse("catalog:product_detail", kwargs={"slug": self.object.slug})


class ProductDeleteView(DeleteView):
    model = Product
    slug_field = "slug"
    slug_url_kwarg = "slug"
    template_name = "catalog/product_confirm_delete.html"

    def get_success_url(self):
        return reverse("catalog:product_list")

    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except ProtectedError:
            messages.error(
                request,
                "Nie można usunąć towaru — posiada powiązane rekordy (zapasy, zamówienia, oferty lub przesyłki).",
            )
            return redirect("catalog:product_detail", slug=self.get_object().slug)


@require_POST
def product_activate(request, slug):
    product = get_object_or_404(Product, slug=slug)
    product.is_active = True
    product.save(update_fields=["is_active", "updated_at"])
    return redirect("catalog:product_detail", slug=slug)


@require_POST
def product_deactivate(request, slug):
    product = get_object_or_404(Product, slug=slug)
    product.is_active = False
    product.save(update_fields=["is_active", "updated_at"])
    return redirect("catalog:product_detail", slug=slug)


def product_image_add(request, slug):
    product = get_object_or_404(Product, slug=slug)
    if request.method == "POST":
        form = ProductImageForm(request.POST, request.FILES)
        if form.is_valid():
            image = form.save(commit=False)
            image.product = product
            image.order = product.images.count()
            image.save()
            return redirect("catalog:product_detail", slug=slug)
    else:
        form = ProductImageForm()
    return render(request, "catalog/productimage_form.html", {"product": product, "form": form})


@require_POST
def product_image_delete(request, pk):
    image = get_object_or_404(ProductImage, pk=pk)
    slug = image.product.slug
    image.delete()
    return redirect("catalog:product_detail", slug=slug)


@require_POST
def product_image_set_primary(request, pk):
    image = get_object_or_404(ProductImage, pk=pk)
    image.is_primary = True
    image.save()
    return redirect("catalog:product_detail", slug=image.product.slug)


@require_POST
def product_image_reorder(request, slug):
    product = get_object_or_404(Product, slug=slug)
    for index, image_id in enumerate(request.POST.getlist("image_id")):
        ProductImage.objects.filter(pk=image_id, product=product).update(order=index)
    return redirect("catalog:product_detail", slug=slug)
