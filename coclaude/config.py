"""Local configuration; credentials are never part of project artifacts."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Settings:
    db_path: Path = field(default_factory=lambda: Path(os.getenv('COCLAUDE_DB', '.runtime/state.db')))
    repo_path: Path = field(default_factory=lambda: Path(os.getenv('COCLAUDE_REPO', '.runtime/project-repo')))
    project_id: str = field(default_factory=lambda: os.getenv('COCLAUDE_PROJECT', 'forecast-pilot'))
    mode: str = field(default_factory=lambda: os.getenv('COCLAUDE_MODE', 'demo'))
    tokens: dict = field(default_factory=lambda: json.loads(os.getenv('COCLAUDE_TOKENS', '{}')))
    github_base: str = field(default_factory=lambda: os.getenv('COCLAUDE_GITHUB_BASE', 'main'))

    def __post_init__(self):
        self.db_path = Path(self.db_path)
        self.repo_path = Path(self.repo_path)
        if self.mode not in {'demo', 'live'}:
            raise ValueError('COCLAUDE_MODE must be demo or live')


load_dotenv()
