from google import genai
from google.genai import types

from app.utils.dev_credentials import MissingCredentialError, get_llm_credentials

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
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents="Hello, world!",
    )
    print(response.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

