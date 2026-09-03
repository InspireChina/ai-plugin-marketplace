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


def question_answer_anchors(
    questions: Sequence[Mapping[str, object]],
    answers: Sequence[Mapping[str, object]],
) -> tuple[SourceAnchor, ...]:
    questions_by_id = {str(question["questionId"]): question for question in questions}
    anchors: list[SourceAnchor] = []
    for answer in answers:
        question_id = str(answer["questionId"])
        question = questions_by_id[question_id]
        identity = sha256_bytes(canonical_json_bytes({"questionId": question_id}))
        normalized_text = "\n".join(
            (
                f"问题：{_normalized_text(question['question'])}",
                f"为什么要问：{_normalized_text(question['reason'])}",
                f"答案决定什么：{_normalized_text(question['decisionImpact'])}",
                f"未回答后果：{_normalized_text(question['unansweredEffect'])}",
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
