"""Pinned patch reconstruction rejects tampered artifacts before installation."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("memory_install_contract", ROOT / "integrations/memory-providers/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def package(tmp_path, monkeypatch):
    source = {"README.md": b"upstream\n", "LICENSE": b"fixture license\n"}
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as stream:
        for name, data in source.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            stream.addfile(entry, io.BytesIO(data))
    monkeypatch.setattr(installer, "git", lambda *args, **kwargs: archive.getvalue())
    metadata = tmp_path / "metadata"
    (metadata / "patches").mkdir(parents=True)
    patch = b"--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-upstream\n+reviewed\n"
    (metadata / "patches/honcho.patch").write_bytes(patch)
    result = dict(source, **{"README.md": b"reviewed\n"})
    pin = {"commit": "a" * 40, "subdir": "plugin", "source_sha256": installer.digest(source),
           "patch_sha256": hashlib.sha256(patch).hexdigest(), "result_sha256": installer.digest(result)}
    (metadata / "manifest.json").write_text(json.dumps({"providers": {"honcho": pin}}))
    monkeypatch.setattr(installer, "HERE", metadata)
    return metadata, tmp_path / "destination", tmp_path / "cache", pin, result


def test_exact_reconstruction_and_existing_destination_refusal(package):
    _, destination, cache, _, expected = package
    installer.reconstruct("honcho", destination, cache)
    assert {p.name: p.read_bytes() for p in destination.iterdir()} == expected
    with pytest.raises(FileExistsError):
        installer.reconstruct("honcho", destination, cache)
    assert (destination / "README.md").read_bytes() == b"reviewed\n"


@pytest.mark.parametrize("field,message", [
    ("source_sha256", "source digest"), ("patch_sha256", "Patch digest"),
    ("result_sha256", "plugin digest"),
])
def test_corrupted_inventory_does_not_install(package, field, message):
    metadata, destination, cache, pin, _ = package
    pin[field] = "0" * 64
    (metadata / "manifest.json").write_text(json.dumps({"providers": {"honcho": pin}}))
    with pytest.raises(ValueError, match=message):
        installer.reconstruct("honcho", destination, cache)
    assert not destination.exists()


def test_patch_mutation_does_not_install(package):
    metadata, destination, cache, _, _ = package
    patch = metadata / "patches/honcho.patch"
    patch.write_bytes(patch.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="Patch digest"):
        installer.reconstruct("honcho", destination, cache)
    assert not destination.exists()


@pytest.mark.parametrize("name,kind", [("../escape", tarfile.REGTYPE),
                                      ("/absolute", tarfile.REGTYPE), ("link", tarfile.SYMTYPE)])
def test_unsafe_archive_entries_are_rejected(package, monkeypatch, name, kind):
    _, destination, cache, _, _ = package
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as stream:
        entry = tarfile.TarInfo(name)
        entry.type = kind
        entry.linkname = "README.md"
        stream.addfile(entry)
    monkeypatch.setattr(installer, "git", lambda *args, **kwargs: archive.getvalue())
    with pytest.raises(ValueError):
        installer.reconstruct("honcho", destination, cache)
    assert not destination.exists()
