from io import BytesIO

from pypdf import PdfReader


async def extract_text_by_page(buffer: bytes) -> list[str]:
    reader = PdfReader(BytesIO(buffer))
    return [page.extract_text() or "" for page in reader.pages]
