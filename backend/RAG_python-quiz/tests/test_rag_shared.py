import unittest

from app.services import rag_shared


class RagSharedTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_doc_aliases_and_concept_fields(self):
        normalized = rag_shared.normalize_doc(
            {
                "content": "  chunk text  ",
                "document_name": "notes.pdf",
                "pageStart": 4,
                "fileid": "file-1",
                "chunkid": "chunk-1",
                "covered_concepts": [" SQL ", "", "SQL", "NoSQL"],
            },
            normalize_concept_fields=("covered_concepts",),
        )

        self.assertEqual(normalized["content"], "chunk text")
        self.assertEqual(normalized["text"], "chunk text")
        self.assertEqual(normalized["source"], "notes.pdf")
        self.assertEqual(normalized["page"], 4)
        self.assertEqual(normalized["fileId"], "file-1")
        self.assertEqual(normalized["chunkId"], "chunk-1")
        self.assertEqual(normalized["covered_concepts"], ["SQL", "NoSQL"])

    def test_build_raw_sources_evidence_nodes_and_retrieval_evidence(self):
        documents = [
            {
                "text": "Chunk one",
                "source": "doc-a.pdf",
                "page": 3,
                "rrf_score": 0.25,
                "fileId": "file-a",
                "chunkId": "chunk-a",
                "covered_concepts": ["SQL"],
            },
            {"content": "", "chunkId": None},
        ]

        raw_sources = rag_shared.build_raw_sources(documents)
        evidence_nodes = rag_shared.build_evidence_nodes(documents)
        evidence = rag_shared.build_retrieval_evidence(
            documents,
            required_concepts=["SQL", "NoSQL"],
        )

        self.assertEqual(raw_sources[0]["content"], "Chunk one")
        self.assertEqual(raw_sources[0]["pageNumber"], 3)
        self.assertEqual(raw_sources[0]["score"], 0.25)
        self.assertEqual(raw_sources[1]["source"], "Unknown source")
        self.assertEqual(evidence_nodes[0]["node_id"], "chunk-a")
        self.assertEqual(evidence_nodes[1]["node_id"], "evidence-node-2")
        self.assertEqual(evidence["required_concepts"], ["SQL", "NoSQL"])
        self.assertEqual(evidence["covered_concepts"], ["SQL"])
        self.assertEqual(evidence["missing_concepts"], ["NoSQL"])

    async def test_safe_emit_transparently_awaits_callback(self):
        captured = []

        async def callback(message, data=None, event_type="retrieval"):
            captured.append((message, data, event_type))

        await rag_shared.safe_emit(callback, "message", 3, "grader")
        self.assertEqual(captured, [("message", 3, "grader")])
