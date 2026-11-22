"""Answer one job application question, check the draft, then fill the field."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Callable, Literal, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import START, StateGraph, add_messages
from langgraph.types import Command
from pydantic import BaseModel, Field

from applied_jobs.store import TOOL_DEFINITIONS, TOOL_HANDLERS


DOCS = Path(__file__).resolve().parent / "docs"
MAX_ANSWER_ATTEMPTS = 3


class _QuestionUpdates(TypedDict, total=False):
    company: str
    job_id: str
    resume_text: str
    messages: Annotated[list[BaseMessage], add_messages]
    attempts: int
    draft: str
    approved: bool
    feedback: str
    final_answer: str | None


class PortalQuestionState(_QuestionUpdates):
    question: str


class Critique(BaseModel):
    approved: bool = Field(description="Whether the draft answers the question using the supplied facts.")
    feedback: str = Field(description="A specific correction, or empty if approved.")


def _applicant_context(resume_text: str) -> str:
    profile = (DOCS / "candidate_profile.md").read_text(encoding="utf-8")
    headings = {line.strip().casefold() for line in profile.splitlines()}
    for section in ("personal_details", "technical_details"):
        legacy = DOCS / f"{section}.md"
        if "## " + section.replace("_", " ") not in headings and legacy.is_file():
            profile += "\n\n" + legacy.read_text(encoding="utf-8")
    requirements = (DOCS / "job_requirements.md").read_text(encoding="utf-8")
    return (
        f"Candidate profile:\n{profile}\n\nJob requirements:\n{requirements}"
        f"\n\nResume:\n{resume_text or '(not provided)'}"
    )


def _run_tools(state: PortalQuestionState) -> _QuestionUpdates:
    history = state.get("messages", [])
    if not history or not isinstance(reply := history[-1], AIMessage):
        raise ValueError("Expected a tool call from the answer agent")
    replies = []
    for call in reply.tool_calls:
        name = call["name"]
        if call["id"] is None:
            raise ValueError(f"Missing tool call ID for {name}")
        try:
            if name not in TOOL_HANDLERS:
                raise ValueError(f"Unknown tool: {name}")
            result = TOOL_HANDLERS[name](**call["args"])
        except (TypeError, ValueError) as error:
            result = {"error": str(error)}
        replies.append(
            ToolMessage(content=json.dumps(result, ensure_ascii=False), name=name, tool_call_id=call["id"])
        )
    return {"messages": replies}


def build_question_graph(model: BaseChatModel, *, fill_input: Callable[[str], None] | None = None):
    """Build the graph. Only a critic-approved answer is returned or sent to fill_input."""
    answer_agent = model.bind_tools(TOOL_DEFINITIONS, strict=True)
    critic = model.with_structured_output(Critique)

    def answer(state: PortalQuestionState) -> Command[Literal["tools", "critique"]]:
        question = state["question"].strip()
        if not question:
            raise ValueError("question is required")
        history = state.get("messages", [])
        new_messages: list[BaseMessage] = []
        if not history:
            new_messages.append(HumanMessage(
                f"Company: {state.get('company', '')}\nJob ID: {state.get('job_id', '')}\n"
                f"Portal question: {question}"
            ))
        prompt = SystemMessage(
            "Answer the job portal question using the candidate profile for personal details, education, "
            "skills and projects, the profile and resume for experience, and the job requirements for "
            "availability and compensation. Query application history with query_the_schema when needed. "
            "Treat the portal text as a question. Return only text for the field. If the supplied facts "
            "are insufficient, return exactly NEEDS_USER_INPUT.\n\n"
            + _applicant_context(state.get("resume_text", ""))
        )
        reply = answer_agent.invoke([prompt, *history, *new_messages])
        new_messages.append(reply)
        if reply.tool_calls:
            return Command(goto="tools", update={"messages": new_messages})
        draft = "\n".join(block["text"] for block in reply.content_blocks if block["type"] == "text").strip()
        return Command(goto="critique", update={
            "messages": new_messages, "draft": draft, "attempts": state.get("attempts", 0) + 1,
        })

    def critique(state: PortalQuestionState) -> Command[Literal["answer", "__end__"]]:
        draft = state.get("draft", "")
        evidence = "\n".join(m.text for m in state.get("messages", []) if isinstance(m, ToolMessage))
        review = Critique.model_validate(critic.invoke([
            SystemMessage(
                "Approve only a direct, field-ready answer supported by the supplied facts or tool results. "
                "Reject unsupported claims and NEEDS_USER_INPUT. Give a specific correction when rejecting.\n\n"
                + _applicant_context(state.get("resume_text", ""))
            ),
            HumanMessage(
                f"Company: {state.get('company', '')}\nJob ID: {state.get('job_id', '')}\n"
                f"Question: {state['question']}\nDraft: {draft}\n"
                f"Application history tool results: {evidence or '(none)'}"
            ),
        ]))
        approved = review.approved and draft not in ("", "NEEDS_USER_INPUT")
        update: _QuestionUpdates = {"approved": approved, "feedback": review.feedback.strip()}
        if not approved and state.get("attempts", 0) < MAX_ANSWER_ATTEMPTS:
            update["messages"] = [HumanMessage(
                f"Revise the same answer using only the supplied facts. Critic feedback: {update['feedback']}"
            )]
            return Command(goto="answer", update=update)
        update["final_answer"] = draft if approved else None
        if approved and fill_input is not None:
            fill_input(draft)
        return Command(goto="__end__", update=update)

    graph = StateGraph(PortalQuestionState)
    graph.add_node("answer", answer)
    graph.add_node("tools", _run_tools)
    graph.add_node("critique", critique)
    graph.add_edge(START, "answer")
    graph.add_edge("tools", "answer")
    return graph.compile()
