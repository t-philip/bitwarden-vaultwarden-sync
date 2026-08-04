import base64
import hashlib
import logging
import warnings
from typing import TYPE_CHECKING

import requests
import urllib3

if TYPE_CHECKING:
    from .config import Config
    from .session import BwSession

log = logging.getLogger("bwsync")


def wipe_vault(session: "BwSession", cfg: "Config") -> None:
    if cfg.vw_wipe_method == "cli":
        _wipe_via_cli(session)
    else:
        _wipe_via_api(cfg)


# ------------------------------------------------------------------
# Method: cli
# Deletes every item individually using the bw CLI.
# Works with any Vaultwarden KDF setting. Slower for large vaults.
# ------------------------------------------------------------------

def _wipe_via_cli(session: "BwSession") -> None:
    items = session.run_json("list", "items")
    total = len(items)
    log.info("Deleting %d item(s) via CLI…", total)
    for i, item in enumerate(items, 1):
        session.run("delete", "item", item["id"])
        if i % 50 == 0:
            log.info("  %d / %d deleted…", i, total)
    log.debug("CLI wipe complete.")


# ------------------------------------------------------------------
# Method: api
# Single HTTP call to POST /api/ciphers/purge — instant regardless
# of vault size. Requires PBKDF2 KDF (kdf=0); Argon2 vaults must
# use VW_WIPE_METHOD=cli instead.
# ------------------------------------------------------------------

def _wipe_via_api(cfg: "Config") -> None:
    base = cfg.bw_dest_url.rstrip("/")
    # requests accepts a CA bundle path in place of the bool, so a configured
    # bundle keeps verification enabled rather than turning it off.
    verify = str(cfg.bw_dest_ca_bundle) if cfg.bw_dest_ca_bundle else cfg.bw_dest_tls_verify

    if verify is False:
        warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

    # Step 1 — get KDF parameters
    r = requests.post(
        f"{base}/api/accounts/prelogin",
        json={"email": cfg.bw_dest_email},
        timeout=15,
        verify=verify,
    )
    r.raise_for_status()
    prelogin = r.json()

    kdf_type = prelogin.get("kdf", 0)
    if kdf_type != 0:
        raise NotImplementedError(
            "VW_WIPE_METHOD=api only supports PBKDF2 (kdf=0). "
            "Your Vaultwarden is configured with Argon2 (kdf=1). "
            "Switch to VW_WIPE_METHOD=cli."
        )

    iterations = prelogin.get("kdfIterations", 600000)
    log.debug("KDF: PBKDF2-SHA256, %d iterations", iterations)

    # Step 2 — compute master password hash (client-side, per Bitwarden spec)
    master_key = hashlib.pbkdf2_hmac(
        "sha256",
        cfg.bw_dest_password.encode("utf-8"),
        cfg.bw_dest_email.lower().encode("utf-8"),
        iterations,
    )
    master_password_hash = base64.b64encode(
        hashlib.pbkdf2_hmac(
            "sha256",
            master_key,
            cfg.bw_dest_password.encode("utf-8"),
            1,
        )
    ).decode("utf-8")

    # Step 3 — obtain an access token via API key
    r = requests.post(
        f"{base}/identity/connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": cfg.bw_dest_client_id,
            "client_secret": cfg.bw_dest_client_secret,
            "scope": "api",
            "deviceType": 21,
            "deviceName": "bitwarden-vaultwarden-sync",
            "deviceIdentifier": "bwvwsync-purge-client",
        },
        timeout=15,
        verify=verify,
    )
    r.raise_for_status()
    access_token = r.json()["access_token"]

    # Step 4 — purge
    r = requests.post(
        f"{base}/api/ciphers/purge",
        json={"masterPasswordHash": master_password_hash},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
        verify=verify,
    )
    r.raise_for_status()
    log.debug("API purge complete.")
