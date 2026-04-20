from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.embedding_backfill_service import (  # noqa: E402
    DEFAULT_TARGET_COLUMN,
    DEFAULT_V2_MODEL,
    backfill_embedding_column,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill chunks.embedding_v2 with Gemini Embedding 2 vectors.")
    parser.add_argument("--batch-size", type=int, default=30, help="Number of chunks to embed per batch.")
    parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of chunks to backfill.")
    parser.add_argument("--model", default=DEFAULT_V2_MODEL, help="Embedding model to use for backfill.")
    parser.add_argument(
        "--column",
        default=DEFAULT_TARGET_COLUMN,
        help="Target embedding column to populate.",
    )
    return parser.parse_args()


async def _main() -> int:
    args = parse_args()
    summary = await backfill_embedding_column(
        batch_size=args.batch_size,
        limit=args.limit,
        model_name=args.model,
        embedding_column=args.column,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
