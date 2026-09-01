from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
import pytest


SKILL_ROOT = Path(__file__).parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from source_readers import SourceReadError, extract_document  # noqa: E402


def synthetic_source(tmp_path: Path, suffix: str) -> Path:
    path = tmp_path / f"source{suffix}"
    if suffix == ".md":
        path.write_text(
            "# Refund\n\nUser submits a refund request and sees the result.\n",
            encoding="utf-8",
        )
    elif suffix == ".txt":
        path.write_text(
            "Refund request\n\nUser sees the processing result.\n",
            encoding="utf-8",
        )
    elif suffix in {".html", ".htm"}:
        path.write_text(
            '<button id="refund">Submit refund</button>\n'
            '<p id="status">Waiting</p>\n'
            '<script>refund.onclick = () => { status.textContent = "Submitted"; };</script>\n',
            encoding="utf-8",
        )
    elif suffix in {".ts", ".tsx"}:
        path.write_text(
            "export function RefundButton() {\n"
            "  const [status, setStatus] = useState('waiting');\n"
            "  return <button onClick={() => setStatus('submitted')}>Refund</button>;\n"
            "}\n",
            encoding="utf-8",
        )
    elif suffix == ".xlsx":
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Refund"
        sheet.append(["Feature", "Outcome"])
        sheet.append(["Refund request", "User sees the processing result"])
        workbook.save(path)
    else:
        raise AssertionError(suffix)
    return path


@pytest.mark.parametrize(
    ("role", "suffix"),
    [
        ("PRD", ".md"),
        ("HLD", ".md"),
        ("PRIOR_SOW", ".xlsx"),
        ("SUPPLEMENT", ".md"),
        ("SUPPLEMENT", ".txt"),
        ("SUPPLEMENT", ".html"),
        ("SUPPLEMENT", ".htm"),
        ("SUPPLEMENT", ".ts"),
        ("SUPPLEMENT", ".tsx"),
        ("SUPPLEMENT", ".xlsx"),
    ],
)
def test_supported_role_format_pairs_produce_non_page_non_line_anchors(
    tmp_path: Path, role: str, suffix: str
) -> None:
    anchors = extract_document(
        synthetic_source(tmp_path, suffix), source_id="source-main", role=role
    )
    assert anchors
    assert all(
        "page=" not in anchor.locator and "line=" not in anchor.locator
        for anchor in anchors
    )
    assert all(anchor.source_id == "source-main" for anchor in anchors)


@pytest.mark.parametrize(
    ("role", "suffix"),
    [
        ("PRD", ".txt"),
        ("PRD", ".html"),
        ("PRD", ".xlsx"),
        ("HLD", ".ts"),
        ("HLD", ".xlsx"),
        ("PRIOR_SOW", ".md"),
        ("PRIOR_SOW", ".pdf"),
        ("SUPPLEMENT", ".pdf"),
        ("SUPPLEMENT", ".docx"),
    ],
)
def test_unsupported_role_format_pairs_are_rejected(
    tmp_path: Path, role: str, suffix: str
) -> None:
    source = tmp_path / f"source{suffix}"
    source.write_bytes(b"synthetic source")
    with pytest.raises(SourceReadError) as captured:
        extract_document(source, source_id="source-main", role=role)
    assert captured.value.code == "SOURCE_FORMAT_UNSUPPORTED"


@pytest.mark.parametrize("suffix", [".html", ".ts", ".tsx"])
def test_prototype_source_preserves_function_and_interaction_evidence(
    tmp_path: Path, suffix: str
) -> None:
    anchors = extract_document(
        synthetic_source(tmp_path, suffix),
        source_id="prototype-demo",
        role="SUPPLEMENT",
    )
    text = " ".join(anchor.normalized_text for anchor in anchors)
    assert "Refund" in text or "refund" in text
    assert "Submitted" in text or "submitted" in text
    assert "button" in text


def test_same_text_under_moved_heading_keeps_semantic_hash(tmp_path: Path) -> None:
    before = tmp_path / "before.md"
    after = tmp_path / "after.md"
    before.write_text("## 原章节\n\n退款必须可追踪\n", encoding="utf-8")
    after.write_text("## 新章节\n\n退款必须可追踪\n", encoding="utf-8")

    def semantic_anchor(path: Path):
        return next(
            anchor
            for anchor in extract_document(path, source_id="prd-main", role="PRD")
            if anchor.normalized_text == "退款必须可追踪"
        )

    assert semantic_anchor(before).sha256 == semantic_anchor(after).sha256


def test_duplicate_semantic_anchors_get_ordered_suffixes(tmp_path: Path) -> None:
    source = tmp_path / "duplicate.txt"
    source.write_text("相同结果\n\n相同结果\n", encoding="utf-8")
    anchors = extract_document(source, source_id="supplement-main", role="SUPPLEMENT")
    assert [anchor.anchor_id[-5:] for anchor in anchors] == ["-0001", "-0002"]
    assert anchors[0].sha256 == anchors[1].sha256


@pytest.mark.parametrize(
    ("name", "payload", "expected_code"),
    [
        ("blank.md", b" \n", "SOURCE_BLANK"),
        ("placeholder.md", b"# TODO\n\nTBD\n", "SOURCE_PLACEHOLDER_ONLY"),
        ("invalid.ts", b"\xff\xfe\x00", "SOURCE_UNREADABLE"),
        ("binary.html", b"valid\x00text", "SOURCE_UNREADABLE"),
    ],
)
def test_invalid_text_sources_return_stable_codes(
    tmp_path: Path, name: str, payload: bytes, expected_code: str
) -> None:
    source = tmp_path / name
    source.write_bytes(payload)
    role = "PRD" if source.suffix == ".md" else "SUPPLEMENT"
    with pytest.raises(SourceReadError) as captured:
        extract_document(source, source_id="source-main", role=role)
    assert captured.value.code == expected_code
