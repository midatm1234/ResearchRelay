"""Serve fresh HTML with asset URLs tied to the current file contents."""
import hashlib
from pathlib import Path
import re

from fastapi.responses import HTMLResponse

STATIC_ROOT = Path(__file__).parent/'static'


def page_response(filename):
    content = (STATIC_ROOT/filename).read_text(encoding='utf-8')

    def version_asset(match):
        name = match['name']
        asset = STATIC_ROOT/name
        if not asset.resolve().is_relative_to(STATIC_ROOT.resolve()) or not asset.is_file():
            return match.group(0)
        version = hashlib.sha256(asset.read_bytes()).hexdigest()[:16]
        return f'{match["attribute"]}/static/{name}?v={version}"'

    content = re.sub(r'(?P<attribute>(?:src|href)=")/static/(?P<name>[^"?]+)"', version_asset, content)
    return HTMLResponse(content, headers={'Cache-Control':'no-store'})
