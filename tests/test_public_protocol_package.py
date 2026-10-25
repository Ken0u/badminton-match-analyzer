"""Generated source archives must retain public protocols and exclude local data."""

import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "public_protocol_package", ROOT / "scripts/verify_package.py"
)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def archive_fixture(tmp_path, monkeypatch):
    backend = {"badminton/__init__.py": b"# generated runtime\n"}
    public = {
        "data/manifests/first.json": b'{"protocol":"generated first"}\n',
        "data/manifests/second.json": b'{"protocol":"generated second"}\n',
    }
    metadata = {
        "uv.lock": b"# generated lock\n",
        "pyproject.toml": b"# generated metadata\n",
        ".python-version": b"3.12\n",
        ".node-version": b"24\n",
    }
    for name, raw in metadata.items():
        (tmp_path / name).write_bytes(raw)
    wheel = tmp_path / "generated.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, raw in backend.items():
            archive.writestr(name, raw)
    members = [(name, raw, None) for name, raw in metadata.items()]
    members += [("backend/" + name, raw, None) for name, raw in backend.items()]
    members += [(name, raw, None) for name, raw in public.items()]
    monkeypatch.setattr(package, "package_sources", lambda root: backend.copy())
    monkeypatch.setattr(package, "public_manifest_sources", lambda root: public.copy())
    monkeypatch.setattr(package, "frontend_assets", lambda root: {})

    def verify(rows=None):
        source = tmp_path / "generated.tar.gz"
        with tarfile.open(source, "w:gz") as archive:
            for name, raw, kind in members if rows is None else rows:
                item = tarfile.TarInfo("generated-1/" + name)
                if kind is not None:
                    item.type = kind
                    if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                        item.linkname = "outside.json"
                else:
                    item.size = len(raw)
                archive.addfile(item, io.BytesIO(raw) if kind is None else None)
        return package.verify_archives(tmp_path, wheel, source)

    return public, members, verify, wheel


def test_public_protocol_archive_is_exact_and_runtime_wheel_unchanged(
    tmp_path, monkeypatch
):
    public, _, verify, wheel = archive_fixture(tmp_path, monkeypatch)
    before = wheel.read_bytes()
    result = verify()
    assert result["public_manifest_files"] == len(public) == 2
    assert result["package_files"] == 1 and result["frontend_files"] == 0
    assert wheel.read_bytes() == before
    with zipfile.ZipFile(wheel) as archive:
        assert archive.namelist() == ["badminton/__init__.py"]


@pytest.mark.parametrize("change", ["missing", "altered", "duplicate", "new_tracked"])
def test_public_manifest_omission_mutation_and_duplicates_fail(
    tmp_path, monkeypatch, change
):
    public, rows, verify, _ = archive_fixture(tmp_path, monkeypatch)
    name = next(iter(public))
    if change == "missing":
        rows = [row for row in rows if row[0] != name]
    elif change == "altered":
        rows = [(n, b"changed" if n == name else raw, kind) for n, raw, kind in rows]
    elif change == "duplicate":
        rows.append((name, public[name], None))
    else:
        public["data/manifests/newly-tracked.json"] = b"{}\n"
    with pytest.raises(ValueError, match="public manifest"):
        verify(rows)


@pytest.mark.parametrize(
    "name",
    [
        "data/manifests/untracked.json",
        "data/manifests/.private.json",
        "data/manifests/nested/private.json",
        "data/datasets/labels.json",
        "data/raw/source.mp4",
        "data/weights/model.pt",
        "data/.env",
        "data/readme.txt",
    ],
)
def test_extra_data_never_hitches_a_ride_in_public_archive(tmp_path, monkeypatch, name):
    _, rows, verify, _ = archive_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="data in source distribution"):
        verify([*rows, (name, b"generated private canary", None)])


@pytest.mark.parametrize(
    "name",
    ["../escape.json", "/absolute.json", "data\\manifests\\extra.json", "data//x.json"],
)
def test_unsafe_source_members_are_rejected(tmp_path, monkeypatch, name):
    _, rows, verify, _ = archive_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Unsafe source distribution"):
        verify([*rows, (name, b"{}", None)])


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE]
)
def test_nonordinary_data_members_are_rejected(tmp_path, monkeypatch, kind):
    _, rows, verify, _ = archive_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="source distribution"):
        verify([*rows, ("data/manifests/first.json", b"", kind)])


def test_only_public_data_parent_directories_are_accepted(tmp_path, monkeypatch):
    _, rows, verify, _ = archive_fixture(tmp_path, monkeypatch)
    assert (
        verify(
            [
                ("data", b"", tarfile.DIRTYPE),
                ("data/manifests", b"", tarfile.DIRTYPE),
                *rows,
            ]
        )["public_manifest_files"]
        == 2
    )
    with pytest.raises(ValueError, match="Unexpected data"):
        verify([*rows, ("data/private", b"", tarfile.DIRTYPE)])


def test_missing_reproducibility_metadata_still_fails(tmp_path, monkeypatch):
    _, rows, verify, _ = archive_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="reproducibility"):
        verify([row for row in rows if row[0] != "uv.lock"])


def tracked_sources(tmp_path, monkeypatch, names):
    calls = []

    def git(command, *, cwd):
        calls.append((command, cwd))
        return "\0".join([*names, ""]).encode("utf-8")

    monkeypatch.setattr(package.subprocess, "check_output", git)
    return calls


def test_git_tracked_public_set_never_globs_untracked_json(tmp_path, monkeypatch):
    folder = tmp_path / "data/manifests"
    folder.mkdir(parents=True)
    tracked, untracked = folder / "public.json", folder / "private.json"
    tracked.write_bytes(b'{"generated":"public"}\n')
    untracked.write_bytes(b"generated private canary")
    names = ["data/manifests/public.json", "data/manifests/README.md"]
    calls = tracked_sources(tmp_path, monkeypatch, names)
    result = package.public_manifest_sources(tmp_path)
    assert result == {names[0]: tracked.read_bytes()}
    assert untracked.read_bytes() == b"generated private canary"
    assert calls == [(["git", "ls-files", "-z", "--", "data/manifests"], tmp_path)]


@pytest.mark.parametrize(
    "name",
    [
        "../data/manifests/file.json",
        "/data/manifests/file.json",
        "data/manifests/nested/file.json",
        "data\\manifests\\file.json",
        "data/manifests/../file.json",
    ],
)
def test_invalid_git_public_paths_fail_closed(tmp_path, monkeypatch, name):
    tracked_sources(tmp_path, monkeypatch, [name])
    with pytest.raises(ValueError, match="Invalid tracked"):
        package.public_manifest_sources(tmp_path)


def test_missing_or_duplicate_tracked_public_files_fail_closed(tmp_path, monkeypatch):
    name = "data/manifests/public.json"
    tracked_sources(tmp_path, monkeypatch, [name])
    with pytest.raises(ValueError, match="missing"):
        package.public_manifest_sources(tmp_path)
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b"{}\n")
    tracked_sources(tmp_path, monkeypatch, [name, name])
    with pytest.raises(ValueError, match="Invalid tracked"):
        package.public_manifest_sources(tmp_path)


def test_empty_public_inventory_is_not_silently_accepted(tmp_path, monkeypatch):
    tracked_sources(tmp_path, monkeypatch, [])
    with pytest.raises(ValueError, match="No tracked"):
        package.public_manifest_sources(tmp_path)


@pytest.mark.parametrize("target", ["file", "parent"])
def test_symlink_public_source_cannot_follow_local_data(tmp_path, monkeypatch, target):
    real = tmp_path / "private.json"
    real.write_bytes(b"private generated canary")
    folder = tmp_path / "data/manifests"
    folder.mkdir(parents=True)
    path = folder / "public.json"
    try:
        if target == "file":
            path.symlink_to(real)
        else:
            actual = tmp_path / "actual"
            actual.mkdir()
            (actual / "public.json").write_bytes(b"{}")
            folder.rmdir()
            folder.symlink_to(actual, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation unavailable on this host")
    tracked_sources(tmp_path, monkeypatch, ["data/manifests/public.json"])
    with pytest.raises(ValueError, match="Symlink"):
        package.public_manifest_sources(tmp_path)
    assert real.read_bytes() == b"private generated canary"


def test_source_manifest_uses_literal_existing_public_paths_only():
    lines = (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
    includes = [line.split()[1] for line in lines if line.startswith("include data/")]
    assert includes and len(includes) == len(set(includes))
    assert "data/manifests/rally_review_contract_v1.json" in includes
    for name in includes:
        assert package.safe_relative(name)
        assert not any(character in name for character in "*?[]")
        assert PurePosixPath(name).parts == ("data", "manifests", Path(name).name)
        assert name.endswith(".json") and (ROOT / name).is_file()
    assert not any(
        "include data" in line and not line.startswith("include data/")
        for line in lines
    )


@pytest.mark.parametrize("target", ["file", "parent"])
def test_windows_reparse_flags_cannot_redirect_public_source(
    tmp_path, monkeypatch, target
):
    name = "data/manifests/public.json"
    source = tmp_path / name
    source.parent.mkdir(parents=True)
    source.write_bytes(b"{}")
    tracked_sources(tmp_path, monkeypatch, [name])
    selected = source if target == "file" else source.parent
    original = Path.lstat

    def reparse(item):
        info = original(item)
        return (
            SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            if item == selected
            else info
        )

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(ValueError, match="reparse"):
        package.public_manifest_sources(tmp_path)
