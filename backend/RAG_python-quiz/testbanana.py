from pathlib import Path
import warnings

from google import genai
from google.genai import types

from app.utils.dev_credentials import MissingCredentialError, get_llm_credentials

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

__test__ = False


def main() -> int:
    try:
        credentials = get_llm_credentials()
    except MissingCredentialError as exc:
        print(f"[SKIP] {exc}")
        return 1

    client_kwargs = {"api_key": credentials.api_key}
    if credentials.base_url:
        client_kwargs["http_options"] = types.HttpOptions(base_url=credentials.base_url)

    client = genai.Client(**client_kwargs)
    chat = client.chats.create(
        model="gemini-3-pro-image-preview",
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )

    message = """
A simplified isometric diagram of a server cluster.
One main server in the center has a red 'X' or is smoking (indicating failure).
Three other smaller servers surround it, connected by lines.
Arrows point from the smaller servers to each other.
Clean, flat vector art style.
"""

    response = chat.send_message(message)
    output_path = Path(__file__).with_name("server_cluster.png")

    for part in response.parts:
        if part.text is not None:
            print(part.text)
        else:
            image = part.as_image()
            if image is not None:
                image.save(output_path)
                print(f"Saved image to {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

