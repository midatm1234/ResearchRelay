"""Installation markers must preserve both native Mac architectures."""
from pathlib import Path
import tomllib
import pytest
from packaging.requirements import Requirement
from packaging.markers import default_environment

ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize("system,machine,version",[
    ("darwin","x86_64","48.0.1"),("darwin","arm64","50.0.2"),
    ("win32","AMD64","50.0.2"),("linux","x86_64","50.0.2"),("linux","aarch64","50.0.2")])
def test_encryption_dependency_resolves_without_an_intel_mac_source_build(system,machine,version):
    environment = dict(default_environment(),sys_platform=system,platform_machine=machine)
    metadata = tomllib.loads((ROOT/"pyproject.toml").read_text(encoding="utf-8"))
    constraints = [Requirement(value) for value in metadata["project"]["dependencies"] if value.startswith("cryptography")]
    lock = [Requirement(value) for value in (ROOT/"requirements.lock.txt").read_text().splitlines() if value.startswith("cryptography")]
    selected = [value for value in constraints if value.marker.evaluate(environment)]
    pinned = [value for value in lock if value.marker.evaluate(environment)]
    assert len(selected)==len(pinned)==1
    assert version in selected[0].specifier
    assert str(pinned[0].specifier)=="=="+version
