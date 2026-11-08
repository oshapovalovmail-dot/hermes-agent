"""Rebuild exact external providers offline, then load through native manifest gates.

The aliases only stabilize test import names; they do not import plugin bytes or
change the host's public-API/private-import policy.
"""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType

from plugins.memory import import_provider_module, load_memory_provider

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "integrations/memory-providers/install.py"
spec = importlib.util.spec_from_file_location("memory_patch_installer", INSTALL)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def pytest_addoption(parser):
    parser.addoption("--memory-source-cache", default=str(ROOT / ".provider-sources"),
                     help="offline Git object caches matching integrations/memory-providers/manifest.json")


def pytest_configure(config):
    stage = tempfile.TemporaryDirectory(prefix="memory-provider-tests-")
    config.add_cleanup(stage.cleanup)
    home = Path(stage.name)
    old_home = os.environ.get("HERMES_HOME")
    package = ModuleType("memory_test_plugins")
    package.__path__ = []
    sys.modules[package.__name__] = package
    try:
        os.environ["HERMES_HOME"] = str(home)
        for name in ("honcho", "openviking"):
            installer.reconstruct(name, home / "plugins" / name, Path(config.getoption("--memory-source-cache")))
            provider = load_memory_provider(name, register_skills=False)
            if provider is None:
                raise ImportError(f"Native manifest/discovery load refused {name}")
            module = import_provider_module(name)
            setattr(package, name, module)
            for key, value in list(sys.modules.items()):
                if key == module.__name__ or key.startswith(module.__name__ + "."):
                    sys.modules["memory_test_plugins." + name + key[len(module.__name__):]] = value
    finally:
        if old_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = old_home
