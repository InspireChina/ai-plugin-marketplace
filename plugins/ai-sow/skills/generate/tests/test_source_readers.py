from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import openpyxl
import pytest


SKILL_ROOT = Path(__file__).parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from source_readers import SourceReadError, extract_document  # noqa: E402


def write_minimal_pdf(path: Path, text: str | None) -> Path:
    stream = b"" if text is None else f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode())
        payload.extend(obj)
        payload.extend(b"\nendobj\n")
    xref = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(payload)
    return path


def synthetic_source(tmp_path: Path, suffix: str) -> Path:
    path = tmp_path / f"source{suffix}"
    if suffix == ".md":
        path.write_text("# Refund\n\nUser submits a refund request and sees the result.\n", encoding="utf-8")
    elif suffix == ".txt":
        path.write_text("Refund request\n\nUser sees the processing result.\n", encoding="utf-8")
    elif suffix == ".docx":
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
            )
            archive.writestr(
                "word/document.xml",
                '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Refund</w:t></w:r></w:p><w:p><w:r><w:t>User sees the refund result.</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Status</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Completed</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>',
            )
    elif suffix == ".pdf":
        write_minimal_pdf(path, "Refund request result")
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


@pytest.mark.parametrize("suffix", [".md", ".txt", ".docx", ".pdf", ".xlsx"])
def test_supported_sources_produce_non_page_non_line_anchors(
    tmp_path: Path, suffix: str
) -> None:
    anchors = extract_document(
        synthetic_source(tmp_path, suffix), source_id="prd-main", role="PRD"
    )
    assert anchors
    assert all("page=" not in anchor.locator and "line=" not in anchor.locator for anchor in anchors)
    assert all(anchor.source_id == "prd-main" for anchor in anchors)


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
    anchors = extract_document(source, source_id="prd-main", role="PRD")
    assert [anchor.anchor_id[-5:] for anchor in anchors] == ["-0001", "-0002"]
    assert anchors[0].sha256 == anchors[1].sha256


@pytest.mark.parametrize(
    ("source_factory", "expected_code"),
    [
        (lambda root: (root / "legacy.doc"), "SOURCE_FORMAT_UNSUPPORTED"),
        (lambda root: (root / "corrupt.docx"), "SOURCE_UNREADABLE"),
        (lambda root: (root / "blank.md"), "SOURCE_BLANK"),
        (lambda root: (root / "placeholder.md"), "SOURCE_PLACEHOLDER_ONLY"),
    ],
)
def test_invalid_sources_return_stable_codes(
    tmp_path: Path, source_factory, expected_code: str
) -> None:
    source = source_factory(tmp_path)
    if source.suffix == ".doc":
        source.write_bytes(b"legacy")
    elif source.suffix == ".docx":
        source.write_bytes(b"not-a-zip")
    elif source.name == "blank.md":
        source.write_text(" \n", encoding="utf-8")
    else:
        source.write_text("# TODO\n\nTBD\n", encoding="utf-8")
    with pytest.raises(SourceReadError) as captured:
        extract_document(source, source_id="prd-main", role="PRD")
    assert captured.value.code == expected_code


def test_no_text_pdf_is_rejected(tmp_path: Path) -> None:
    source = write_minimal_pdf(tmp_path / "scan.pdf", None)
    with pytest.raises(SourceReadError) as captured:
        extract_document(source, source_id="hld-main", role="HLD")
    assert captured.value.code == "SOURCE_NO_TEXT"
