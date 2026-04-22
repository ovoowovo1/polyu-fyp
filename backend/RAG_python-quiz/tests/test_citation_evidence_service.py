import unittest
from unittest.mock import AsyncMock, patch

from llama_index.core.base.response.schema import Response
from llama_index.core.schema import NodeWithScore, TextNode

from app.services import citation_evidence_service as service


def _source_node(chunk_id: str, *, file_id="file-1", source="notes.pdf", page=5):
    node = TextNode(
        text=f"text for {chunk_id}",
        id_=chunk_id,
        metadata={
            "chunk_id": chunk_id,
            "file_id": file_id,
            "source": source,
            "page": page,
        },
    )
    return NodeWithScore(node=node, score=0.5)


class CitationEvidenceServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_and_build_retrieval_evidence_cover_aliases(self):
        self.assertEqual(service._normalize_concepts([" SQL ", "", "SQL", "NoSQL"]), ["SQL", "NoSQL"])

        documents = [
            {
                "text": " First chunk ",
                "source": "doc-a.pdf",
                "page": 3,
                "score": 0.25,
                "fileid": "file-a",
                "chunkid": "chunk-a",
            },
            {
                "content": "Second chunk",
                "document_name": "doc-b.pdf",
                "pageStart": 7,
                "rrf_score": 0.75,
                "fileId": "file-b",
                "chunkId": "chunk-b",
            },
            {
                "content": "",
            },
        ]

        normalized = service.normalize_retrieved_documents(documents)
        evidence = service.build_retrieval_evidence(
            [
                {**documents[0], "covered_concepts": ["SQL"]},
                documents[1],
                documents[2],
            ],
            required_concepts=["SQL", "NoSQL"],
        )

        self.assertEqual(normalized[0]["content"], "First chunk")
        self.assertEqual(normalized[0]["fileId"], "file-a")
        self.assertEqual(normalized[1]["source"], "doc-b.pdf")
        self.assertEqual(normalized[1]["pageNumber"], 7)
        self.assertEqual(normalized[2]["source"], "Unknown source")
        self.assertEqual(normalized[2]["pageNumber"], "Unknown page")
        self.assertIsNone(normalized[2]["score"])
        self.assertEqual(evidence["raw_sources"], normalized)
        self.assertEqual(evidence["evidence_nodes"][0]["node_id"], "chunk-a")
        self.assertEqual(evidence["evidence_nodes"][2]["node_id"], "evidence-node-3")
        self.assertEqual(evidence["required_concepts"], ["SQL", "NoSQL"])
        self.assertEqual(evidence["covered_concepts"], ["SQL"])
        self.assertEqual(evidence["missing_concepts"], ["NoSQL"])
        self.assertEqual(
            service._build_synthesis_question(
                "what is SQL and NoSQL",
                "definition_multi",
                ["SQL", "NoSQL"],
                ["SQL", "NoSQL"],
                [],
            ),
            "what is SQL and NoSQL\n\nAnswer only with information supported by the provided sources.\nMake sure the answer covers all of these concepts when supported: SQL, NoSQL.",
        )
        self.assertEqual(service._build_missing_concept_disclaimer([]), "")
        self.assertEqual(
            service._build_missing_concept_disclaimer(["SQL", "NoSQL"]),
            "The selected documents do not provide enough reliable information about SQL, and NoSQL.",
        )
        self.assertIn(
            "Prefer direct comparisons over incidental mentions.",
            service._build_synthesis_question(
                "compare SQL and NoSQL",
                "comparison",
                ["SQL", "NoSQL"],
                ["SQL", "NoSQL"],
                [],
            ),
        )

    def test_build_answer_with_citations_extracts_segments_and_unique_citations(self):
        answer_text = "Alpha [1]. Beta [2] [1]!"
        source_nodes = [_source_node("chunk-1"), _source_node("chunk-2", file_id="file-2", page=8)]

        clean_answer, citations, answer_with_citations = service.build_answer_with_citations(
            answer_text,
            source_nodes,
        )

        self.assertEqual(clean_answer, "Alpha. Beta!")
        self.assertEqual(
            citations,
            [
                {"chunk_id": "chunk-1", "file_id": "file-1", "source": "notes.pdf", "page": 5},
                {"chunk_id": "chunk-2", "file_id": "file-2", "source": "notes.pdf", "page": 8},
            ],
        )
        self.assertEqual(
            answer_with_citations,
            [
                {
                    "content_segments": [
                        {"segment_text": "Alpha.", "source_references": [{"file_chunk_id": "chunk-1"}]},
                        {
                            "segment_text": "Beta!",
                            "source_references": [
                                {"file_chunk_id": "chunk-2"},
                                {"file_chunk_id": "chunk-1"},
                            ],
                        },
                    ]
                }
            ],
        )

    def test_build_answer_with_citations_handles_empty_and_invalid_references(self):
        self.assertEqual(service.build_answer_with_citations("", []), ("", [], []))

        clean_answer, citations, answer_with_citations = service.build_answer_with_citations(
            "Loose text [3]",
            [_source_node("chunk-1")],
        )

        self.assertEqual(clean_answer, "Loose text")
        self.assertEqual(citations, [])
        self.assertEqual(answer_with_citations, [])

        missing_chunk_node = NodeWithScore(
            node=TextNode(text="orphan text", id_="", metadata={}),
            score=0.1,
        )
        self.assertIsNone(service._citation_reference([missing_chunk_node], 1))
        fallback_citations, fallback_answer = service._fallback_citation_payload(
            "Fallback answer",
            [_source_node("chunk-1")],
        )
        self.assertEqual(fallback_citations[0]["chunk_id"], "chunk-1")
        self.assertEqual(
            fallback_answer,
            [
                {
                    "content_segments": [
                        {
                            "segment_text": "Fallback answer",
                            "source_references": [{"file_chunk_id": "chunk-1"}],
                        }
                    ]
                }
            ],
        )
        self.assertEqual(service._fallback_citation_payload("", [_source_node("chunk-1")]), ([], []))
        orphan_node = NodeWithScore(node=TextNode(text="orphan text", id_="", metadata={}), score=0.1)
        self.assertEqual(service._fallback_citation_payload("Fallback answer", [orphan_node]), ([], []))

    def test_static_retriever_and_custom_llm_cover_core_methods(self):
        nodes = [_source_node("chunk-1")]
        retriever = service.StaticNodeRetriever(nodes)
        self.assertEqual(retriever.retrieve("question"), nodes)

        captured = {}

        class _FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return object()

        class _FakeChat:
            def __init__(self):
                self.completions = _FakeCompletions()

        class _FakeClient:
            def __init__(self):
                self.chat = _FakeChat()

        llm = service.OpenAICompatibleCustomLLM(model_name="test-model", api_key="abc")
        with patch("app.services.citation_evidence_service.get_llm_client", return_value=_FakeClient()), patch(
            "app.services.citation_evidence_service.extract_chat_completion_text",
            return_value="Completed answer",
        ):
            completion = llm.complete("Prompt text")
            streamed = list(llm.stream_complete("Prompt text"))

        self.assertEqual(llm.metadata.model_name, "test-model")
        self.assertEqual(completion.text, "Completed answer")
        self.assertEqual(streamed[0].delta, "Completed answer")
        self.assertEqual(captured["model"], "test-model")
        self.assertEqual(captured["messages"], [{"role": "user", "content": "Prompt text"}])

    def test_run_citation_query_builds_engine_with_static_retriever(self):
        fake_response = Response(response="Answer [1]", source_nodes=[_source_node("chunk-1")])
        captured = {}

        class _FakeQueryEngine:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def query(self, question):
                captured["question"] = question
                return fake_response

        with patch("app.services.citation_evidence_service.CitationQueryEngine", _FakeQueryEngine), patch(
            "app.services.citation_evidence_service.get_default_llm_model_name",
            return_value="test-model",
        ):
            result = service._run_citation_query(
                "What is CAP theorem?",
                [{"content": "Chunk text", "source": "doc.pdf", "pageNumber": 1, "chunkId": "chunk-1"}],
            )

        self.assertIs(result, fake_response)
        self.assertIsInstance(captured["retriever"], service.StaticNodeRetriever)
        self.assertIsInstance(captured["llm"], service.OpenAICompatibleCustomLLM)
        self.assertEqual(captured["citation_chunk_size"], service.DEFAULT_CITATION_CHUNK_SIZE)
        self.assertEqual(captured["citation_chunk_overlap"], 0)
        self.assertEqual(captured["question"], "What is CAP theorem?")

    async def test_generate_citation_evidence_covers_empty_and_non_empty_documents(self):
        empty_result = await service.generate_citation_evidence("question", [])
        self.assertEqual(
            empty_result,
            {
                "answer_text": "",
                "citations": [],
                "raw_sources": [],
                "evidence_nodes": [],
                "answer_with_citations": [],
                "required_concepts": [],
                "covered_concepts": [],
                "missing_concepts": [],
                "coverage_status": "empty",
            },
        )

        response = Response(response="Grounded answer [1].", source_nodes=[_source_node("chunk-1")])
        with patch(
            "app.services.citation_evidence_service._run_citation_query",
            return_value=response,
        ) as run_query:
            result = await service.generate_citation_evidence(
                "question",
                [
                    {
                        "text": "Grounded answer",
                        "source": "doc.pdf",
                        "page": 2,
                        "score": 0.3,
                        "fileId": "file-1",
                        "chunkId": "chunk-1",
                    }
                ],
            )

        run_query.assert_called_once()
        self.assertEqual(result["answer_text"], "Grounded answer.")
        self.assertEqual(result["citations"][0]["chunk_id"], "chunk-1")
        self.assertEqual(result["raw_sources"][0]["chunkId"], "chunk-1")
        self.assertEqual(result["evidence_nodes"][0]["node_id"], "chunk-1")
        self.assertEqual(result["required_concepts"], [])
        self.assertEqual(result["covered_concepts"], [])
        self.assertEqual(result["missing_concepts"], [])
        self.assertEqual(result["coverage_status"], "complete")
        self.assertEqual(
            result["answer_with_citations"],
            [
                {
                    "content_segments": [
                        {
                            "segment_text": "Grounded answer.",
                            "source_references": [{"file_chunk_id": "chunk-1"}],
                        }
                    ]
                }
            ],
        )

    async def test_generate_citation_evidence_builds_partial_answer_when_concepts_missing(self):
        response = Response(response="NoSQL uses flexible schemas [1].", source_nodes=[_source_node("chunk-1")])

        with patch(
            "app.services.citation_evidence_service._run_citation_query",
            return_value=response,
        ) as run_query:
            result = await service.generate_citation_evidence(
                "what is SQL and NoSQL",
                [
                    {
                        "text": "NoSQL uses flexible schemas.",
                        "source": "doc.pdf",
                        "page": 2,
                        "score": 0.3,
                        "fileId": "file-1",
                        "chunkId": "chunk-1",
                        "covered_concepts": ["NoSQL"],
                    }
                ],
                required_concepts=["SQL", "NoSQL"],
                covered_concepts=["NoSQL"],
                intent_type="comparison",
            )

        self.assertIn("Missing evidence concepts: SQL.", run_query.call_args.args[0])
        self.assertEqual(result["covered_concepts"], ["NoSQL"])
        self.assertEqual(result["missing_concepts"], ["SQL"])
        self.assertEqual(result["coverage_status"], "partial")
        self.assertIn("do not provide enough reliable information about SQL", result["answer_text"])

    async def test_generate_citation_evidence_adds_fallback_citation_when_inline_citations_missing(self):
        response = Response(response="Grounded answer without inline citations.", source_nodes=[_source_node("chunk-1")])

        with patch(
            "app.services.citation_evidence_service._run_citation_query",
            return_value=response,
        ):
            result = await service.generate_citation_evidence(
                "question",
                [
                    {
                        "text": "Grounded answer without inline citations.",
                        "source": "doc.pdf",
                        "page": 1,
                        "fileId": "file-1",
                        "chunkId": "chunk-1",
                    }
                ],
            )

        self.assertEqual(result["citations"][0]["chunk_id"], "chunk-1")
        self.assertEqual(
            result["answer_with_citations"][0]["content_segments"][0]["source_references"],
            [{"file_chunk_id": "chunk-1"}],
        )
