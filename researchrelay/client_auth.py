"""Use the participant's existing GitHub authentication for managed CLI work."""
import os
import re
import subprocess
from urllib.parse import urlparse


def github_token(server):
    target = urlparse(server)
    if not re.fullmatch(r'/projects/[^/]+/?', target.path):
        return None
    if target.scheme != 'https' and not (target.scheme == 'http' and target.hostname in {'localhost', '127.0.0.1', '::1'}):
        raise RuntimeError('Use HTTPS for a shared ResearchRelay server, or HTTP on loopback.')
    token = os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN')
    if token:
        return token
    try:
        result = subprocess.run(['gh', 'auth', 'token', '--hostname', 'github.com'],
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result and result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    raise RuntimeError('Sign in to your GitHub account with gh auth login --hostname github.com, then retry.')


def authorization_headers(server):
    token = github_token(server)
    return {'Authorization': 'Bearer '+token} if token else {}
