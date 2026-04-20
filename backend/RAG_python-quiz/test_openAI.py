import requests

from app.utils.dev_credentials import MissingCredentialError, get_eval_embedding_credentials

__test__ = False


def main() -> int:
    try:
        credentials = get_eval_embedding_credentials()
    except MissingCredentialError as exc:
        print(f"[SKIP] {exc}")
        return 1

    response = requests.post(
        f"{credentials.base_url.rstrip('/')}/embeddings",
        json={
            "model": credentials.model,
            "input": ["What is the meaning of life?"],
            "encoding_format": "float",
        },
        headers={
            "Authorization": f"Bearer {credentials.api_key}",
            "Content-Type": "application/json",
        },
        timeout=60,
    )
    payload = response.json()

    if "error" in payload:
        raise RuntimeError(f"Embedding provider error: {payload['error']}")

    embedding = payload["data"][0]["embedding"]
    print(len(embedding), embedding[:5])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
