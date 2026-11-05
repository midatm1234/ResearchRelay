"""Request-local GitHub identity, never a browser-visible credential."""
from contextvars import ContextVar
import base64
import hashlib
import json
import os
import threading

from .sync import ProjectSync, SyncError

managed_identity = ContextVar("researchrelay_managed_identity", default=None)


class ManagedProjectSync(ProjectSync):
    def __init__(self,settings,engine):
        super().__init__(settings,engine)
        self._lock = threading.RLock()
        self.root = settings.repo_path.parent/"git"

    def _cache(self):
        binding = self._validate_binding(self.binding)
        return self.root/hashlib.sha256(json.dumps(binding,sort_keys=True).encode()).hexdigest()[:20]

    def _git(self,path,*arguments,**options):
        try:
            return super()._git(path,*arguments,**options)
        except SyncError as error:
            if error.kind=="authentication_error":
                raise SyncError("GitHub rejected this participant's Git access.",401,kind="authentication_error",
                    next_action="Reconnect your GitHub account and verify repository contents access and organization SSO authorization.") from None
            raise

    def _validate_prospective(self,cache,latest,documents,changes):
        from .providers import guard_output_bytes, ProviderError
        current = managed_identity.get()
        token = current["identity"].token.encode() if current and not current.get("demo") else None
        try:
            for change in changes:
                guard_output_bytes(change["content"].encode(),[token] if token else [])
        except ProviderError:
            raise SyncError("A possible credential was found in a proposed or generated project document.",422,
                kind="validation",next_action="Remove the credential before publishing; keep it in your private environment.") from None
        return super()._validate_prospective(cache,latest,documents,changes)

    def _environment(self, base=None):
        current = managed_identity.get()
        if not current:
            raise SyncError("Sign in to GitHub before synchronizing this project.",401,kind="authentication_error")
        environment = super()._environment(base)
        # Disable ambient credential helpers, traces, URL rewrites and hooks.
        for key in list(environment):
            if key.startswith(("GIT_CONFIG_", "GIT_TRACE", "GIT_CURL", "RESEARCHRELAY_")) or key in {"GIT_ASKPASS","SSH_ASKPASS"}:
                environment.pop(key,None)
        values = [("core.longpaths","true"),("core.autocrlf","false"),("credential.helper",""),("http.followRedirects","false"),
                  ("http.sslVerify","true"),("core.hooksPath",os.devnull),
                  ("protocol.file.allow","always" if current.get("demo") else "never")]
        token = current["identity"].token
        if not current.get("demo"):
            encoded = base64.b64encode(("x-access-token:"+token).encode()).decode()
            values.append(("http.https://github.com/.extraHeader","Authorization: Basic "+encoded))
        environment.update(GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_NOSYSTEM="1",GIT_CONFIG_COUNT=str(len(values)))
        for index,(key,value) in enumerate(values):
            environment[f"GIT_CONFIG_KEY_{index}"] = key
            environment[f"GIT_CONFIG_VALUE_{index}"] = value
        return environment

    def configure(self,*args,**kwargs):
        raise SyncError("Managed project bindings are fixed. Connect another project from Projects instead.",409,
                        kind="configuration",next_action="Open Projects and choose New Project or Join existing project.")
