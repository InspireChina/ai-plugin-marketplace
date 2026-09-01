from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

PLUGIN_ROOT = Path(__file__).parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.project_io import ProjectFiles, ProjectIOError, ProjectView


def _symlink_supported() -> bool:
    """Windows only allows symlink creation under Developer Mode or elevation."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        try:
            (root / "link").symlink_to(root / "target", target_is_directory=True)
        except (OSError, NotImplementedError):
            return False
    return True


SYMLINK_SUPPORTED = _symlink_supported()
requires_symlinks = pytest.mark.skipif(
    not SYMLINK_SUPPORTED,
    reason="creating symlinks requires Developer Mode or elevation on this platform",
)


def test_project_files_read_write_and_resolve_relative_paths(tmp_path: Path) -> None:
    files = ProjectFiles.open(tmp_path)
    files.write_atomic(".ai-sow/data/result.json", b'{"value":1}\n')
    assert files.read_bytes(".ai-sow/data/result.json") == b'{"value":1}\n'
    assert files.read_json(".ai-sow/data/result.json") == {"value": 1}
    assert files.resolve(".ai-sow/data", expect="dir").is_dir()
    assert files.resolve(".ai-sow/data/result.json", expect="file").is_file()


def test_write_atomic_replaces_content_and_reuses_identical_bytes(tmp_path: Path) -> None:
    files = ProjectFiles.open(tmp_path)
    relative = ".ai-sow/project.json"
    files.write_atomic(relative, b"first")
    target = files.resolve(relative)
    first_stat = target.stat()
    files.write_atomic(relative, b"first")
    assert target.stat().st_mtime_ns == first_stat.st_mtime_ns
    files.write_atomic(relative, b"second")
    assert files.read_bytes(relative) == b"second"


def test_publish_new_creates_reuses_and_rejects_conflicting_content(tmp_path: Path) -> None:
    files = ProjectFiles.open(tmp_path)
    assert files.publish_new(".ai-sow/data/value.json", b"same") == "CREATED"
    assert files.publish_new(".ai-sow/data/value.json", b"same") == "REUSED"
    with pytest.raises(ProjectIOError) as raised:
        files.publish_new(".ai-sow/data/value.json", b"different")
    assert raised.value.code == "PROJECT_CONTENT_CONFLICT"
    assert raised.value.relative_path == ".ai-sow/data/value.json"
    assert files.read_bytes(".ai-sow/data/value.json") == b"same"


@pytest.mark.parametrize(
    "relative",
    ("", ".", "../outside", ".ai-sow/../outside", "/absolute", r".ai-sow\data"),
)
def test_project_files_reject_invalid_relative_paths(tmp_path: Path, relative: str) -> None:
    files = ProjectFiles.open(tmp_path)
    with pytest.raises(ProjectIOError) as raised:
        files.read_bytes(relative)
    assert raised.value.code == "PROJECT_PATH_INVALID"


@requires_symlinks
def test_project_files_reject_symlink_in_managed_path(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / ".ai-sow").symlink_to(outside, target_is_directory=True)
    files = ProjectFiles.open(tmp_path)
    with pytest.raises(ProjectIOError) as raised:
        files.write_atomic(".ai-sow/project.json", b"{}")
    assert raised.value.code == "PROJECT_PATH_UNSAFE"
    assert list(outside.iterdir()) == []


def test_project_files_reject_type_mismatch_and_missing_file(tmp_path: Path) -> None:
    files = ProjectFiles.open(tmp_path)
    files.ensure_dir(".ai-sow/data")
    with pytest.raises(ProjectIOError) as missing:
        files.read_bytes(".ai-sow/data/missing.json")
    assert missing.value.code == "PROJECT_PATH_MISSING"
    with pytest.raises(ProjectIOError) as wrong_type:
        files.resolve(".ai-sow/data", expect="file")
    assert wrong_type.value.code == "PROJECT_PATH_TYPE"


def test_read_json_reports_invalid_json_without_leaking_absolute_path(tmp_path: Path) -> None:
    files = ProjectFiles.open(tmp_path)
    files.write_atomic(".ai-sow/data/value.json", b"not json")
    with pytest.raises(ProjectIOError) as raised:
        files.read_json(".ai-sow/data/value.json")
    assert raised.value.code == "PROJECT_JSON_INVALID"
    assert str(tmp_path) not in str(raised.value)


def test_project_files_requires_existing_regular_directory_root(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(ProjectIOError) as raised:
        ProjectFiles.open(missing)
    assert raised.value.code == "PROJECT_ROOT_INVALID"
    file_root = tmp_path / "file"
    file_root.write_text(json.dumps({}), encoding="utf-8")
    with pytest.raises(ProjectIOError):
        ProjectFiles.open(file_root)


def test_project_view_reads_staging_first_then_falls_back_to_base(
    tmp_path: Path,
) -> None:
    base = ProjectFiles.open(tmp_path)
    base.ensure_dir(".ai-sow")
    base.write_atomic(".ai-sow/data/base.json", b'"base"\n')
    base.write_atomic(".ai-sow/data/shadow.json", b'"old"\n')
    base.write_atomic("repositories/customer/evidence.txt", b"base evidence\n")

    view = ProjectFiles.open_view(tmp_path, ".ai-sow/.stage-0123456789ab")
    assert view.staging_root == ".ai-sow/.stage-0123456789ab"
    view.staging.write_atomic("data/shadow.json", b'"staged"\n')
    view.staging.write_atomic(
        "repositories/customer/evidence.txt",
        b"must not shadow external evidence\n",
    )

    assert view.read_bytes(".ai-sow/data/base.json") == b'"base"\n'
    assert view.read_bytes(".ai-sow/data/shadow.json") == b'"staged"\n'
    assert view.read_json(".ai-sow/data/shadow.json") == "staged"
    assert (
        view.read_bytes("repositories/customer/evidence.txt")
        == b"base evidence\n"
    )


def test_project_view_writes_and_directories_only_enter_staging(tmp_path: Path) -> None:
    base = ProjectFiles.open(tmp_path)
    base.ensure_dir(".ai-sow")
    base.write_atomic(".ai-sow/data/value.json", b"base")

    view = ProjectFiles.open_view(tmp_path, ".ai-sow/.stage-0123456789ab")
    view.ensure_dir(".ai-sow/work/reconcile")
    view.write_atomic(".ai-sow/data/value.json", b"staged")
    assert view.publish_new(".ai-sow/data/new.json", b"new") == "CREATED"

    assert base.read_bytes(".ai-sow/data/value.json") == b"base"
    with pytest.raises(ProjectIOError) as missing:
        base.read_bytes(".ai-sow/data/new.json")
    assert missing.value.code == "PROJECT_PATH_MISSING"
    with pytest.raises(ProjectIOError):
        base.resolve(".ai-sow/work/reconcile", expect="dir")
    assert view.read_bytes(".ai-sow/data/value.json") == b"staged"
    assert view.read_bytes(".ai-sow/data/new.json") == b"new"
    assert (view.staging.root / "data/value.json").read_bytes() == b"staged"
    assert (view.staging.root / "data/new.json").read_bytes() == b"new"
    assert (view.staging.root / "work/reconcile").is_dir()
    assert not (view.staging.root / ".ai-sow").exists()


def test_project_view_tombstone_hides_base_until_staged_write(tmp_path: Path) -> None:
    base = ProjectFiles.open(tmp_path)
    base.ensure_dir(".ai-sow")
    base.write_atomic(".ai-sow/data/value.json", b"base")
    view = ProjectFiles.open_view(tmp_path, ".ai-sow/.stage-0123456789ab")
    view.write_atomic(".ai-sow/data/value.json", b"staged candidate")
    assert (view.staging.root / "data/value.json").is_file()

    view.tombstone(".ai-sow/data/value.json")
    with pytest.raises(ProjectIOError) as missing:
        view.read_bytes(".ai-sow/data/value.json")
    assert missing.value.code == "PROJECT_PATH_MISSING"
    assert base.read_bytes(".ai-sow/data/value.json") == b"base"
    assert any(
        path.is_file()
        for path in (view.staging.root / ".project-io/tombstones").iterdir()
    )
    assert not (view.staging.root / "data/value.json").exists()

    view.write_atomic(".ai-sow/data/value.json", b"replacement")
    assert view.read_bytes(".ai-sow/data/value.json") == b"replacement"
    assert base.read_bytes(".ai-sow/data/value.json") == b"base"
    assert (view.staging.root / "data/value.json").read_bytes() == b"replacement"


@pytest.mark.parametrize(
    "operation",
    (
        lambda view: view.ensure_dir("repositories/customer"),
        lambda view: view.write_atomic("repositories/customer/value.json", b"unsafe"),
        lambda view: view.publish_new("repositories/customer/value.json", b"unsafe"),
        lambda view: view.tombstone("repositories/customer/value.json"),
    ),
)
def test_project_view_rejects_writes_outside_logical_ai_sow(
    tmp_path: Path,
    operation: Callable[[ProjectView], object],
) -> None:
    base = ProjectFiles.open(tmp_path)
    base.ensure_dir(".ai-sow")
    view = ProjectFiles.open_view(tmp_path, ".ai-sow/.stage-0123456789ab")

    with pytest.raises(ProjectIOError) as raised:
        operation(view)

    assert raised.value.code == "PROJECT_PATH_INVALID"
    assert not (tmp_path / "repositories").exists()
    assert not (view.staging.root / "repositories").exists()


def test_project_view_exposes_validated_tombstone_state(tmp_path: Path) -> None:
    base = ProjectFiles.open(tmp_path)
    base.ensure_dir(".ai-sow")
    base.write_atomic(".ai-sow/data/value.json", b"base")
    view = ProjectFiles.open_view(tmp_path, ".ai-sow/.stage-0123456789ab")

    assert not view.is_tombstoned(".ai-sow/data/value.json")
    view.tombstone(".ai-sow/data/value.json")
    assert view.is_tombstoned(".ai-sow/data/value.json")
    assert not view.is_tombstoned(".ai-sow/data/other.json")

    with pytest.raises(ProjectIOError) as reserved:
        view.is_tombstoned(
            ".ai-sow/.stage-fedcba987654/.ai-sow/data/value.json"
        )
    assert reserved.value.code == "PROJECT_PATH_INVALID"


@pytest.mark.parametrize(
    "staging_root",
    (
        "",
        ".",
        "../stage",
        ".ai-sow/../stage",
        "/absolute/stage",
        r".ai-sow\stage",
    ),
)
def test_project_view_rejects_unsafe_staging_roots(
    tmp_path: Path,
    staging_root: str,
) -> None:
    ProjectFiles.open(tmp_path).ensure_dir(".ai-sow")
    with pytest.raises(ProjectIOError) as raised:
        ProjectFiles.open_view(tmp_path, staging_root)
    assert raised.value.code == "PROJECT_PATH_INVALID"


@pytest.mark.parametrize(
    "staging_root",
    (
        ".ai-sow",
        ".ai-sow/stage-0123456789ab",
        ".ai-sow/.stage-0123456789a",
        ".ai-sow/.stage-0123456789abc",
        ".ai-sow/.stage-0123456789aG",
        ".ai-sow/.stage-ABCDEFGHIJKL",
        ".ai-sow/work/.stage-0123456789ab",
    ),
)
def test_project_view_requires_exact_staging_namespace(
    tmp_path: Path,
    staging_root: str,
) -> None:
    ProjectFiles.open(tmp_path).ensure_dir(".ai-sow")
    with pytest.raises(ProjectIOError) as raised:
        ProjectFiles.open_view(tmp_path, staging_root)
    assert raised.value.code == "STAGING_ROOT_INVALID"


def test_project_view_rejects_staging_root_on_another_filesystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = ProjectFiles.open(tmp_path)
    formal_root = base.ensure_dir(".ai-sow")
    stage = formal_root / ".stage-0123456789ab"
    stage.mkdir()
    real_lstat = Path.lstat

    def fake_lstat(path: Path) -> object:
        snapshot = real_lstat(path)
        if path == stage:
            return SimpleNamespace(
                st_dev=snapshot.st_dev + 1,
                st_file_attributes=getattr(snapshot, "st_file_attributes", 0),
                st_mode=snapshot.st_mode,
            )
        return snapshot

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(ProjectIOError) as raised:
        ProjectFiles.open_view(tmp_path, ".ai-sow/.stage-0123456789ab")
    assert raised.value.code == "STAGING_ROOT_INVALID"


@requires_symlinks
def test_project_view_rejects_missing_or_symlinked_staging_parent(
    tmp_path: Path,
) -> None:
    with pytest.raises(ProjectIOError) as missing:
        ProjectFiles.open_view(tmp_path, ".ai-sow/.stage-0123456789ab")
    assert missing.value.code == "PROJECT_PATH_MISSING"

    outside = tmp_path.parent / f"{tmp_path.name}-view-outside"
    outside.mkdir()
    (tmp_path / ".ai-sow").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ProjectIOError) as unsafe:
        ProjectFiles.open_view(tmp_path, ".ai-sow/.stage-0123456789ab")
    assert unsafe.value.code == "PROJECT_PATH_UNSAFE"
    assert list(outside.iterdir()) == []


@requires_symlinks
def test_project_view_rejects_file_or_symlink_staging_root(tmp_path: Path) -> None:
    base = ProjectFiles.open(tmp_path)
    stage_parent = base.ensure_dir(".ai-sow")
    stage = stage_parent / ".stage-0123456789ab"
    stage.write_bytes(b"not a directory")
    with pytest.raises(ProjectIOError) as wrong_type:
        ProjectFiles.open_view(tmp_path, ".ai-sow/.stage-0123456789ab")
    assert wrong_type.value.code == "STAGING_ROOT_INVALID"

    stage.unlink()
    outside = tmp_path.parent / f"{tmp_path.name}-stage-outside"
    outside.mkdir()
    stage.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ProjectIOError) as unsafe:
        ProjectFiles.open_view(tmp_path, ".ai-sow/.stage-0123456789ab")
    assert unsafe.value.code == "STAGING_ROOT_INVALID"
    assert list(outside.iterdir()) == []


@requires_symlinks
def test_project_view_rejects_unsafe_paths_in_both_layers(tmp_path: Path) -> None:
    base = ProjectFiles.open(tmp_path)
    base.ensure_dir(".ai-sow")
    view = ProjectFiles.open_view(tmp_path, ".ai-sow/.stage-0123456789ab")

    with pytest.raises(ProjectIOError) as invalid:
        view.write_atomic(".ai-sow/../outside", b"unsafe")
    assert invalid.value.code == "PROJECT_PATH_INVALID"

    outside = tmp_path.parent / f"{tmp_path.name}-layer-outside"
    outside.mkdir()
    (view.staging.root / "data").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ProjectIOError) as unsafe:
        view.write_atomic(".ai-sow/data/value.json", b"unsafe")
    assert unsafe.value.code == "PROJECT_PATH_UNSAFE"
    assert list(outside.iterdir()) == []

    with pytest.raises(ProjectIOError) as reserved:
        view.write_atomic(".ai-sow/.project-io/value.json", b"unsafe")
    assert reserved.value.code == "PROJECT_PATH_INVALID"


def test_project_view_rejects_its_physical_staging_namespace_as_logical_input(
    tmp_path: Path,
) -> None:
    base = ProjectFiles.open(tmp_path)
    base.ensure_dir(".ai-sow")
    staging_root = ".ai-sow/.stage-0123456789ab"
    view = ProjectFiles.open_view(tmp_path, staging_root)
    view.staging.write_atomic("data/staged-only.json", b"staged only")

    operations = (
        lambda: view.resolve(staging_root, expect="dir"),
        lambda: view.read_bytes(f"{staging_root}/data/staged-only.json"),
        lambda: view.write_atomic(f"{staging_root}/alias.json", b"unsafe"),
        lambda: view.ensure_dir(f"{staging_root}/alias"),
        lambda: view.publish_new(f"{staging_root}/alias.json", b"unsafe"),
        lambda: view.tombstone(f"{staging_root}/alias.json"),
    )
    for operation in operations:
        with pytest.raises(ProjectIOError) as raised:
            operation()
        assert raised.value.code == "PROJECT_PATH_INVALID"


def test_project_view_rejects_sibling_staging_namespace_as_logical_input(
    tmp_path: Path,
) -> None:
    base = ProjectFiles.open(tmp_path)
    base.ensure_dir(".ai-sow")
    sibling_root = ".ai-sow/.stage-fedcba987654"
    sibling = ProjectFiles.open_view(tmp_path, sibling_root)
    sibling.write_atomic(".ai-sow/data/staged-only.json", b"sibling staged only")

    view = ProjectFiles.open_view(tmp_path, ".ai-sow/.stage-0123456789ab")
    with pytest.raises(ProjectIOError) as raised:
        view.read_bytes(f"{sibling_root}/data/staged-only.json")
    assert raised.value.code == "PROJECT_PATH_INVALID"


def test_project_view_tombstone_rejects_directories_in_either_layer(
    tmp_path: Path,
) -> None:
    base = ProjectFiles.open(tmp_path)
    base.ensure_dir(".ai-sow/data/base-directory")
    view = ProjectFiles.open_view(tmp_path, ".ai-sow/.stage-0123456789ab")
    view.ensure_dir(".ai-sow/data/staged-directory")

    for relative_path in (
        ".ai-sow/data/base-directory",
        ".ai-sow/data/staged-directory",
    ):
        with pytest.raises(ProjectIOError) as raised:
            view.tombstone(relative_path)
        assert raised.value.code == "PROJECT_PATH_TYPE"
        assert view.resolve(relative_path, expect="dir").is_dir()


def test_publish_tree_new_creates_reuses_and_rejects_extra_files(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = tmp_path / "source"
    project.mkdir()
    (source / "nested").mkdir(parents=True)
    (source / "a.txt").write_bytes(b"a")
    (source / "nested/b.txt").write_bytes(b"b")
    files = ProjectFiles.open(project)

    assert files.publish_tree_new(source, ".ai-sow/data/tree") == "CREATED"
    assert files.publish_tree_new(source, ".ai-sow/data/tree") == "REUSED"
    files.write_atomic(".ai-sow/data/tree/extra.txt", b"extra")
    with pytest.raises(ProjectIOError) as raised:
        files.publish_tree_new(source, ".ai-sow/data/tree")
    assert raised.value.code == "PROJECT_CONTENT_CONFLICT"


@requires_symlinks
def test_publish_tree_new_rejects_symlinked_source_entry(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = tmp_path / "source"
    project.mkdir()
    source.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")
    (source / "link.txt").symlink_to(outside)

    with pytest.raises(ProjectIOError) as raised:
        ProjectFiles.open(project).publish_tree_new(source, ".ai-sow/data/tree")
    assert raised.value.code == "PROJECT_PATH_UNSAFE"
    assert not (project / ".ai-sow/data/tree/link.txt").exists()


def test_remove_managed_tree_requires_an_exact_narrow_allowed_root(tmp_path: Path) -> None:
    files = ProjectFiles.open(tmp_path)
    files.write_atomic(".ai-sow/work/nested/value.json", b"{}\n")
    files.remove_managed_tree(
        ".ai-sow/work/nested",
        allowed_roots=(".ai-sow/work",),
    )
    assert not (tmp_path / ".ai-sow/work/nested").exists()

    for broad in (
        ".ai-sow",
        ".ai-sow/inputs",
        ".ai-sow/inputs/revisions",
        ".ai-sow/generations",
        ".ai-sow/$UNRESOLVED",
    ):
        with pytest.raises(ProjectIOError) as raised:
            files.remove_managed_tree(broad, allowed_roots=(broad,))
        assert raised.value.code == "PROJECT_DELETE_SCOPE_INVALID"
