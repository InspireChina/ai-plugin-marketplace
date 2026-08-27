from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator


# Windows 控制台默认使用本地代码页（如 cp936），会把中文结构化输出写成非 UTF-8 字节。
# 调用方按 UTF-8 读取 stdout/stderr，这里显式固定编码，与 POSIX 行为保持一致。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.handoff import (
    Artifact,
    MatchResult,
    OwnerContract,
    canonical_json_bytes,
    match_owner,
    sha256_bytes,
)
from runtime.project_io import ProjectFiles, ProjectIOError
from workbook import write_workbook


PLUGIN_VERSION = "0.1.0"
PACKAGE_ALGORITHM = "ai-sow-package-v1"
GENERATOR_CONTRACT = "receipt-only-v1"
PROJECT_PATH = ".ai-sow/project.json"
TEMPLATE_PATH = ".ai-sow/templates/sow-template.xlsx"
OUTPUTS_PATH = ".ai-sow/outputs"

DATA_PATHS = {
    "sourceRequirements": ".ai-sow/data/analyze-requirement/requirements.json",
    "asis": ".ai-sow/data/analyze-as-is/asis.json",
    "design": ".ai-sow/data/generate-design/design.json",
    "derivedRequirements": ".ai-sow/data/generate-design/requirements.json",
    "delivery": ".ai-sow/data/generate-story/delivery.json",
    "estimate": ".ai-sow/data/generate-task/estimate.json",
}
REVIEW_PATHS = {
    "analyzeRequirement": ".ai-sow/reviews/analyze-requirement.md",
    "analyzeAsIs": ".ai-sow/reviews/analyze-as-is.md",
    "generateDesign": ".ai-sow/reviews/generate-design.md",
    "generateStory": ".ai-sow/reviews/generate-story.md",
    "generateTask": ".ai-sow/reviews/generate-task.md",
}
VALIDATION_PATHS = {
    "analyzeRequirement": ".ai-sow/validation/analyze-requirement.json",
    "analyzeAsIs": ".ai-sow/validation/analyze-as-is.json",
    "generateDesign": ".ai-sow/validation/generate-design.json",
    "generateStory": ".ai-sow/validation/generate-story.json",
    "generateTask": ".ai-sow/validation/generate-task.json",
}
PACKAGE_DATA_PATHS = {
    key: f"sources/{path.removeprefix('.ai-sow/')}" for key, path in DATA_PATHS.items()
}
PACKAGE_REVIEW_PATHS = {
    key: f"sources/{path.removeprefix('.ai-sow/')}" for key, path in REVIEW_PATHS.items()
}
PACKAGE_VALIDATION_PATHS = {
    key: path.removeprefix(".ai-sow/") for key, path in VALIDATION_PATHS.items()
}
PACKAGE_TEMPLATE_PATH = "sources/templates/sow-template.xlsx"

REQUIREMENT_CONTRACT = OwnerContract(
    subject="analyze-requirement",
    contract_ids=("urn:ai-sow:analyze-requirement:source-requirements:0.1",),
    validation_path=VALIDATION_PATHS["analyzeRequirement"],
    reviews=(("approvedReview", REVIEW_PATHS["analyzeRequirement"]),),
    outputs=(("requirements", DATA_PATHS["sourceRequirements"]),),
)
ASIS_CONTRACT = OwnerContract(
    subject="analyze-as-is",
    contract_ids=("urn:ai-sow:analyze-as-is:asis:0.1",),
    validation_path=VALIDATION_PATHS["analyzeAsIs"],
    reviews=(("approvedReview", REVIEW_PATHS["analyzeAsIs"]),),
    outputs=(("asIs", DATA_PATHS["asis"]),),
)
DESIGN_CONTRACT = OwnerContract(
    subject="generate-design",
    contract_ids=(
        "urn:ai-sow:generate-design:design:0.2",
        "urn:ai-sow:generate-design:technical-requirements:0.2",
    ),
    validation_path=VALIDATION_PATHS["generateDesign"],
    reviews=(("approvedReview", REVIEW_PATHS["generateDesign"]),),
    outputs=(
        ("design", DATA_PATHS["design"]),
        ("technicalRequirements", DATA_PATHS["derivedRequirements"]),
    ),
)
STORY_CONTRACT = OwnerContract(
    subject="generate-story",
    contract_ids=("urn:ai-sow:generate-story:delivery:0.2",),
    validation_path=VALIDATION_PATHS["generateStory"],
    reviews=(("approvedReview", REVIEW_PATHS["generateStory"]),),
    outputs=(("delivery", DATA_PATHS["delivery"]),),
)
TASK_CONTRACT = OwnerContract(
    subject="generate-task",
    contract_ids=("urn:ai-sow:generate-task:estimate:0.2",),
    validation_path=VALIDATION_PATHS["generateTask"],
    reviews=(("approvedReview", REVIEW_PATHS["generateTask"]),),
    outputs=(("estimate", DATA_PATHS["estimate"]),),
)


class GenerationError(ValueError):
    def __init__(self, code: str, message: str, path: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.path = path


def diagnostic(code: str, message: str, path: str = "") -> dict[str, object]:
    value: dict[str, object] = {"code": code, "message": message}
    if path:
        value["path"] = path
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a deterministic SOW package")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--staging-root")
    return parser.parse_args()


def file_artifact(files: ProjectFiles, name: str, path: str) -> Artifact:
    return Artifact(name, "FILE", path, sha256_bytes(files.read_bytes(path)))


def declaration(files: ProjectFiles, path: str, label: str) -> str:
    try:
        text = files.read_bytes(path).decode("utf-8")
    except (ProjectIOError, UnicodeDecodeError) as error:
        raise GenerationError("UPSTREAM_HANDOFF_INVALID", f"review is unavailable: {path}", path) from error
    values = re.findall(rf"(?m)^{re.escape(label)}\s*:\s*(.+?)\s*$", text)
    if len(values) != 1:
        raise GenerationError(
            "UPSTREAM_HANDOFF_INVALID",
            f"review must declare exactly one {label}",
            path,
        )
    return values[0]


def questionnaire_artifact(files: ProjectFiles, review_path: str) -> Artifact:
    value = declaration(files, review_path, "Questionnaire")
    if value == "NOT_REQUIRED":
        logical = canonical_json_bytes({"declaration": "NOT_REQUIRED"})
        return Artifact(
            "questionnaire",
            "QUESTIONNAIRE_PRESENCE",
            "questionnaire:NOT_REQUIRED",
            sha256_bytes(logical),
        )
    return Artifact(
        "questionnaire",
        "QUESTIONNAIRE_PRESENCE",
        f"questionnaire:{value}",
        sha256_bytes(files.read_bytes(value)),
    )


def requirement_inputs(files: ProjectFiles, data: dict[str, Any]) -> tuple[Artifact, ...]:
    inputs = [file_artifact(files, "project", PROJECT_PATH)]
    for source in data["sourceDocuments"]:
        inputs.append(file_artifact(files, f"source:{source['sourceDocumentId']}", source["file"]))
    inputs.append(questionnaire_artifact(files, REVIEW_PATHS["analyzeRequirement"]))
    return tuple(inputs)


def repository_evidence_path(scope: dict[str, Any], reference: str) -> str:
    match = re.fullmatch(r"([a-z][a-z0-9-]*):([^#]+)(?:#.*)?", reference)
    if match is None:
        raise GenerationError("UPSTREAM_HANDOFF_INVALID", f"invalid repository evidence: {reference}")
    repo_id, anchor = match.groups()
    snapshot = next(
        (item for item in scope["repositorySnapshots"] if item["repoId"] == repo_id),
        None,
    )
    if snapshot is None:
        raise GenerationError("UPSTREAM_HANDOFF_INVALID", f"unknown repository evidence: {reference}")
    return anchor if snapshot["path"] == "." else f"{snapshot['path']}/{anchor}"


def asis_inputs(files: ProjectFiles, data: dict[str, Any]) -> tuple[Artifact, ...]:
    inputs = [
        file_artifact(files, "project", PROJECT_PATH),
        file_artifact(files, "requirementsValidation", VALIDATION_PATHS["analyzeRequirement"]),
        file_artifact(files, "requirements", DATA_PATHS["sourceRequirements"]),
    ]
    scope = data["analysisScope"]
    for snapshot in scope["repositorySnapshots"]:
        inputs.append(
            Artifact(
                f"repository:{snapshot['repoId']}",
                "CANONICAL_JSON",
                f"repository:{snapshot['repoId']}",
                sha256_bytes(canonical_json_bytes(snapshot)),
            )
        )
    for snapshot in scope["priorSowSnapshots"]:
        inputs.append(file_artifact(files, f"priorSow:{snapshot['priorSowId']}", snapshot["file"]))
    for evidence in data["evidence"]:
        kind = evidence["kind"]
        reference = evidence["reference"]
        if kind in {"PRIOR_SOW", "QUESTIONNAIRE"} or (
            kind == "DOCUMENT" and reference.startswith("requirements:")
        ):
            continue
        if kind in {"CODE", "CONTRACT", "CONFIGURATION", "DEPLOYMENT"} or (
            kind == "DOCUMENT"
            and re.fullmatch(r"[a-z][a-z0-9-]*:[^#]+(?:#.*)?", reference) is not None
        ):
            path = repository_evidence_path(scope, reference)
        elif kind in {"RUNTIME", "DOCUMENT"}:
            path = reference.split("#", 1)[0]
        else:
            continue
        inputs.append(file_artifact(files, f"evidence:{evidence['evidenceId']}", path))
    inputs.append(questionnaire_artifact(files, REVIEW_PATHS["analyzeAsIs"]))
    return tuple(inputs)


def design_inputs(files: ProjectFiles) -> tuple[Artifact, ...]:
    return tuple(
        file_artifact(files, name, path)
        for name, path in (
            ("project", PROJECT_PATH),
            ("requirementsValidation", VALIDATION_PATHS["analyzeRequirement"]),
            ("requirements", DATA_PATHS["sourceRequirements"]),
            ("asIsValidation", VALIDATION_PATHS["analyzeAsIs"]),
            ("asIs", DATA_PATHS["asis"]),
        )
    )


def story_inputs(files: ProjectFiles) -> tuple[Artifact, ...]:
    return tuple(
        file_artifact(files, name, path)
        for name, path in (
            ("project", PROJECT_PATH),
            ("requirementsValidation", VALIDATION_PATHS["analyzeRequirement"]),
            ("requirements", DATA_PATHS["sourceRequirements"]),
            ("asIsValidation", VALIDATION_PATHS["analyzeAsIs"]),
            ("asIs", DATA_PATHS["asis"]),
            ("designValidation", VALIDATION_PATHS["generateDesign"]),
            ("design", DATA_PATHS["design"]),
            ("technicalRequirements", DATA_PATHS["derivedRequirements"]),
        )
    )


def task_inputs(files: ProjectFiles) -> tuple[Artifact, ...]:
    return tuple(
        file_artifact(files, name, path)
        for name, path in (
            ("project", PROJECT_PATH),
            ("asIsValidation", VALIDATION_PATHS["analyzeAsIs"]),
            ("asIs", DATA_PATHS["asis"]),
            ("designValidation", VALIDATION_PATHS["generateDesign"]),
            ("design", DATA_PATHS["design"]),
            ("technicalRequirements", DATA_PATHS["derivedRequirements"]),
            ("deliveryValidation", VALIDATION_PATHS["generateStory"]),
            ("delivery", DATA_PATHS["delivery"]),
            ("template", TEMPLATE_PATH),
        )
    )


def load_object(files: ProjectFiles, path: str) -> dict[str, Any]:
    value = files.read_json(path)
    if not isinstance(value, dict):
        raise GenerationError("INPUT_INVALID", f"JSON object is required: {path}", path)
    return value


def validate_project(project: dict[str, Any]) -> None:
    if set(project) != {"projectId", "name", "pluginVersion", "sowStandardVersion"}:
        raise GenerationError("PROJECT_SCHEMA_INVALID", "project metadata must contain exactly four fields", PROJECT_PATH)
    if (
        not isinstance(project["projectId"], str)
        or re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+", project["projectId"]) is None
        or not isinstance(project["name"], str)
        or not project["name"]
        or project["pluginVersion"] != PLUGIN_VERSION
        or project["sowStandardVersion"] != "1.3"
    ):
        raise GenerationError(
            "PROJECT_SCHEMA_INVALID",
            f"project metadata must use pluginVersion {PLUGIN_VERSION} and SOW standard 1.3",
            PROJECT_PATH,
        )


def verify_owner_handoffs(
    files: ProjectFiles,
    data: dict[str, dict[str, Any]],
) -> tuple[dict[str, object], ...]:
    specs: tuple[
        tuple[OwnerContract, Callable[[], tuple[Artifact, ...]]], ...
    ] = (
        (REQUIREMENT_CONTRACT, lambda: requirement_inputs(files, data["sourceRequirements"])),
        (ASIS_CONTRACT, lambda: asis_inputs(files, data["asis"])),
        (DESIGN_CONTRACT, lambda: design_inputs(files)),
        (STORY_CONTRACT, lambda: story_inputs(files)),
        (TASK_CONTRACT, lambda: task_inputs(files)),
    )
    receipts: list[dict[str, object]] = []
    for contract, build_inputs in specs:
        result: MatchResult = match_owner(files, contract, build_inputs())
        if not result.ok:
            first = result.diagnostics[0]
            raise GenerationError(
                str(first["code"]),
                str(first["message"]),
                str(first.get("path", contract.validation_path)),
            )
        assert result.receipt is not None
        receipts.append(result.receipt)
    return tuple(receipts)


def digest_entry(path: str, payload: bytes) -> dict[str, str]:
    return {"path": path, "sha256": sha256_bytes(payload)}


def fingerprint_entry(name: str, path: str, payload: bytes) -> dict[str, str]:
    return {"name": name, "path": path, "sha256": sha256_bytes(payload)}


def package_fingerprint_payload(
    files: ProjectFiles,
    project: dict[str, Any],
) -> dict[str, object]:
    return {
        "algorithm": PACKAGE_ALGORITHM,
        "generatorContract": GENERATOR_CONTRACT,
        "projectIdentity": {
            "projectId": project["projectId"],
            "pluginVersion": project["pluginVersion"],
            "sowStandardVersion": project["sowStandardVersion"],
        },
        "project": fingerprint_entry(
            "project",
            PROJECT_PATH,
            files.read_bytes(PROJECT_PATH),
        ),
        "inputs": [
            fingerprint_entry(key, PACKAGE_DATA_PATHS[key], files.read_bytes(path))
            for key, path in DATA_PATHS.items()
        ],
        "reviews": [
            fingerprint_entry(key, PACKAGE_REVIEW_PATHS[key], files.read_bytes(path))
            for key, path in REVIEW_PATHS.items()
        ],
        "validationReceipts": [
            fingerprint_entry(key, PACKAGE_VALIDATION_PATHS[key], files.read_bytes(path))
            for key, path in VALIDATION_PATHS.items()
        ],
        "template": fingerprint_entry(
            "template",
            PACKAGE_TEMPLATE_PATH,
            files.read_bytes(TEMPLATE_PATH),
        ),
    }


def package_fingerprint(files: ProjectFiles, project: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(package_fingerprint_payload(files, project)))


def write_file(root: Path, relative: str, payload: bytes) -> None:
    target = root.joinpath(*relative.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)


def tree_digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_bytes(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def expected_package_paths() -> set[str]:
    return {
        "manifest.json",
        "sow.xlsx",
        *PACKAGE_DATA_PATHS.values(),
        *PACKAGE_REVIEW_PATHS.values(),
        *PACKAGE_VALIDATION_PATHS.values(),
        PACKAGE_TEMPLATE_PATH,
    }


def verify_package_tree(root: Path, manifest: dict[str, object]) -> dict[str, str]:
    digests = tree_digests(root)
    if set(digests) != expected_package_paths():
        raise GenerationError("PACKAGE_TREE_INVALID", "package member set is invalid")
    if root.joinpath("manifest.json").read_bytes() != canonical_json_bytes(manifest):
        raise GenerationError("PACKAGE_TREE_INVALID", "manifest bytes are not canonical")
    if digests["sow.xlsx"] != manifest["generatedWorkbookSha256"]:
        raise GenerationError("PACKAGE_TREE_INVALID", "generated workbook digest is invalid")
    for section in ("inputs", "reviews", "validationReceipts"):
        entries = manifest[section]
        assert isinstance(entries, dict)
        for entry in entries.values():
            assert isinstance(entry, dict)
            if digests.get(str(entry["path"])) != entry["sha256"]:
                raise GenerationError("PACKAGE_TREE_INVALID", f"package digest is invalid: {entry['path']}")
    template = manifest["template"]
    assert isinstance(template, dict)
    if digests.get(str(template["path"])) != template["sha256"]:
        raise GenerationError("PACKAGE_TREE_INVALID", "package template digest is invalid")
    return digests


def publish_staging(staging: Path, final: Path) -> None:
    try:
        os.replace(staging, final)
    except OSError as error:
        unsupported = {
            errno.EXDEV,
            getattr(errno, "ENOTSUP", -1),
            getattr(errno, "EOPNOTSUPP", -1),
        }
        if error.errno in unsupported:
            raise GenerationError(
                "PACKAGE_PUBLICATION_UNSUPPORTED",
                "same-filesystem no-overwrite publication is unsupported",
                final.as_posix(),
            ) from error
        raise


def package_manifest(
    files: ProjectFiles,
    project: dict[str, Any],
    data: dict[str, dict[str, Any]],
    package_id: str,
    fingerprint: str,
    workbook_payload: bytes,
) -> dict[str, object]:
    scope = data["asis"]["analysisScope"]
    manifest: dict[str, object] = {
        "packageId": package_id,
        "fingerprintAlgorithm": PACKAGE_ALGORITHM,
        "generationFingerprint": fingerprint,
        "generatedWorkbookSha256": sha256_bytes(workbook_payload),
        "projectId": project["projectId"],
        "pluginVersion": project["pluginVersion"],
        "sowStandardVersion": project["sowStandardVersion"],
        "projectMode": scope["mode"],
        "repositories": [
            {
                "repoId": item["repoId"],
                "name": item["name"],
                "setupRevision": item["revision"],
            }
            for item in scope["repositorySnapshots"]
        ],
        "priorSows": [
            {
                "priorSowId": item["priorSowId"],
                "name": item["name"],
                "sha256": item["sha256"],
            }
            for item in scope["priorSowSnapshots"]
        ],
        "inputs": {
            key: digest_entry(PACKAGE_DATA_PATHS[key], files.read_bytes(path))
            for key, path in DATA_PATHS.items()
        },
        "reviews": {
            key: digest_entry(PACKAGE_REVIEW_PATHS[key], files.read_bytes(path))
            for key, path in REVIEW_PATHS.items()
        },
        "template": digest_entry(PACKAGE_TEMPLATE_PATH, files.read_bytes(TEMPLATE_PATH)),
        "validationReceipts": {
            key: digest_entry(PACKAGE_VALIDATION_PATHS[key], files.read_bytes(path))
            for key, path in VALIDATION_PATHS.items()
        },
    }
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "contracts/manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(manifest), key=lambda item: list(item.path))
    if errors:
        raise GenerationError("MANIFEST_SCHEMA_INVALID", errors[0].message)
    return manifest


def build_package(
    files: ProjectFiles,
    project: dict[str, Any],
    data: dict[str, dict[str, Any]],
) -> tuple[str, str, str]:
    fingerprint = package_fingerprint(files, project)
    package_id = f"sow-sha256-{fingerprint}"
    outputs = files.ensure_dir(OUTPUTS_PATH)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=outputs))
    final = outputs / package_id
    try:
        workbook_path = staging / "sow.xlsx"
        workbook_data = {
            "requirements": {
                "epics": [
                    *data["sourceRequirements"]["epics"],
                    *data["derivedRequirements"]["epics"],
                ],
                "features": [
                    *data["sourceRequirements"]["features"],
                    *data["derivedRequirements"]["features"],
                ],
            },
            "asis": data["asis"],
            "design": data["design"],
            "technicalRequirements": data["derivedRequirements"],
            "delivery": data["delivery"],
            "estimate": data["estimate"],
        }
        input_hashes = {
            key: sha256_bytes(files.read_bytes(path)) for key, path in DATA_PATHS.items()
        }
        write_workbook(
            files.resolve(TEMPLATE_PATH),
            workbook_data,
            workbook_path,
            input_hashes,
        )
        workbook_payload = workbook_path.read_bytes()
        for key, path in DATA_PATHS.items():
            write_file(staging, PACKAGE_DATA_PATHS[key], files.read_bytes(path))
        for key, path in REVIEW_PATHS.items():
            write_file(staging, PACKAGE_REVIEW_PATHS[key], files.read_bytes(path))
        for key, path in VALIDATION_PATHS.items():
            write_file(staging, PACKAGE_VALIDATION_PATHS[key], files.read_bytes(path))
        write_file(staging, PACKAGE_TEMPLATE_PATH, files.read_bytes(TEMPLATE_PATH))
        manifest = package_manifest(files, project, data, package_id, fingerprint, workbook_payload)
        write_file(staging, "manifest.json", canonical_json_bytes(manifest))
        staging_digests = verify_package_tree(staging, manifest)

        if final.exists():
            if final.is_symlink() or not final.is_dir() or tree_digests(final) != staging_digests:
                raise GenerationError(
                    "PACKAGE_CONTENT_MISMATCH",
                    "existing deterministic package has different content",
                    f"{OUTPUTS_PATH}/{package_id}",
                )
            publication = "REUSED"
        else:
            publish_staging(staging, final)
            publication = "CREATED"
        return package_id, f"{OUTPUTS_PATH}/{package_id}", publication
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main() -> int:
    args = parse_args()
    diagnostics: list[dict[str, object]] = []
    try:
        files = (
            ProjectFiles.open_view(args.project_root, args.staging_root)
            if args.staging_root is not None
            else ProjectFiles.open(args.project_root)
        )
        project = load_object(files, PROJECT_PATH)
        validate_project(project)
        data = {key: load_object(files, path) for key, path in DATA_PATHS.items()}
        verify_owner_handoffs(files, data)
        package_id, package_path, publication = build_package(files, project, data)
        result: dict[str, object] = {
            "outcome": "OK",
            "summary": "SOW package generated",
            "packageId": package_id,
            "packagePath": package_path,
            "publication": publication,
            "diagnostics": [],
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except GenerationError as error:
        diagnostics.append(diagnostic(error.code, str(error), error.path))
    except ProjectIOError as error:
        diagnostics.append(diagnostic(error.code, str(error), error.relative_path))
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
        diagnostics.append(diagnostic("GENERATION_BLOCKED", str(error)))
    print(
        json.dumps(
            {
                "outcome": "BLOCKED",
                "summary": "SOW package was not generated",
                "diagnostics": diagnostics,
            },
            ensure_ascii=False,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
