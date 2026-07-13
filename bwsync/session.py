import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("bwsync")

_BITWARDEN_DEFAULT_URLS = {
    "https://bitwarden.com",
    "https://vault.bitwarden.com",
}


class BwSession:
    """Wrapper around the Bitwarden CLI for a single vault (source or destination)."""

    def __init__(
        self,
        server_url: str,
        client_id: str,
        client_secret: str,
        master_password: str,
        config_dir: Path,
        label: str = "",
    ):
        self.server_url = server_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.master_password = master_password
        self.config_dir = config_dir
        self.label = label or server_url
        self._session_key: Optional[str] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _env(self, extra: Optional[dict] = None) -> dict:
        env = os.environ.copy()
        env["BITWARDENCLI_APPDATA_DIR"] = str(self.config_dir)
        if extra:
            env.update(extra)
        return env

    def _run(self, *args: str, extra_env: Optional[dict] = None) -> str:
        env = self._env(extra_env)
        cmd = ["bw", "--nointeraction", *args]
        log.debug("[%s] bw %s", self.label, " ".join(a for a in args if "password" not in a.lower()))
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"bw command failed [{self.label}]: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return result.stdout.strip()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def login(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.config_dir, 0o700)

        # config_dir persists across runs (see sync.py) so the CLI's device_id
        # stays stable and Bitwarden.com stops flagging every run as a new
        # device login. That means a prior run that crashed after login but
        # before logout() could leave this dir in a logged-in state, which
        # `bw login` refuses to do again — force a clean slate first.
        try:
            self._run("logout")
        except Exception:
            pass  # not logged in yet, or a stale/invalid session — ignore

        # Always set server URL explicitly so isolated config dirs start clean
        canonical = (
            "https://vault.bitwarden.com"
            if self.server_url in _BITWARDEN_DEFAULT_URLS
            else self.server_url
        )
        self._run("config", "server", canonical)

        self._run(
            "login", "--apikey",
            extra_env={
                "BW_CLIENTID": self.client_id,
                "BW_CLIENTSECRET": self.client_secret,
            },
        )

    def unlock(self) -> str:
        # Use a named env var so the password never appears as a CLI argument
        pw_var = f"_BWPW_{self.label.upper().replace('-', '_').replace('.', '_')}"
        session_key = self._run(
            "unlock", "--passwordenv", pw_var, "--raw",
            extra_env={pw_var: self.master_password},
        )
        self._session_key = session_key
        return session_key

    def logout(self) -> None:
        try:
            self._run("logout")
        except Exception:
            pass  # best-effort cleanup
        self._session_key = None

    # ------------------------------------------------------------------
    # Authenticated commands
    # ------------------------------------------------------------------

    @property
    def session_key(self) -> str:
        if not self._session_key:
            raise RuntimeError(f"Session not unlocked [{self.label}]. Call unlock() first.")
        return self._session_key

    def run(self, *args: str) -> str:
        return self._run(*args, extra_env={"BW_SESSION": self.session_key})

    def run_json(self, *args: str) -> list:
        output = self.run(*args)
        if not output:
            return []
        parsed = json.loads(output)
        return parsed if isinstance(parsed, list) else [parsed]
