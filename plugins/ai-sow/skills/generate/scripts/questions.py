from __future__ import annotations

from collections.abc import Mapping, Sequence

from contracts import canonical_json_bytes, sha256_bytes
from models import Diagnostic, SourceAnchor


def _diagnostic(code: str, message: str, path: str) -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details={})


def question_sha256(question: Mapping[str, object]) -> str:
    return sha256_bytes(canonical_json_bytes(question))


def _normalized_text(value: object) -> str:
    return " ".join(str(value).split())


_TYPED_GAP_SOURCE_ROLES = {
    "PRD",
    "DEMO",
    "APPROVED_DESIGN",
    "PRIOR_SOW",
    "SUPPLEMENT",
    "USER_DECISION",
}


def validate_typed_gap_question(
    question: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    text_fields = (
        "questionId",
        "question",
        "whyAsked",
        "unansweredConsequence",
        "requiredSourceRole",
    )
    for field in text_fields:
        value = question.get(field)
        if not isinstance(value, str) or not value.strip():
            diagnostics.append(
                _diagnostic(
                    "QUESTION_TYPED_FIELD_REQUIRED",
                    "结构化问题缺少非空字段。",
                    f"/{field}",
                )
            )
    for field in ("subjectIds", "answerDetermines", "checkedEvidenceIds"):
        value = question.get(field)
        if not isinstance(value, list) or not value or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            diagnostics.append(
                _diagnostic(
                    "QUESTION_TYPED_FIELD_REQUIRED",
                    "结构化问题缺少非空列表字段。",
                    f"/{field}",
                )
            )
    role = question.get("requiredSourceRole")
    if isinstance(role, str) and role not in _TYPED_GAP_SOURCE_ROLES:
        diagnostics.append(
            _diagnostic(
                "QUESTION_REQUIRED_SOURCE_ROLE_INVALID",
                "结构化问题的 requiredSourceRole 不受支持。",
                "/requiredSourceRole",
            )
        )
    return tuple(sorted(diagnostics, key=lambda item: (item.path, item.code, item.message)))


def _question_wording(question: Mapping[str, object]) -> tuple[str, str, str, str]:
    if "whyAsked" in question:
        answer_determines = question.get("answerDetermines")
        if isinstance(answer_determines, list):
            determines_text = "；".join(
                _normalized_text(item) for item in answer_determines
            )
        else:
            determines_text = _normalized_text(answer_determines)
        return (
            _normalized_text(question.get("question")),
            _normalized_text(question.get("whyAsked")),
            determines_text,
            _normalized_text(question.get("unansweredConsequence")),
        )
    return (
        _normalized_text(question.get("question")),
        _normalized_text(question.get("reason")),
        _normalized_text(question.get("decisionImpact")),
        _normalized_text(question.get("unansweredEffect")),
    )


def question_answer_anchors(
    questions: Sequence[Mapping[str, object]],
    answers: Sequence[Mapping[str, object]],
) -> tuple[SourceAnchor, ...]:
    questions_by_id = {str(question["questionId"]): question for question in questions}
    anchors: list[SourceAnchor] = []
    for answer in answers:
        question_id = str(answer["questionId"])
        question = questions_by_id[question_id]
        question_text, why_asked, answer_determines, unanswered = _question_wording(
            question
        )
        identity = sha256_bytes(canonical_json_bytes({"questionId": question_id}))
        normalized_text = "\n".join(
            (
                f"问题：{question_text}",
                f"为什么要问：{why_asked}",
                f"答案决定什么：{answer_determines}",
                f"未回答后果：{unanswered}",
                f"答案：{_normalized_text(answer['answer'])}",
            )
        )
        anchors.append(
            SourceAnchor(
                anchor_id=f"question-answer-anchor-{identity}",
                source_id=f"question-answer-{identity}",
                kind="QUESTION_ANSWER",
                locator=f"question:{question_id}",
                normalized_text=normalized_text,
                sha256=sha256_bytes(
                    canonical_json_bytes(
                        {"question": question, "answer": answer["answer"]}
                    )
                ),
            )
        )
    return tuple(anchors)


def validate_question_answers(
    questions: Sequence[Mapping[str, object]],
    answers: Sequence[Mapping[str, object]],
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    question_ids: set[str] = set()
    for index, question in enumerate(questions):
        question_id = str(question["questionId"])
        if question_id in question_ids:
            diagnostics.append(
                _diagnostic(
                    "QUESTION_ID_DUPLICATE",
                    "问题 questionId 必须唯一。",
                    f"/questions/{index}/questionId",
                )
            )
        question_ids.add(question_id)
    if diagnostics:
        return tuple(
            sorted(diagnostics, key=lambda item: (item.path, item.code, item.message))
        )

    expected = {str(item["questionId"]): question_sha256(item) for item in questions}
    seen: set[str] = set()
    for index, answer in enumerate(answers):
        question_id = str(answer.get("questionId", ""))
        path = f"/questionnaireAnswers/{index}"
        if question_id not in expected:
            diagnostics.append(
                _diagnostic(
                    "QUESTION_ANSWER_UNKNOWN_QUESTION",
                    "答案引用了不存在的问题。",
                    f"{path}/questionId",
                )
            )
            continue
        if question_id in seen:
            diagnostics.append(
                _diagnostic(
                    "QUESTION_ANSWER_DUPLICATE",
                    "同一问题只能有一个答案。",
                    f"{path}/questionId",
                )
            )
        seen.add(question_id)
        if answer.get("questionSha256") != expected[question_id]:
            diagnostics.append(
                _diagnostic(
                    "QUESTION_ANSWER_HASH_MISMATCH",
                    "答案未绑定当前问题包。",
                    f"{path}/questionSha256",
                )
            )
    return tuple(sorted(diagnostics, key=lambda item: (item.path, item.code, item.message)))
