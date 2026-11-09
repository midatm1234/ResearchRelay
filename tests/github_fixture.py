"""Verified GitHub identities for protocol tests; OAuth itself has separate tests."""
from fastapi.responses import JSONResponse

from researchrelay.api import create_app
from researchrelay.github_auth import GitHubIdentity
from researchrelay.managed_context import managed_identity


def authenticated_app(settings, engine=None):
    app = create_app(settings, engine)
    identities = {f'github-{login}-test-token': GitHubIdentity(index, login, f'github-{login}-test-token')
                  for index, login in enumerate(('human', 'alice', 'bob'), 1)}

    @app.middleware('http')
    async def github_account(request, call_next):
        credential = request.headers.get('authorization', '').removeprefix('Bearer ')
        identity = identities.get(credential)
        if identity is None:
            return JSONResponse({'detail': 'Sign in with GitHub.'}, status_code=401)
        context = managed_identity.set(dict(identity=identity,
            role='admin' if identity.login == 'human' else 'write', demo=True))
        try:
            return await call_next(request)
        finally:
            managed_identity.reset(context)

    return app
