# -*- coding: utf-8 -*-
"""LangGraph workflow for exam generation."""

from typing import List
import uuid
import asyncio

from langgraph.graph import StateGraph, END

from app.agents.state import ExamGenerationState
from app.agents.nodes.retriever import retriever_node
from app.agents.nodes.generator import generator_node
from app.agents.nodes.visualizer import visualizer_node
from app.agents.nodes.reviewer import reviewer_node
from app.agents.schemas import ExamGenerationRequest, ExamGenerationResponse
from app.services import pg_service
from app.logger import get_logger

logger = get_logger(__name__)


def should_retry(state: ExamGenerationState) -> str:
    """Decide the next workflow step after review."""
    is_complete = state.get("is_complete", False)
    research_goal = state.get("research_goal")

    if is_complete:
        return "pdf"

    # When the reviewer asks for more evidence, loop back to retrieval.
    if research_goal:
        return "retriever"

    return "generator"


def create_exam_graph() -> StateGraph:
    """Create the exam generation workflow.

    Flow:
        START -> Retriever -> Generator -> Visualizer -> Reviewer
                                ^           ^               |
                                |           |_______________|
                                |           |   (Rewrite)   |
                                |___________|_______________|
                                        (Research)

        Reviewer -> END (when the review passes or retries are exhausted)
    """
    workflow = StateGraph(ExamGenerationState)

    workflow.add_node("retriever", retriever_node)
    workflow.add_node("generator", generator_node)
    workflow.add_node("visualizer", visualizer_node)
    workflow.add_node("reviewer", reviewer_node)

    workflow.set_entry_point("retriever")

    workflow.add_edge("retriever", "generator")
    workflow.add_edge("generator", "visualizer")
    workflow.add_edge("visualizer", "reviewer")

    workflow.add_conditional_edges(
        "reviewer",
        should_retry,
        {
            "generator": "generator",
            "retriever": "retriever",
            "pdf": END,
        }
    )

    return workflow.compile()


async def run_exam_generation(
    request: ExamGenerationRequest
) -> ExamGenerationResponse:
    """Run the exam generation workflow and return the generated exam."""
    question_types = None
    if request.question_types:
        question_types = {
            "multiple_choice": request.question_types.multiple_choice,
            "short_answer": request.question_types.short_answer,
            "essay": request.question_types.essay,
        }
        total_questions = sum(question_types.values())
        logger.info(
            f"[ExamGraph] Starting exam generation - files={len(request.file_ids)}, "
            f"question_types={question_types}, total_questions={total_questions}"
        )
    else:
        total_questions = request.num_questions
        logger.info(
            f"[ExamGraph] Starting exam generation - files={len(request.file_ids)}, "
            f"num_questions={request.num_questions}"
        )

    initial_state: ExamGenerationState = {
        "file_ids": request.file_ids,
        "topic": request.topic or "",
        "difficulty": request.difficulty,
        "num_questions": request.num_questions,
        "question_types": question_types,
        "custom_prompt": request.custom_prompt or "",
        "context": "",
        "context_chunks": [],
        "questions": [],
        "images": {},
        "review_result": None,
        "feedback": "",
        "retry_count": 0,
        "max_retries": 3,
        "exam_name": request.exam_name or "",
        # Use an app-generated UUID so the graph can prepare related assets up front.
        "exam_id": str(uuid.uuid4()),
        "pdf_path": None,
        "warnings": [],
        "is_complete": False,
    }

    graph = create_exam_graph()
    final_state = await graph.ainvoke(initial_state)

    logger.info(f"[ExamGraph] Workflow completed - exam_id={final_state['exam_id']}")

    questions = final_state.get("questions", [])
    review_result = final_state.get("review_result")

    response = ExamGenerationResponse(
        exam_id=final_state["exam_id"],
        exam_name=final_state.get("exam_name", "Exam"),
        questions=questions,
        pdf_path=final_state.get("pdf_path"),
        warnings=final_state.get("warnings", []),
        review_score=review_result.overall_score if review_result else 0
    )

    return response


async def run_exam_generation_with_pdf(
    request: ExamGenerationRequest
) -> ExamGenerationResponse:
    """Run the workflow, optionally render a PDF, and persist the saved exam."""
    response = await run_exam_generation(request)

    if response.questions:
        try:
            from app.utils.pdf_generator import generate_exam_pdf

            pdf_path = await generate_exam_pdf(
                exam_id=response.exam_id,
                exam_name=response.exam_name,
                questions=response.questions,
            )

            response.pdf_path = pdf_path
            logger.info(f"[ExamGraph] PDF generated successfully: {pdf_path}")

        except Exception as e:
            logger.error(f"[ExamGraph] PDF generation failed: {e}")
            response.warnings.append(f"PDF generation failed: {str(e)}")

    if response.questions:
        try:
            # Derive class ownership from the selected source files before saving.
            class_id, owner_id = await _get_class_and_owner_from_files(request.file_ids)

            questions_dict = [q.model_dump() for q in response.questions]

            save_result = await asyncio.to_thread(
                pg_service.save_exam,
                response.exam_id,
                response.exam_name,
                questions_dict,
                request.file_ids,
                class_id,
                owner_id,
                request.difficulty,
                None,
                response.pdf_path,
                None,
            )

            logger.info(
                f"[ExamGraph] Exam saved successfully - "
                f"ID: {save_result['exam_id']}, title: {save_result['title']}"
            )

        except Exception as e:
            logger.error(f"[ExamGraph] Saving generated exam failed: {e}")
            response.warnings.append(f"Saving generated exam failed: {str(e)}")

    return response


async def _get_class_and_owner_from_files(file_ids: List[str]) -> tuple:
    """Look up a shared class_id and owner_id from the selected document IDs."""
    if not file_ids:
        return None, None

    try:
        from app.services.pg_db import _get_conn

        def _query():
            with _get_conn() as conn, conn.cursor() as cur:
                # Resolve the class and teacher from the selected documents.
                cur.execute("""
                    SELECT DISTINCT d.class_id, c.teacher_id
                    FROM documents d
                    LEFT JOIN classes c ON c.id = d.class_id
                    WHERE d.id = ANY(%s::uuid[]) AND d.class_id IS NOT NULL
                """, (file_ids,))
                rows = cur.fetchall()
                if rows and len(rows) == 1:
                    class_id = str(rows[0]["class_id"]) if rows[0]["class_id"] else None
                    owner_id = str(rows[0]["teacher_id"]) if rows[0]["teacher_id"] else None
                    return class_id, owner_id
                return None, None

        return await asyncio.to_thread(_query)
    except Exception as e:
        logger.warning(f"[ExamGraph] Failed to resolve class_id/owner_id: {e}")
        return None, None
