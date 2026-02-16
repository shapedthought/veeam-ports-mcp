"""Tests for service matching helpers used by generate_app_import."""

import pytest

from veeam_ports_mcp.server import (
    _find_server,
    _has_conflicting_os,
    _normalise_service,
)


# ---------------------------------------------------------------------------
# _normalise_service
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Backup proxy (Linux)", "backup proxy"),
    ("Backup proxy (Microsoft Windows)", "backup proxy"),
    ("Backup proxy (Linux/Unix)", "backup proxy"),
    ("Backup proxy", "backup proxy"),
    ("  Backup proxy (Linux)  ", "backup proxy"),
    ("ESXi host", "esxi host"),
])
def test_normalise_service(raw, expected):
    assert _normalise_service(raw) == expected


# ---------------------------------------------------------------------------
# _has_conflicting_os
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("entry,server,conflict", [
    # Different OS → conflict
    ("Backup proxy (Microsoft Windows)", "Backup proxy (Linux)", True),
    ("Backup proxy (Linux)", "Backup proxy (Microsoft Windows)", True),
    # Same OS → no conflict
    ("Backup proxy (Linux)", "Backup proxy (Linux)", False),
    ("Backup proxy (Linux/Unix)", "Backup proxy (Linux)", False),
    # Generic entry → no conflict
    ("Backup proxy", "Backup proxy (Linux)", False),
    ("Backup proxy", "Backup proxy (Microsoft Windows)", False),
    # Both generic → no conflict
    ("Backup proxy", "Backup proxy", False),
])
def test_has_conflicting_os(entry, server, conflict):
    assert _has_conflicting_os(entry, server) is conflict


# ---------------------------------------------------------------------------
# _find_server
# ---------------------------------------------------------------------------

def _make_server_map(servers):
    """Build a server_map dict from a simple list of (name, services) tuples."""
    return {
        name: {"id": f"id-{i}", "services": services, "mappedPorts": []}
        for i, (name, services) in enumerate(servers)
    }


class TestFindServerExactMatch:
    def test_exact_case_insensitive(self):
        sm = _make_server_map([("Proxy", ["Backup proxy (Linux)"])])
        assert _find_server("Backup proxy (Linux)", sm) == "Proxy"
        assert _find_server("backup proxy (linux)", sm) == "Proxy"

    def test_exact_match_preferred_over_normalised(self):
        sm = _make_server_map([
            ("WinProxy", ["Backup proxy (Microsoft Windows)"]),
            ("LinProxy", ["Backup proxy (Linux)"]),
        ])
        assert _find_server("Backup proxy (Linux)", sm) == "LinProxy"
        assert _find_server("Backup proxy (Microsoft Windows)", sm) == "WinProxy"


class TestFindServerNormalisedMatch:
    """Generic port entries should match OS-qualified server services."""

    def test_generic_entry_matches_linux_server(self):
        sm = _make_server_map([("Proxy", ["Backup proxy (Linux)"])])
        assert _find_server("Backup proxy", sm) == "Proxy"

    def test_generic_entry_matches_windows_server(self):
        sm = _make_server_map([("Proxy", ["Backup proxy (Microsoft Windows)"])])
        assert _find_server("Backup proxy", sm) == "Proxy"

    def test_os_conflict_rejected(self):
        sm = _make_server_map([("LinProxy", ["Backup proxy (Linux)"])])
        # Windows-specific entry should NOT match a Linux server
        assert _find_server("Backup proxy (Microsoft Windows)", sm) is None


class TestFindServerSubstringMatch:
    def test_compound_service_matches(self):
        sm = _make_server_map([("Proxy", ["Backup proxy (Linux)"])])
        result = _find_server(
            "Backup proxy or Hyper-V server/Off-host backup proxy", sm
        )
        assert result == "Proxy"

    def test_no_false_substring_match(self):
        sm = _make_server_map([("ESXi", ["ESXi host"])])
        # "ESXi server" is a different role; "host" is not a substring of "server"
        assert _find_server("ESXi server", sm) is None


class TestFindServerNoMatch:
    def test_completely_unrelated(self):
        sm = _make_server_map([("Proxy", ["Backup proxy (Linux)"])])
        assert _find_server("vCenter Server", sm) is None
