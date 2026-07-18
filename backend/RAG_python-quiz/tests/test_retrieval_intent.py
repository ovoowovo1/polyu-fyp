import unittest
import sys
import types
from unittest.mock import AsyncMock, patch

from app.services.rag import retrieval_intent


def query_spec(label, query, concept, query_kind):
    return {
        "label": label,
        "query": query,
        "concept": concept,
        "query_kind": query_kind,
    }


def comparison_plan():
    sql = query_spec("SQL", "SQL definition", "SQL", "concept_support")
    nosql = query_spec("NoSQL", "NoSQL definition", "NoSQL", "concept_support")
    return {
        "mode": "multi",
        "intent_type": "comparison",
        "required_concepts": [" SQL ", "NoSQL", "sql"],
        "subqueries": [sql, nosql],
        "search_queries": [
            query_spec("comparison", "SQL \u8207 NoSQL \u6bd4\u8f03", None, "comparison"),
            sql,
            nosql,
        ],
    }


class RetrievalIntentTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_default_structured_generator_when_not_injected(self):
        fallback_plan = {
            "mode": "single",
            "intent_type": "single",
            "required_concepts": [],
            "subqueries": [],
            "search_queries": [query_spec("original", "question", None, "original")],
        }
        generator = AsyncMock(return_value=fallback_plan)
        fake_module = types.ModuleType("app.services.ai.llm.structured_json")
        fake_module.generate_structured_json = generator

        with patch.dict(
            sys.modules,
            {"app.services.ai.llm.structured_json": fake_module},
        ):
            result = await retrieval_intent.classify_query_intent("question")

        self.assertEqual(result, fallback_plan)
        generator.assert_awaited_once()

    async def test_classifies_traditional_chinese_comparison_and_preserves_full_plan(self):
        question = "SQL \u540c NoSQL \u6709\u5481\u5206\u5225\uff1f"
        generator = AsyncMock(return_value=comparison_plan())

        result = await retrieval_intent.classify_query_intent(
            question,
            generate_structured_json_func=generator,
        )

        self.assertEqual(result["mode"], "multi")
        self.assertEqual(result["intent_type"], "comparison")
        self.assertEqual(result["required_concepts"], ["SQL", "NoSQL"])
        self.assertEqual(result["search_queries"][0]["query_kind"], "comparison")
        self.assertEqual(result["subqueries"][0]["concept"], "SQL")
        prompt = generator.await_args.args[0]
        self.assertIn(question, prompt)
        self.assertIn("Traditional Chinese", prompt)
        self.assertEqual(generator.await_args.kwargs["operation_name"], "Adaptive RAG classify query intent")
        self.assertEqual(generator.await_args.args[1], retrieval_intent.build_query_intent_schema())

    async def test_classifies_natural_mixed_language_comparison_question(self):
        question = "SQL \u548c NoSQL \u54ea\u500b\u6bd4\u8f03\u9069\u5408\uff1f"
        generator = AsyncMock(return_value=comparison_plan())

        result = await retrieval_intent.classify_query_intent(
            question,
            generate_structured_json_func=generator,
        )

        self.assertEqual(result["intent_type"], "comparison")
        self.assertEqual(result["required_concepts"], ["SQL", "NoSQL"])
        self.assertIn(question, generator.await_args.args[0])

    async def test_classifies_definition_multi_and_single_queries(self):
        index_concept = "\u8cc7\u6599\u5eab\u7d22\u5f15"
        scan_concept = "\u5168\u8868\u6383\u63cf"
        definition_result = {
            "mode": "multi",
            "intent_type": "definition_multi",
            "required_concepts": [index_concept, scan_concept],
            "subqueries": [
                query_spec("index", f"{index_concept} definition", index_concept, "concept_definition"),
                query_spec("scan", f"{scan_concept} definition", scan_concept, "concept_definition"),
            ],
            "search_queries": [
                query_spec("index", f"{index_concept} definition", index_concept, "concept_definition"),
                query_spec("scan", f"{scan_concept} definition", scan_concept, "concept_definition"),
                query_spec("combined", f"{index_concept}\u8207{scan_concept}", None, "combined_definition"),
            ],
        }
        single_question = "CAP \u5b9a\u7406\u662f\u4ec0\u9ebc\uff1f"
        single_result = {
            "mode": "single",
            "intent_type": "single",
            "required_concepts": [],
            "subqueries": [],
            "search_queries": [query_spec("original", single_question, None, "original")],
        }
        generator = AsyncMock(side_effect=[definition_result, single_result])

        definition = await retrieval_intent.classify_query_intent(
            f"\u8acb\u89e3\u91cb{index_concept}\u548c{scan_concept}\u3002",
            generate_structured_json_func=generator,
        )
        single = await retrieval_intent.classify_query_intent(
            single_question,
            generate_structured_json_func=generator,
        )

        self.assertEqual(definition["intent_type"], "definition_multi")
        self.assertEqual(definition["required_concepts"], [index_concept, scan_concept])
        self.assertEqual(single["mode"], "single")
        self.assertEqual(single["search_queries"][0]["query_kind"], "original")

    async def test_classification_error_and_invalid_result_fall_back_to_single_query(self):
        question = "\u8acb\u6bd4\u8f03\u5169\u7a2e\u8cc7\u6599\u5eab"
        generator = AsyncMock(
            side_effect=[
                RuntimeError("provider unavailable"),
                {"mode": "multi", "intent_type": "comparison"},
            ]
        )

        first = await retrieval_intent.classify_query_intent(
            question,
            generate_structured_json_func=generator,
        )
        second = await retrieval_intent.classify_query_intent(
            question,
            generate_structured_json_func=generator,
        )

        for result in (first, second):
            self.assertEqual(result["mode"], "single")
            self.assertEqual(result["intent_type"], "single")
            self.assertEqual(result["required_concepts"], [])
            self.assertEqual(result["search_queries"][0]["query"], question)
            self.assertEqual(result["search_queries"][0]["query_kind"], "original")

    def test_schema_prompt_and_language_neutral_normalizers(self):
        schema = retrieval_intent.build_query_intent_schema()
        self.assertEqual(schema["properties"]["required_concepts"]["maxItems"], 8)
        self.assertEqual(schema["properties"]["search_queries"]["maxItems"], 12)
        self.assertNotIn("enum", schema["properties"]["intent_type"])
        self.assertNotIn("enum", schema["properties"]["search_queries"]["items"]["properties"]["query_kind"])
        prompt = retrieval_intent.build_query_intent_prompt("\u8acb\u6bd4\u8f03 A \u8207 B")
        self.assertIn("\u8acb\u6bd4\u8f03", prompt)
        self.assertIn("scenario_context", prompt)
        self.assertIn("formula_support", prompt)
        self.assertEqual(retrieval_intent._canonicalize_known_concept("  NewSQL  "), "NewSQL")
        self.assertEqual(
            retrieval_intent._clean_concept_fragment("  \u8cc7\u6599\u5eab\u7d22\u5f15\uff01\uff1f  "),
            "\u8cc7\u6599\u5eab\u7d22\u5f15",
        )

    def test_query_spec_validation_rejects_invalid_shapes(self):
        valid_concepts = ["SQL", "NoSQL"]
        invalid_specs = [
            None,
            {"label": "", "query": "q", "concept": None, "query_kind": "original"},
            {"label": "label", "query": "", "concept": None, "query_kind": "original"},
            {"label": "label", "query": "q", "concept": 3, "query_kind": "original"},
            {"label": "label", "query": "q", "concept": None, "query_kind": ""},
            {"label": "label", "query": "q", "concept": None, "query_kind": 3},
            {"label": "label", "query": "q", "concept": "Other", "query_kind": "concept_support"},
        ]
        for invalid_spec in invalid_specs:
            with self.subTest(invalid_spec=invalid_spec):
                with self.assertRaises(ValueError):
                    retrieval_intent._normalize_query_spec(invalid_spec, valid_concepts)

        normalized = retrieval_intent._normalize_query_spec(
            query_spec(" SQL ", "  SQL   definition ", " SQL ", "concept_support"),
            valid_concepts,
        )
        self.assertEqual(normalized, query_spec("SQL", "SQL definition", "SQL", "concept_support"))

    def test_open_semantic_labels_are_normalized_and_preserved(self):
        scenario_plan = {
            "mode": "single",
            "intent_type": " Scenario ",
            "required_concepts": ["Load balancing"],
            "subqueries": [
                query_spec(
                    "case context",
                    "10,000 users need low-latency traffic distribution",
                    None,
                    " Scenario_Context ",
                )
            ],
            "search_queries": [
                query_spec(
                    "scenario",
                    "10,000 users need low-latency traffic distribution",
                    None,
                    " Scenario_Context ",
                ),
                query_spec(
                    "support",
                    "load balancing strategies",
                    "Load balancing",
                    "Scenario_Support",
                ),
            ],
        }
        quantitative_plan = {
            "mode": "single",
            "intent_type": "QUANTITATIVE",
            "required_concepts": ["throughput"],
            "subqueries": [],
            "search_queries": [
                query_spec("data", "requests per second over 5 minutes", None, "data_context"),
                query_spec("formula", "throughput calculation formula", "throughput", "formula_support"),
            ],
        }

        scenario = retrieval_intent._normalize_query_intent(scenario_plan)
        quantitative = retrieval_intent._normalize_query_intent(quantitative_plan)

        self.assertEqual(scenario["intent_type"], "scenario")
        self.assertEqual(
            [query["query_kind"] for query in scenario["search_queries"]],
            ["scenario_context", "scenario_support"],
        )
        self.assertEqual(quantitative["intent_type"], "quantitative")
        self.assertEqual(
            [query["query_kind"] for query in quantitative["search_queries"]],
            ["data_context", "formula_support"],
        )

    async def test_unknown_semantic_labels_do_not_fall_back(self):
        question = "A novel reasoning question"
        plan = {
            "mode": "single",
            "intent_type": "novel_reasoning",
            "required_concepts": [],
            "subqueries": [],
            "search_queries": [query_spec("reasoning", question, None, "evidence_lookup")],
        }
        generator = AsyncMock(return_value=plan)

        result = await retrieval_intent.classify_query_intent(
            question,
            generate_structured_json_func=generator,
        )

        self.assertEqual(result["intent_type"], "novel_reasoning")
        self.assertEqual(result["search_queries"][0]["query_kind"], "evidence_lookup")
        self.assertEqual(result["search_queries"][0]["query"], question)

    def test_query_intent_validation_rejects_malformed_structural_plans(self):
        invalid_results = [
            None,
            {"mode": "single", "intent_type": ""},
            {"mode": "invalid", "intent_type": "single"},
            {"mode": "single", "intent_type": "single", "required_concepts": "SQL", "subqueries": [], "search_queries": []},
            {"mode": "single", "intent_type": "single", "required_concepts": [], "subqueries": {}, "search_queries": []},
            {"mode": "single", "intent_type": "single", "required_concepts": [], "subqueries": [], "search_queries": []},
        ]
        for invalid_result in invalid_results:
            with self.subTest(invalid_result=invalid_result):
                with self.assertRaises(ValueError):
                    retrieval_intent._normalize_query_intent(invalid_result)

        too_many_concepts = {
            "mode": "multi",
            "intent_type": "comparison",
            "required_concepts": [f"concept-{index}" for index in range(9)],
            "subqueries": [],
            "search_queries": [query_spec("comparison", "compare", None, "comparison")],
        }
        with self.assertRaises(ValueError):
            retrieval_intent._normalize_query_intent(too_many_concepts)

        too_many_queries = {
            "mode": "single",
            "intent_type": "single",
            "required_concepts": [],
            "subqueries": [],
            "search_queries": [query_spec("q", "q", None, "original")] * 13,
        }
        with self.assertRaises(ValueError):
            retrieval_intent._normalize_query_intent(too_many_queries)
