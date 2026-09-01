import io

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import File
from PIL import Image, ImageOps


def make_thumbnail(source: File, size: tuple[int, int] = (400, 400)) -> ContentFile | None:
    """Build a resized JPEG copy of `source` that fits within `size`.

    Returns None if `source` can't be read as an image.
    """
    source.seek(0)
    try:
        img = Image.open(source)
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except Exception:
        return None

    img.thumbnail(size, Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    buffer.seek(0)

    original_name = source.name.rsplit("/", 1)[-1]
    stem = original_name.rsplit(".", 1)[0]
    return ContentFile(buffer.read(), name=f"{stem}_thumb.jpg")
