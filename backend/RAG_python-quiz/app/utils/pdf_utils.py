from io import BytesIO
from typing import Any

from pypdf import PdfReader


_IMAGE_MIME_TYPES = {
    "JPEG": "image/jpeg",
    "JPG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "BMP": "image/bmp",
    "GIF": "image/gif",
}


def _extract_image_payload(image_file: Any) -> tuple[bytes, str]:
    """Return normalized image bytes and MIME type from a pypdf ImageFile."""
    image = getattr(image_file, "image", None)
    image_format = (getattr(image, "format", None) or "").upper()
    mimetype = _IMAGE_MIME_TYPES.get(image_format) if image_format in {"JPEG", "JPG", "PNG"} else None
    data = getattr(image_file, "data", b"") or b""

    if image is not None and not mimetype:
        output = BytesIO()
        image.save(output, format="PNG")
        data = output.getvalue()
        mimetype = "image/png"

    if not mimetype:
        name = str(getattr(image_file, "name", "")).lower()
        mimetype = (
            "image/jpeg" if name.endswith((".jpg", ".jpeg"))
            else "image/webp" if name.endswith(".webp")
            else "image/bmp" if name.endswith(".bmp")
            else "image/png"
        )

    if not data:
        raise ValueError("PDF image contained no data")
    return data, mimetype


async def extract_pdf_content_by_page(buffer: bytes) -> list[dict[str, Any]]:
    """Extract text and embedded raster images while preserving page metadata."""
    reader = PdfReader(BytesIO(buffer))
    pages: list[dict[str, Any]] = []
    for page_number, page in enumerate(reader.pages, start=1):
        images = []
        for image_index, image_file in enumerate(getattr(page, "images", []), start=1):
            data, mimetype = _extract_image_payload(image_file)
            images.append(
                {
                    "data": data,
                    "mimetype": mimetype,
                    "name": str(getattr(image_file, "name", f"image-{image_index}")),
                    "imageIndex": image_index,
                }
            )
        pages.append(
            {
                "pageNumber": page_number,
                "text": page.extract_text() or "",
                "images": images,
            }
        )
    return pages


async def extract_text_by_page(buffer: bytes) -> list[str]:
    """Backward-compatible text-only PDF extraction helper."""
    pages = await extract_pdf_content_by_page(buffer)
    return [page["text"] for page in pages]
