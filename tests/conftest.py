"""Keep unit/integration fixtures offline despite the application GitHub default."""
import os

import pytest


@pytest.fixture(autouse=True)
def isolated_project_environment(monkeypatch, tmp_path):
    # A developer's live .env and credentials must not select a real project in
    # temporary test coordinators. Default-configuration tests opt back in by
    # deleting these two explicit overrides; live GitHub reads are separate.
    for key in tuple(os.environ):
        if key.upper().startswith("RESEARCHRELAY_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("RESEARCHRELAY_MODE", "demo")
    monkeypatch.setenv("RESEARCHRELAY_GITHUB_URL", "")
    monkeypatch.setenv("RESEARCHRELAY_DB", str(tmp_path/"implicit-project"/"state.db"))
    monkeypatch.setenv("RESEARCHRELAY_REPO", str(tmp_path/"implicit-project"/"record"))
