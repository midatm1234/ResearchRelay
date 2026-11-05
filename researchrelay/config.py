"""Local configuration; credentials are never part of project artifacts."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_GITHUB_URL = 'git@github.com:midatm1234/ResearchRelay.git'
DEFAULT_GITHUB_BRANCH = 'SRTD_DT_test'


@dataclass
class Settings:
    db_path: Path = field(default_factory=lambda: Path(os.getenv('RESEARCHRELAY_DB', '.runtime/literature/state.db')))
    repo_path: Path = field(default_factory=lambda: Path(os.getenv('RESEARCHRELAY_REPO', '.runtime/literature/project-record')))
    project_id: str = field(default_factory=lambda: os.getenv('RESEARCHRELAY_PROJECT', 'agentic-collaboration'))
    mode: str = field(default_factory=lambda: os.getenv('RESEARCHRELAY_MODE', 'live'))
    tokens: dict = field(default_factory=lambda: json.loads(os.getenv('RESEARCHRELAY_TOKENS', '{}')))
    github_base: str = field(default_factory=lambda: os.getenv('RESEARCHRELAY_GITHUB_BASE', 'main'))

    github_url: str | None = field(default_factory=lambda: os.getenv('RESEARCHRELAY_GITHUB_URL', DEFAULT_GITHUB_URL) or None)
    github_branch: str = field(default_factory=lambda: os.getenv('RESEARCHRELAY_GITHUB_BRANCH', DEFAULT_GITHUB_BRANCH))
    knowledge_path: str | None = field(default_factory=lambda: os.getenv('RESEARCHRELAY_KNOWLEDGE_PATH') or None)
    sync_interval: float = field(default_factory=lambda: float(os.getenv('RESEARCHRELAY_SYNC_INTERVAL', '15')))

    hub_path: Path | None = field(default_factory=lambda: Path(os.environ['RESEARCHRELAY_HUB_PATH']) if os.getenv('RESEARCHRELAY_HUB_PATH') else None)
    project_demo: bool = field(default_factory=lambda: os.getenv('RESEARCHRELAY_PROJECT_DEMO', '').lower() in {'1','true'})
    oauth_client_id: str = field(default_factory=lambda: os.getenv('RESEARCHRELAY_GITHUB_CLIENT_ID', ''))
    oauth_client_secret: str = field(default_factory=lambda: os.getenv('RESEARCHRELAY_GITHUB_CLIENT_SECRET', ''), repr=False)
    public_url: str = field(default_factory=lambda: os.getenv('RESEARCHRELAY_PUBLIC_URL', 'http://127.0.0.1:8000').rstrip('/'))

    def __post_init__(self):
        self.db_path = Path(self.db_path).expanduser()
        self.repo_path = Path(self.repo_path).expanduser()
        self.hub_path = Path(self.hub_path).expanduser() if self.hub_path else self.db_path.parent / 'project-hub'
        if not 1 <= self.sync_interval <= 300:
            raise ValueError('RESEARCHRELAY_SYNC_INTERVAL must be between 1 and 300 seconds')
        if self.mode not in {'demo', 'live'}:
            raise ValueError('RESEARCHRELAY_MODE must be demo or live')


load_dotenv()
