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

    def test_build_answer_with_citations_extracts_block_segments_and_unique_citations(self):
        answer_text = "Alpha [1]. Beta [2] [1]!"
        source_nodes = [_source_node("chunk-1"), _source_node("chunk-2", file_id="file-2", page=8)]

        cited_answer, citations, answer_with_citations = service.build_answer_with_citations(
            answer_text,
            source_nodes,
        )

        self.assertEqual(cited_answer, "Alpha [1]. Beta [2] [1]!")
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
                        {
                            "segment_text": "Alpha. Beta!",
                            "source_references": [
                                {"file_chunk_id": "chunk-1"},
                                {"file_chunk_id": "chunk-2"},
                            ],
                        },
                    ]
                }
            ],
        )

    def test_build_answer_with_citations_supports_bracket_lists_without_truncating_sentence_tails(self):
        answer_text = "Announcement later [1, 2, 2], and additional hours will be provided."
        source_nodes = [_source_node("chunk-1"), _source_node("chunk-2", file_id="file-2", page=8)]

        cited_answer, citations, answer_with_citations = service.build_answer_with_citations(
            answer_text,
            source_nodes,
        )

        self.assertEqual(
            cited_answer,
            "Announcement later [1, 2, 2], and additional hours will be provided.",
        )
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
                        {
                            "segment_text": "Announcement later, and additional hours will be provided.",
                            "source_references": [
                                {"file_chunk_id": "chunk-1"},
                                {"file_chunk_id": "chunk-2"},
                            ],
                        }
                    ]
                }
            ],
        )

    def test_build_answer_with_citations_preserves_markdown_paragraphs_and_list_items(self):
        answer_text = (
            "## Summary\n"
            "CAP theorem balances consistency and availability under partitions [1].\n\n"
            "- Partition tolerance is mandatory in distributed systems [2]\n"
            "- Trade-offs depend on failure conditions [1, 2]"
        )

        cited_answer, citations, answer_with_citations = service.build_answer_with_citations(
            answer_text,
            [_source_node("chunk-1"), _source_node("chunk-2", file_id="file-2", page=8)],
        )

        self.assertEqual(cited_answer, answer_text)
        self.assertEqual([citation["chunk_id"] for citation in citations], ["chunk-1", "chunk-2"])
        self.assertEqual(
            answer_with_citations,
            [
                {
                    "content_segments": [
                        {
                            "segment_text": "## Summary\nCAP theorem balances consistency and availability under partitions.",
                            "source_references": [{"file_chunk_id": "chunk-1"}],
                        },
                        {
                            "segment_text": "- Partition tolerance is mandatory in distributed systems",
                            "source_references": [{"file_chunk_id": "chunk-2"}],
                        },
                        {
                            "segment_text": "- Trade-offs depend on failure conditions",
                            "source_references": [
                                {"file_chunk_id": "chunk-1"},
                                {"file_chunk_id": "chunk-2"},
                            ],
                        },
                    ]
                }
            ],
        )

    def test_build_answer_with_citations_handles_empty_and_invalid_references(self):
        self.assertEqual(service.build_answer_with_citations("", []), ("", [], []))

        cited_answer, citations, answer_with_citations = service.build_answer_with_citations(
            "Loose text [3]",
            [_source_node("chunk-1")],
        )

        self.assertEqual(cited_answer, "Loose text [3]")
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

    def test_helper_coverage_for_empty_markdown_heading_merges_and_limits_sections(self):
        self.assertEqual(service._normalize_markdown_answer(""), "")
        self.assertEqual(
            service._split_list_items(["", "Plain intro", "continued detail"]),
            ["Plain intro\ncontinued detail"],
        )
        self.assertEqual(service._split_markdown_blocks(""), [])
        self.assertEqual(
            service._split_markdown_blocks("## Heading\n\n\n- First point [1]\n- Second point [2]"),
            ["## Heading\n- First point [1]", "- Second point [2]"],
        )
        self.assertEqual(service._format_sources_for_prompt([]), "[No grounded sources available]")
        self.assertTrue(service._format_source_excerpt("x" * 900).endswith("..."))
        self.assertEqual(service._build_default_citation_suffix([]), "")
        self.assertEqual(
            service._ensure_missing_concept_section(
                "## Limits\nThe selected documents do not provide enough reliable information about SQL. [1]",
                ["SQL"],
                [_source_node("chunk-1")],
            ),
            "## Limits\nThe selected documents do not provide enough reliable information about SQL. [1]",
        )
        self.assertEqual(
            service._ensure_missing_concept_section("", ["SQL"], []),
            "## Limits\nThe selected documents do not provide enough reliable information about SQL.",
        )

    async def test_synthesize_markdown_answer_uses_grounded_prompt_and_normalizes_output(self):
        with patch(
            "app.services.citation_evidence_service.generate_text_completion",
            AsyncMock(return_value="## Answer\n\nGrounded explanation [1]\n"),
        ) as generate_text_completion:
            result = await service.synthesize_markdown_answer(
                "What is CAP theorem?",
                "Draft answer [1].",
                [_source_node("chunk-1")],
                required_concepts=["CAP theorem"],
                covered_concepts=["CAP theorem"],
                missing_concepts=[],
                intent_type="single",
            )

        self.assertEqual(result, "## Answer\n\nGrounded explanation [1]")
        prompt = generate_text_completion.await_args.args[0]
        self.assertIn("Rewrite the grounded answer into a fuller English Markdown response.", prompt)
        self.assertIn("Every factual paragraph or bullet item must end with one or more bracket citations", prompt)
        self.assertIn("[1] notes.pdf | page 5 | chunk_id=chunk-1", prompt)
        self.assertEqual(
            await service.synthesize_markdown_answer("What is CAP theorem?", "   ", [_source_node("chunk-1")]),
            "",
        )

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
        ) as run_query, patch(
            "app.services.citation_evidence_service.generate_text_completion",
            AsyncMock(return_value="## Answer\nGrounded answer in Markdown [1]."),
        ) as generate_text_completion:
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
        generate_text_completion.assert_awaited_once()
        self.assertEqual(result["answer_text"], "## Answer\nGrounded answer in Markdown [1].")
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
                            "segment_text": "## Answer\nGrounded answer in Markdown.",
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
        ) as run_query, patch(
            "app.services.citation_evidence_service.generate_text_completion",
            AsyncMock(return_value="## NoSQL\nNoSQL uses flexible schemas [1]."),
        ):
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
        self.assertIn("## Limits", result["answer_text"])
        self.assertIn("do not provide enough reliable information about SQL", result["answer_text"])
        self.assertEqual(
            result["answer_with_citations"][0]["content_segments"][-1],
            {
                "segment_text": "## Limits\nThe selected documents do not provide enough reliable information about SQL.",
                "source_references": [{"file_chunk_id": "chunk-1"}],
            },
        )

    async def test_generate_citation_evidence_adds_fallback_citation_when_inline_citations_missing(self):
        response = Response(response="Grounded answer without inline citations.", source_nodes=[_source_node("chunk-1")])

        with patch(
            "app.services.citation_evidence_service._run_citation_query",
            return_value=response,
        ), patch(
            "app.services.citation_evidence_service.generate_text_completion",
            AsyncMock(return_value="## Answer\nGrounded answer without inline citations."),
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
        self.assertEqual(
            result["answer_with_citations"][0]["content_segments"][0]["segment_text"],
            "## Answer\nGrounded answer without inline citations.",
        )

    async def test_generate_citation_evidence_falls_back_to_citation_query_draft_when_markdown_synthesis_fails(self):
        response = Response(response="Grounded answer [1].", source_nodes=[_source_node("chunk-1")])

        with patch(
            "app.services.citation_evidence_service._run_citation_query",
            return_value=response,
        ), patch(
            "app.services.citation_evidence_service.generate_text_completion",
            AsyncMock(side_effect=RuntimeError("llm failed")),
        ):
            result = await service.generate_citation_evidence(
                "question",
                [
                    {
                        "text": "Grounded answer",
                        "source": "doc.pdf",
                        "page": 1,
                        "fileId": "file-1",
                        "chunkId": "chunk-1",
                    }
                ],
            )

        self.assertEqual(result["answer_text"], "Grounded answer [1].")
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
