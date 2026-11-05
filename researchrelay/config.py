"""Local configuration; credentials are never part of project artifacts."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Settings:
    db_path: Path = field(default_factory=lambda: Path(os.getenv('RESEARCHRELAY_DB', '.runtime/literature/state.db')))
    repo_path: Path = field(default_factory=lambda: Path(os.getenv('RESEARCHRELAY_REPO', '.runtime/literature/project-record')))
    project_id: str = field(default_factory=lambda: os.getenv('RESEARCHRELAY_PROJECT', 'agentic-collaboration'))
    mode: str = field(default_factory=lambda: os.getenv('RESEARCHRELAY_MODE', 'demo'))
    tokens: dict = field(default_factory=lambda: json.loads(os.getenv('RESEARCHRELAY_TOKENS', '{}')))
    github_base: str = field(default_factory=lambda: os.getenv('RESEARCHRELAY_GITHUB_BASE', 'main'))

    github_url: str | None = field(default_factory=lambda: os.getenv('RESEARCHRELAY_GITHUB_URL') or None)
    github_branch: str = field(default_factory=lambda: os.getenv('RESEARCHRELAY_GITHUB_BRANCH', 'main'))
    knowledge_path: str | None = field(default_factory=lambda: os.getenv('RESEARCHRELAY_KNOWLEDGE_PATH') or None)
    sync_interval: float = field(default_factory=lambda: float(os.getenv('RESEARCHRELAY_SYNC_INTERVAL', '15')))

    def __post_init__(self):
        self.db_path = Path(self.db_path).expanduser()
        self.repo_path = Path(self.repo_path).expanduser()
        if not 1 <= self.sync_interval <= 300:
            raise ValueError('RESEARCHRELAY_SYNC_INTERVAL must be between 1 and 300 seconds')
        if self.mode not in {'demo', 'live'}:
            raise ValueError('RESEARCHRELAY_MODE must be demo or live')


load_dotenv()
