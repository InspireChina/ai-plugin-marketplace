from __future__ import annotations

from collections.abc import Mapping, Sequence

from runtime.handoff import canonical_json_bytes, sha256_bytes
from runtime.project_io import ProjectFiles, ProjectIOError


def optional_bytes(files: ProjectFiles, relative_path: str) -> bytes | None:
    try:
        return files.read_bytes(relative_path)
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return None
        raise


def _delete_regular_file(files: ProjectFiles, relative_path: str) -> None:
    target = files.resolve(relative_path, expect="file")
    target.unlink()


def publish_file_transaction(
    files: ProjectFiles,
    writes: Mapping[str, bytes],
    deletes: Sequence[str],
) -> None:
    paths = sorted(set(writes) | set(deletes))
    before = {path: optional_bytes(files, path) for path in paths}
    try:
        for path in sorted(writes):
            files.write_atomic(path, writes[path])
        for path in sorted(deletes):
            if optional_bytes(files, path) is not None:
                _delete_regular_file(files, path)
    except (ProjectIOError, OSError):
        for path in reversed(paths):
            original = before[path]
            if original is None:
                if optional_bytes(files, path) is not None:
                    _delete_regular_file(files, path)
            else:
                files.write_atomic(path, original)
        raise


def plan_review_packet_rotation(
    files: ProjectFiles,
    *,
    packet_path: str,
    packet_payload: bytes,
    reviewer_path: str,
    approval_path: str,
) -> tuple[dict[str, bytes], list[str], str | None]:
    current_packet = optional_bytes(files, packet_path)
    current_reviewer = optional_bytes(files, reviewer_path)
    current_approval = optional_bytes(files, approval_path)
    writes = {packet_path: packet_payload}
    if current_packet == packet_payload:
        return writes, [], None
    if current_packet is None and current_reviewer is None and current_approval is None:
        return writes, [], None
    if current_packet is not None:
        archive_key = sha256_bytes(current_packet)
    else:
        orphan_payload = canonical_json_bytes(
            {
                "approvalSha256": (
                    sha256_bytes(current_approval) if current_approval is not None else None
                ),
                "reviewerSha256": (
                    sha256_bytes(current_reviewer) if current_reviewer is not None else None
                ),
            }
        )
        archive_key = f"orphan-{sha256_bytes(orphan_payload)}"
    work_root = packet_path.rsplit("/", 1)[0]
    archive_root = f"{work_root}/archive/{archive_key}"
    for name, payload in (
        ("review-packet.json", current_packet),
        ("reviewer.json", current_reviewer),
        ("approval.json", current_approval),
    ):
        if payload is None:
            continue
        archive_path = f"{archive_root}/{name}"
        existing = optional_bytes(files, archive_path)
        if existing is not None and existing != payload:
            raise ProjectIOError(
                "REVIEW_ARCHIVE_CONFLICT",
                archive_path,
                f"authorization archive has conflicting bytes: {archive_path}",
            )
        writes[archive_path] = payload
    deletes = [
        path
        for path, payload in (
            (reviewer_path, current_reviewer),
            (approval_path, current_approval),
        )
        if payload is not None
    ]
    return writes, deletes, archive_root


def publish_review_packet(
    files: ProjectFiles,
    *,
    packet_path: str,
    packet_payload: bytes,
    reviewer_path: str,
    approval_path: str,
) -> str | None:
    writes, deletes, archive_root = plan_review_packet_rotation(
        files,
        packet_path=packet_path,
        packet_payload=packet_payload,
        reviewer_path=reviewer_path,
        approval_path=approval_path,
    )
    publish_file_transaction(files, writes, deletes)
    return archive_root
