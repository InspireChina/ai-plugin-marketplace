from __future__ import annotations

import hashlib
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree

import openpyxl
from pypdf import PdfReader

from contracts import canonical_json_bytes
from models import SourceAnchor


SUPPORTED_SUFFIXES = frozenset({".md", ".txt", ".docx", ".pdf", ".xlsx"})
SOURCE_ROLES = frozenset({"PRD", "HLD", "PRIOR_SOW", "SUPPLEMENT"})
WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{WORD_NAMESPACE}}}"
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


def _docx_anchors(path: Path) -> list[tuple[str, str, str]]:
    try:
        with zipfile.ZipFile(path) as archive:
            document = ElementTree.fromstring(archive.read("word/document.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as error:
        raise SourceReadError("SOURCE_UNREADABLE", "DOCX 无法读取。") from error

    anchors: list[tuple[str, str, str]] = []
    headings: list[str] = []
    paragraph_index = 0
    table_index = 0
    body = document.find(f"{W}body")
    if body is None:
        return anchors

    def text_of(element: ElementTree.Element) -> str:
        return _normalize("".join(node.text or "" for node in element.iter(f"{W}t")))

    def section() -> str:
        return "/".join(headings) if headings else "document"

    for element in body:
        if element.tag == f"{W}p":
            text = text_of(element)
            if not text:
                continue
            style = element.find(f"{W}pPr/{W}pStyle")
            style_name = style.get(f"{W}val", "") if style is not None else ""
            heading = re.match(r"(?:Heading|标题)\s*([1-6])$", style_name, re.IGNORECASE)
            if heading:
                level = int(heading.group(1))
                headings[level - 1 :] = [text]
                anchors.append(("HEADING", f"heading:{section()}", text))
            else:
                paragraph_index += 1
                anchors.append(
                    ("PARAGRAPH", f"section:{section()}/paragraph:{paragraph_index:04d}", text)
                )
        elif element.tag == f"{W}tbl":
            for row in element.findall(f"{W}tr"):
                cells = [text_of(cell) for cell in row.findall(f"{W}tc")]
                normalized = " | ".join(cell for cell in cells if cell)
                if normalized:
                    table_index += 1
                    anchors.append(
                        ("TABLE_ROW", f"table:{table_index:04d}", normalized)
                    )
    return anchors


def _pdf_anchors(path: Path) -> list[tuple[str, str, str]]:
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise SourceReadError("SOURCE_ENCRYPTED_PDF", "加密 PDF 不受支持。")
        paragraphs: list[str] = []
        for page in reader.pages:
            extracted = page.extract_text() or ""
            paragraphs.extend(
                normalized
                for block in re.split(r"\n\s*\n|\n", extracted)
                if (normalized := _normalize(block))
            )
    except SourceReadError:
        raise
    except Exception as error:
        raise SourceReadError("SOURCE_UNREADABLE", "PDF 无法读取。") from error
    if not paragraphs:
        raise SourceReadError("SOURCE_NO_TEXT", "PDF 未包含可提取文本。")
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
    if role not in SOURCE_ROLES:
        raise SourceReadError("SOURCE_ROLE_INVALID", "来源角色不受支持。")
    suffix = path.suffix.casefold()
    if suffix not in SUPPORTED_SUFFIXES:
        raise SourceReadError("SOURCE_FORMAT_UNSUPPORTED", "来源文件格式不受支持。")
    if not path.is_file():
        raise SourceReadError("SOURCE_UNREADABLE", "来源文件无法读取。")

    try:
        if suffix in {".md", ".txt"}:
            text = path.read_text(encoding="utf-8")
            raw = _markdown_anchors(text) if suffix == ".md" else _text_anchors(text)
        elif suffix == ".docx":
            raw = _docx_anchors(path)
        elif suffix == ".pdf":
            raw = _pdf_anchors(path)
        else:
            raw = _xlsx_anchors(path)
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
