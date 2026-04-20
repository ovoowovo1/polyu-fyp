from unittest.mock import AsyncMock, patch
import unittest

from app.services import embedding_backfill_service


class EmbeddingBackfillServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_backfill_updates_missing_chunks_in_order(self):
        fake_model = object()

        with patch(
            "app.services.embedding_backfill_service.create_embedding_model",
            return_value=fake_model,
        ) as create_model, patch(
            "app.services.embedding_backfill_service.pg_service.get_chunks_missing_embeddings",
            side_effect=[
                [
                    {"id": "chunk-1", "text": "first"},
                    {"id": "chunk-2", "text": "second"},
                ],
                [],
            ],
        ) as get_missing, patch(
            "app.services.embedding_backfill_service.document_service.embed_texts_with_retry",
            AsyncMock(return_value=[[1.0], [2.0]]),
        ) as embed_texts, patch(
            "app.services.embedding_backfill_service.pg_service.update_chunk_embeddings",
            return_value=2,
        ) as update_embeddings:
            summary = await embedding_backfill_service.backfill_embedding_column(batch_size=2)

        create_model.assert_called_once_with(model_name=embedding_backfill_service.DEFAULT_V2_MODEL)
        get_missing.assert_any_call(embedding_column="embedding_v2", limit=2)
        embed_texts.assert_awaited_once_with(["first", "second"], embeddings_model=fake_model)
        update_embeddings.assert_called_once_with(
            [
                {"id": "chunk-1", "embedding": [1.0]},
                {"id": "chunk-2", "embedding": [2.0]},
            ],
            embedding_column="embedding_v2",
        )
        self.assertEqual(summary["updated"], 2)
        self.assertEqual(summary["batches"], 1)

    async def test_backfill_respects_limit(self):
        with patch(
            "app.services.embedding_backfill_service.create_embedding_model",
            return_value=object(),
        ), patch(
            "app.services.embedding_backfill_service.pg_service.get_chunks_missing_embeddings",
            side_effect=[[{"id": "chunk-1", "text": "only"}]],
        ) as get_missing, patch(
            "app.services.embedding_backfill_service.document_service.embed_texts_with_retry",
            AsyncMock(return_value=[[1.0]]),
        ), patch(
            "app.services.embedding_backfill_service.pg_service.update_chunk_embeddings",
            return_value=1,
        ):
            summary = await embedding_backfill_service.backfill_embedding_column(batch_size=5, limit=1)

        get_missing.assert_called_once_with(embedding_column="embedding_v2", limit=1)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(summary["limit"], 1)

    async def test_backfill_rejects_invalid_batch_size(self):
        with self.assertRaises(ValueError):
            await embedding_backfill_service.backfill_embedding_column(batch_size=0)
