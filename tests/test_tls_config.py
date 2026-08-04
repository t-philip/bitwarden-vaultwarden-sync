"""Tests for destination TLS handling.

BW_DEST_TLS_VERIFY previously reached only the `api` wipe path, so it did not do
what its name implied — bw CLI calls still failed against a self-signed
destination. These cover the environment the CLI is actually given.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from bwsync.config import Config
from bwsync.session import BwSession


def _session(tmp_path, **kwargs) -> BwSession:
    return BwSession(
        server_url="https://vault.example.com",
        client_id="id",
        client_secret="secret",
        master_password="pw",
        config_dir=tmp_path / "appdata",
        label="destination",
        **kwargs,
    )


class TestSessionEnvironment:
    def test_default_sets_no_tls_overrides(self, tmp_path):
        """Verification on and no bundle: Node's own trust store is used."""
        env = _session(tmp_path)._env()
        assert "NODE_EXTRA_CA_CERTS" not in env
        assert "NODE_TLS_REJECT_UNAUTHORIZED" not in env

    def test_ca_bundle_exported_to_node(self, tmp_path):
        bundle = tmp_path / "ca.pem"
        bundle.write_text("-----BEGIN CERTIFICATE-----", encoding="utf-8")
        env = _session(tmp_path, ca_bundle=bundle)._env()
        assert env["NODE_EXTRA_CA_CERTS"] == str(bundle)
        # A bundle keeps verification ON — this is the whole point of preferring it.
        assert "NODE_TLS_REJECT_UNAUTHORIZED" not in env

    def test_verify_disabled_falls_back_to_node_flag(self, tmp_path):
        env = _session(tmp_path, tls_verify=False)._env()
        assert env["NODE_TLS_REJECT_UNAUTHORIZED"] == "0"

    def test_ca_bundle_wins_over_disabled_verification(self, tmp_path):
        """A bundle is the safer mechanism, so it takes precedence."""
        bundle = tmp_path / "ca.pem"
        bundle.write_text("x", encoding="utf-8")
        env = _session(tmp_path, ca_bundle=bundle, tls_verify=False)._env()
        assert env["NODE_EXTRA_CA_CERTS"] == str(bundle)
        assert "NODE_TLS_REJECT_UNAUTHORIZED" not in env

    def test_appdata_dir_still_set(self, tmp_path):
        env = _session(tmp_path)._env()
        assert env["BITWARDENCLI_APPDATA_DIR"] == str(tmp_path / "appdata")


def _config(**overrides) -> Config:
    base = dict(
        bw_source_url="https://vault.bitwarden.com",
        bw_source_email="a@example.com",
        bw_source_client_id="i", bw_source_client_secret="s", bw_source_password="p",
        bw_dest_url="https://vault.example.com",
        bw_dest_email="a@example.com",
        bw_dest_client_id="i", bw_dest_client_secret="s", bw_dest_password="p",
        vw_wipe_method="cli",
        bw_dest_tls_verify=True,
        bw_dest_ca_bundle=None,
        backup_enabled=False,
        backup_dir=Path("/tmp/backups"),
        backup_gpg_passphrase="",
        backup_retention_days=7,
        telegram_bot_token="", telegram_chat_id="",
        temp_dir=Path("/tmp/bw"), appdata_dir=Path("/tmp/appdata"),
        log_level="INFO",
    )
    base.update(overrides)
    return Config(**base)


class TestConfigValidation:
    def test_missing_ca_bundle_rejected(self, tmp_path):
        """Node silently ignores an unreadable NODE_EXTRA_CA_CERTS and falls back
        to the system store, so a typo would otherwise degrade quietly."""
        cfg = _config(bw_dest_ca_bundle=tmp_path / "nope.pem")
        with pytest.raises(ValueError, match="does not exist"):
            cfg.validate()

    def test_existing_ca_bundle_accepted(self, tmp_path):
        bundle = tmp_path / "ca.pem"
        bundle.write_text("x", encoding="utf-8")
        _config(bw_dest_ca_bundle=bundle).validate()

    def test_no_bundle_is_fine(self):
        _config().validate()
