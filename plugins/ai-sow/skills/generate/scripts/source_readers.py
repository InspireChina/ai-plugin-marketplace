from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl

from contracts import canonical_json_bytes
from models import SourceAnchor


SOURCE_ROLES = frozenset({"PRD", "HLD", "PRIOR_SOW", "SUPPLEMENT"})
ROLE_SUFFIXES = {
    "PRD": frozenset({".md"}),
    "HLD": frozenset({".md"}),
    "PRIOR_SOW": frozenset({".xlsx"}),
}
UNSUPPORTED_PARSED_SUFFIXES = frozenset(
    {
        ".doc",
        ".docm",
        ".docx",
        ".odt",
        ".pdf",
        ".ppt",
        ".pptm",
        ".pptx",
        ".rtf",
        ".xls",
        ".xlsb",
        ".xlsm",
    }
)
TEXT_MEDIA_TYPES = {
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
    ".ts": "text/typescript",
    ".tsx": "text/typescript",
}
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PLACEHOLDER_TERMS = frozenset(
    {
        "todo",
        "tbd",
        "placeholder",
        "待补充",
        "待填写",
        "待定",
        "填写",
        "示例",
        "n/a",
        "na",
        "无",
    }
)


class SourceReadError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _normalize(text: object) -> str:
    return " ".join(unicodedata.normalize("NFC", str(text)).split())


def _markdown_anchors(text: str) -> list[tuple[str, str, str]]:
    anchors: list[tuple[str, str, str]] = []
    headings: list[str] = []
    paragraph: list[str] = []
    paragraph_index = 0
    table_index = 0

    def section() -> str:
        return "/".join(headings) if headings else "document"

    def flush_paragraph() -> None:
        nonlocal paragraph_index
        normalized = _normalize(" ".join(paragraph))
        paragraph.clear()
        if not normalized:
            return
        paragraph_index += 1
        anchors.append(
            ("PARAGRAPH", f"section:{section()}/paragraph:{paragraph_index:04d}", normalized)
        )

    for line in text.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            title = _normalize(heading.group(2))
            headings[level - 1 :] = [title]
            anchors.append(("HEADING", f"heading:{section()}", title))
            continue
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_paragraph()
            cells = [_normalize(cell) for cell in stripped.strip("|").split("|")]
            if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                continue
            normalized = " | ".join(cell for cell in cells if cell)
            if normalized:
                table_index += 1
                anchors.append(
                    ("TABLE_ROW", f"section:{section()}/table-row:{table_index:04d}", normalized)
                )
            continue
        if not stripped:
            flush_paragraph()
        else:
            paragraph.append(stripped)
    flush_paragraph()
    return anchors


def _text_anchors(text: str) -> list[tuple[str, str, str]]:
    paragraphs = [
        normalized
        for block in re.split(r"\n\s*\n", text)
        if (normalized := _normalize(block))
    ]
    return [
        ("PARAGRAPH", f"paragraph:{index:04d}", paragraph)
        for index, paragraph in enumerate(paragraphs, 1)
    ]


def _xlsx_anchors(path: Path) -> list[tuple[str, str, str]]:
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
        anchors: list[tuple[str, str, str]] = []
        for worksheet in workbook.worksheets:
            semantic_row = 0
            for row in worksheet.iter_rows(values_only=True):
                cells = [_normalize(value) for value in row if value is not None]
                normalized = " | ".join(cell for cell in cells if cell)
                if not normalized:
                    continue
                semantic_row += 1
                anchors.append(
                    (
                        "SHEET_ROW",
                        f"sheet:{worksheet.title}/row:{semantic_row:04d}",
                        normalized,
                    )
                )
        workbook.close()
        return anchors
    except Exception as error:
        raise SourceReadError("SOURCE_UNREADABLE", "XLSX 无法读取。") from error


def _source_kind(path: Path, role: str) -> str:
    if role not in SOURCE_ROLES:
        raise SourceReadError("SOURCE_ROLE_INVALID", "来源角色不受支持。")
    suffix = path.suffix.casefold()
    if role in ROLE_SUFFIXES:
        if suffix not in ROLE_SUFFIXES[role]:
            raise SourceReadError("SOURCE_FORMAT_UNSUPPORTED", "来源文件格式不受支持。")
        return "MARKDOWN" if suffix == ".md" else "XLSX"
    if suffix == ".xlsx":
        return "XLSX"
    if suffix in UNSUPPORTED_PARSED_SUFFIXES:
        raise SourceReadError("SOURCE_FORMAT_UNSUPPORTED", "来源文件格式不受支持。")
    return "MARKDOWN" if suffix == ".md" else "TEXT"


def source_media_type(path: Path, role: str) -> str:
    kind = _source_kind(path, role)
    if kind == "XLSX":
        return XLSX_MEDIA_TYPE
    return TEXT_MEDIA_TYPES.get(path.suffix.casefold(), "text/plain")


def _read_utf8_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if any(
        unicodedata.category(character) == "Cc" and character not in "\n\r\t"
        for character in text
    ):
        raise SourceReadError("SOURCE_UNREADABLE", "文本来源包含二进制控制字符。")
    return text


def _is_placeholder_only(texts: list[str]) -> bool:
    tokens: list[str] = []
    for text in texts:
        simplified = re.sub(r"[^\w\u3400-\u9fff/]+", " ", text.casefold())
        tokens.extend(token for token in simplified.split() if token)
    return bool(tokens) and all(token in PLACEHOLDER_TERMS for token in tokens)


def _looks_like_unrelated_sample(texts: list[str]) -> bool:
    combined = " ".join(texts).casefold()
    has_sample_marker = any(marker in combined for marker in ("仅供参考", "示例模板", "sample template"))
    has_fill_marker = any(marker in combined for marker in ("请填写", "待填写", "replace this"))
    return has_sample_marker and has_fill_marker


def extract_document(
    path: Path,
    *,
    source_id: str,
    role: str,
) -> tuple[SourceAnchor, ...]:
    kind = _source_kind(path, role)
    if not path.is_file():
        raise SourceReadError("SOURCE_UNREADABLE", "来源文件无法读取。")

    try:
        if kind in {"MARKDOWN", "TEXT"}:
            text = _read_utf8_text(path)
            raw = _markdown_anchors(text) if kind == "MARKDOWN" else _text_anchors(text)
        else:
            raw = _xlsx_anchors(path)
    except SourceReadError:
        raise
    except UnicodeDecodeError as error:
        raise SourceReadError("SOURCE_UNREADABLE", "文本来源不是有效 UTF-8。") from error
    except OSError as error:
        raise SourceReadError("SOURCE_UNREADABLE", "来源文件无法读取。") from error

    normalized = [(kind, locator, _normalize(text)) for kind, locator, text in raw]
    normalized = [item for item in normalized if item[2]]
    texts = [item[2] for item in normalized]
    if not texts:
        raise SourceReadError("SOURCE_BLANK", "来源文件没有有效内容。")
    if _is_placeholder_only(texts):
        raise SourceReadError("SOURCE_PLACEHOLDER_ONLY", "来源文件只有占位内容。")
    if _looks_like_unrelated_sample(texts):
        raise SourceReadError("SOURCE_IRRELEVANT_SAMPLE", "来源文件是未填写的无关样例。")

    identities = [
        hashlib.sha256(canonical_json_bytes([source_id, kind, text])).hexdigest()
        for kind, _, text in normalized
    ]
    totals = Counter(identities)
    occurrences: defaultdict[str, int] = defaultdict(int)
    anchors: list[SourceAnchor] = []
    for (kind, locator, text), identity in zip(normalized, identities, strict=True):
        occurrences[identity] += 1
        anchor_id = f"anchor-{identity[:16]}"
        if totals[identity] > 1:
            anchor_id += f"-{occurrences[identity]:04d}"
        anchors.append(
            SourceAnchor(
                anchor_id=anchor_id,
                source_id=source_id,
                kind=kind,  # type: ignore[arg-type]
                locator=locator,
                normalized_text=text,
                sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )
    return tuple(anchors)
