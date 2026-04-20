import argparse
import json
import traceback

from google import genai
from google.genai import types
from openai import OpenAI

from app.utils.dev_credentials import (
    MissingCredentialError,
    get_eval_embedding_credentials,
    get_genai_credentials,
)

__test__ = False


def _build_genai_client():
    credentials = get_genai_credentials()
    client_kwargs = {"api_key": credentials.api_key}
    if credentials.base_url:
        client_kwargs["http_options"] = types.HttpOptions(base_url=credentials.base_url)
    return genai.Client(**client_kwargs)


def run_genai_client() -> bool:
    print("=" * 50)
    print("Smoke 1: Google GenAI text generation")
    print("=" * 50)

    try:
        client = _build_genai_client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Say hello in one word.",
        )
        print(f"Response: {response.text}")
        return True
    except MissingCredentialError as exc:
        print(f"[SKIP] {exc}")
        return False
    except Exception as exc:
        print(f"[FAIL] {exc}")
        return False


def run_genai_structured_output() -> bool:
    print("\n" + "=" * 50)
    print("Smoke 2: Google GenAI structured JSON output")
    print("=" * 50)

    try:
        client = _build_genai_client()
        schema = {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["answer", "confidence"],
        }
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="What is 2+2? Give a short answer.",
            config=types.GenerateContentConfig(
                temperature=0.7,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        result = json.loads(response.text)
        print(f"Parsed JSON: {result}")
        return True
    except MissingCredentialError as exc:
        print(f"[SKIP] {exc}")
        return False
    except Exception as exc:
        print(f"[FAIL] {exc}")
        traceback.print_exc()
        return False


def run_openai_embedding() -> bool:
    print("\n" + "=" * 50)
    print("Smoke 3: OpenAI-compatible embedding")
    print("=" * 50)

    try:
        credentials = get_eval_embedding_credentials()
        client = OpenAI(api_key=credentials.api_key, base_url=credentials.base_url)
        response = client.embeddings.create(
            model=credentials.model,
            input="What is the meaning of life?",
        )
        result = response.data[0].embedding
        print(f"Vector length: {len(result)}")
        print(f"First 5 values: {result[:5]}")
        return True
    except MissingCredentialError as exc:
        print(f"[SKIP] {exc}")
        return False
    except Exception as exc:
        print(f"[FAIL] {exc}")
        traceback.print_exc()
        return False


def run_openai_embedding_batch() -> bool:
    print("\n" + "=" * 50)
    print("Smoke 4: OpenAI-compatible batch embedding")
    print("=" * 50)

    try:
        credentials = get_eval_embedding_credentials()
        client = OpenAI(api_key=credentials.api_key, base_url=credentials.base_url)
        response = client.embeddings.create(
            model=credentials.model,
            input=["Hello world", "How are you?", "This is a test."],
        )
        results = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
        print(f"Batch count: {len(results)}")
        print(f"Vector lengths: {[len(item) for item in results]}")
        return True
    except MissingCredentialError as exc:
        print(f"[SKIP] {exc}")
        return False
    except Exception as exc:
        print(f"[FAIL] {exc}")
        traceback.print_exc()
        return False


def run_gemini_embedding() -> bool:
    print("\n" + "=" * 50)
    print("Smoke 5: Gemini embedding")
    print("=" * 50)

    try:
        client = _build_genai_client()
        result = client.models.embed_content(
            model="gemini-embedding-001",
            contents="What is the meaning of life?",
        )
        print(result.embeddings)
        return True
    except MissingCredentialError as exc:
        print(f"[SKIP] {exc}")
        return False
    except Exception as exc:
        print(f"[FAIL] {exc}")
        traceback.print_exc()
        return False


def run_openrouter_embedding() -> bool:
    print("\n" + "=" * 50)
    print("Smoke 6: OpenAI-compatible embedding via configured provider")
    print("=" * 50)

    try:
        credentials = get_eval_embedding_credentials()
        client = OpenAI(api_key=credentials.api_key, base_url=credentials.base_url)
        response = client.embeddings.create(
            model=credentials.model,
            input="What is the meaning of life?",
        )
        result = response.data[0].embedding
        print(f"Provider base URL: {credentials.base_url}")
        print(f"Model: {credentials.model}")
        print(f"Vector length: {len(result)}")
        print(f"First 5 values: {result[:5]}")
        return True
    except MissingCredentialError as exc:
        print(f"[SKIP] {exc}")
        return False
    except Exception as exc:
        print(f"[FAIL] {exc}")
        traceback.print_exc()
        return False


def main() -> int:
    checks = {
        "genai-client": run_genai_client,
        "genai-structured": run_genai_structured_output,
        "embedding": run_openai_embedding,
        "embedding-batch": run_openai_embedding_batch,
        "gemini-embedding": run_gemini_embedding,
        "provider-embedding": run_openrouter_embedding,
    }

    parser = argparse.ArgumentParser(description="Manual backend provider smoke checks.")
    parser.add_argument(
        "--check",
        choices=["all", *checks.keys()],
        default="provider-embedding",
        help="Which smoke check to run.",
    )
    args = parser.parse_args()

    selected = checks.keys() if args.check == "all" else [args.check]
    results = {name: checks[name]() for name in selected}

    print("\n" + "=" * 50)
    print("Smoke summary")
    print("=" * 50)
    for name, success in results.items():
        status = "PASS" if success else "SKIP/FAIL"
        print(f"{status} - {name}")

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
