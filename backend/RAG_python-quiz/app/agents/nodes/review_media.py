import base64
import os
from typing import Tuple


def load_image_as_base64(image_path: str) -> Tuple[str, str]:
    with open(image_path, "rb") as file_obj:
        image_data = file_obj.read()

    ext = os.path.splitext(image_path)[1].lower()
    mime_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "image/png")
    return mime_type, base64.b64encode(image_data).decode("utf-8")


def get_absolute_image_path(relative_path: str, images_dir: str) -> str:
    if relative_path.startswith("/static/images/"):
        filename = relative_path[len("/static/images/"):]
        return os.path.join(images_dir, filename)
    return relative_path
