from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from models import OfficeRoundtrip


DETERMINISTIC_ZIP_TIME = (2000, 1, 1, 0, 0, 0)
DETERMINISTIC_CREATE_SYSTEM = 3
DETERMINISTIC_UNIX_MODE = 0o600


@dataclass(frozen=True)
class OfficeEngine:
    executable: str
    name: str
    version: str


class OfficeEngineError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def deterministic_external_attr(_external_attr: int) -> int:
    """Pin every XLSX ZIP member to one regular-file mode on every host."""
    return (0o100000 | DETERMINISTIC_UNIX_MODE) << 16


def normalize_xlsx(path: Path, *, table_source_path: Path | None = None) -> None:
    """Normalize Office output while restoring template-owned metadata."""
    table_members: dict[str, bytes] = {}
    worksheet_elements: dict[str, dict[str, bytes]] = {}
    if table_source_path is not None:
        with zipfile.ZipFile(table_source_path, "r") as table_source:
            for entry in table_source.infolist():
                if entry.filename.startswith(
                    "xl/worksheets/sheet"
                ) and entry.filename.endswith(".xml"):
                    payload = table_source.read(entry.filename)
                    worksheet_elements[entry.filename] = {
                        tag: match.group(0)
                        for tag in ("sheetProtection", "dataValidations")
                        for match in [
                            re.search(
                                rb"<"
                                + tag.encode()
                                + rb"\b.*?</"
                                + tag.encode()
                                + rb">",
                                payload,
                                flags=re.DOTALL,
                            )
                        ]
                        if match is not None
                    }
                if not entry.filename.startswith(
                    "xl/tables/"
                ) or not entry.filename.endswith(".xml"):
                    continue
                payload = table_source.read(entry.filename)
                root = ET.fromstring(payload)
                name = root.attrib.get("displayName") or root.attrib.get("name")
                if name:
                    table_members[name] = payload
    with zipfile.ZipFile(path, "r") as source:
        members = []
        for entry in source.infolist():
            payload = source.read(entry.filename)
            if entry.filename.startswith("xl/tables/") and entry.filename.endswith(
                ".xml"
            ):
                root = ET.fromstring(payload)
                name = root.attrib.get("displayName") or root.attrib.get("name")
                if name in table_members:
                    payload = table_members[name]
            if entry.filename in worksheet_elements:
                for tag, replacement in worksheet_elements[entry.filename].items():
                    pattern = rb"<" + tag.encode() + rb"\b.*?</" + tag.encode() + rb">"
                    if re.search(pattern, payload, flags=re.DOTALL) is None:
                        raise ValueError(
                            f"office output removed required worksheet metadata: {tag}"
                        )
                    payload = re.sub(
                        pattern,
                        lambda _match, value=replacement: value,
                        payload,
                        count=1,
                        flags=re.DOTALL,
                    )
            if entry.filename == "docProps/core.xml":
                payload = re.sub(
                    rb"<dcterms:modified[^>]*>.*?</dcterms:modified>",
                    b'<dcterms:modified xsi:type="dcterms:W3CDTF">2000-01-01T00:00:00Z</dcterms:modified>',
                    payload,
                )
            elif entry.filename == "docProps/app.xml":
                payload = re.sub(
                    rb"<Application>.*?</Application>",
                    b"<Application>AI SOW Office Engine</Application>",
                    payload,
                )
                payload = re.sub(
                    rb"<AppVersion>.*?</AppVersion>",
                    b"<AppVersion>1.0</AppVersion>",
                    payload,
                )
            members.append((entry.filename, payload, entry))
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as target:
            for name, payload, original in sorted(members, key=lambda item: item[0]):
                entry = zipfile.ZipInfo(name, DETERMINISTIC_ZIP_TIME)
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.create_system = DETERMINISTIC_CREATE_SYSTEM
                entry.external_attr = deterministic_external_attr(original.external_attr)
                entry.flag_bits = original.flag_bits
                target.writestr(entry, payload)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def discover_office_engine() -> OfficeEngine | None:
    configured = os.environ.get("AI_SOW_OFFICE_BIN")
    candidates = [
        configured,
        shutil.which("soffice"),
        shutil.which("libreoffice"),
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        executable = Path(candidate).expanduser().resolve()
        if not executable.is_file() or not os.access(executable, os.X_OK):
            continue
        try:
            completed = subprocess.run(
                [str(executable), "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        version = (completed.stdout or completed.stderr).strip()
        if completed.returncode == 0 and "LibreOffice" in version:
            return OfficeEngine(
                executable=str(executable),
                name="LibreOffice",
                version=version,
            )
    return None


def require_office_engine() -> OfficeEngine:
    engine = discover_office_engine()
    if engine is None:
        raise OfficeEngineError(
            "OFFICE_ENGINE_UNAVAILABLE",
            "未找到可用于重算工作簿的办公软件。",
        )
    return engine


def recalculate_workbook(
    candidate_path: Path,
    output_path: Path,
    engine: OfficeEngine,
) -> OfficeRoundtrip:
    candidate = Path(candidate_path).resolve()
    output = Path(output_path).resolve()
    if not candidate.is_file():
        raise OfficeEngineError(
            "OFFICE_ENGINE_INPUT_MISSING",
            "待重算工作簿不存在。",
        )
    if output.exists():
        raise OfficeEngineError(
            "OFFICE_ENGINE_OUTPUT_EXISTS",
            "重算输出路径已存在。",
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=".office-", dir=output.parent)
    ).resolve()
    try:
        input_root = temporary / "input"
        converted_root = temporary / "converted"
        profile_root = temporary / "profile"
        input_root.mkdir()
        converted_root.mkdir()
        profile_root.mkdir()
        isolated_input = input_root / "candidate.xlsx"
        shutil.copy2(candidate, isolated_input)
        try:
            completed = subprocess.run(
                [
                    engine.executable,
                    f"-env:UserInstallation={profile_root.as_uri()}",
                    "--headless",
                    "--convert-to",
                    "xlsx",
                    "--outdir",
                    str(converted_root),
                    str(isolated_input),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired as error:
            raise OfficeEngineError(
                "OFFICE_ENGINE_RECALCULATION_TIMEOUT",
                "办公软件重算工作簿超时。",
            ) from error
        converted = converted_root / "candidate.xlsx"
        if completed.returncode != 0 or not converted.is_file():
            raise OfficeEngineError(
                "OFFICE_ENGINE_RECALCULATION_FAILED",
                "办公软件未能完成工作簿重算和保存。",
            )
        os.replace(converted, output)
        normalize_xlsx(output, table_source_path=candidate)
        return OfficeRoundtrip(
            engine={"name": engine.name, "version": engine.version},
            output_path=str(output),
        )
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
