"""Tests for Bitwarden server-region handling.

BW_SOURCE_URL must pass an official regional cloud (e.g. the EU cloud at
vault.bitwarden.eu) through to `bw config server` unchanged — only known
aliases of the US cloud are normalized.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bwsync.session import canonical_server_url


class TestCanonicalServerUrl:
    def test_us_cloud_bare_domain_normalized(self):
        assert canonical_server_url("https://bitwarden.com") == "https://vault.bitwarden.com"

    def test_us_cloud_vault_domain_unchanged(self):
        assert canonical_server_url("https://vault.bitwarden.com") == "https://vault.bitwarden.com"

    def test_eu_cloud_passed_through_unchanged(self):
        assert canonical_server_url("https://vault.bitwarden.eu") == "https://vault.bitwarden.eu"

    def test_self_hosted_url_passed_through_unchanged(self):
        assert canonical_server_url("https://vault.example.com") == "https://vault.example.com"
