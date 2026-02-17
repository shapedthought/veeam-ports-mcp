"""Tests for generate_app_import file output and _get_output_dir."""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from veeam_ports_mcp.server import _get_output_dir


# ---------------------------------------------------------------------------
# _get_output_dir
# ---------------------------------------------------------------------------


class TestGetOutputDir:
    def test_returns_configured_dir_if_exists(self, tmp_path):
        with patch("veeam_ports_mcp.server.OUTPUT_DIR", str(tmp_path)):
            assert _get_output_dir() == str(tmp_path)

    def test_creates_dir_if_missing(self, tmp_path):
        target = str(tmp_path / "subdir")
        with patch("veeam_ports_mcp.server.OUTPUT_DIR", target):
            result = _get_output_dir()
            assert result == target
            assert os.path.isdir(target)

    def test_falls_back_to_temp_on_error(self):
        with patch("veeam_ports_mcp.server.OUTPUT_DIR", "/nonexistent/readonly/path"):
            with patch("os.makedirs", side_effect=OSError("nope")):
                result = _get_output_dir()
                assert result == tempfile.gettempdir()


# ---------------------------------------------------------------------------
# App import response handling
# ---------------------------------------------------------------------------


SAMPLE_APP_IMPORT_RESPONSE = [
    {
        "id": "uuid-1",
        "sourceServer": "VBR",
        "totalMappedPorts": 2,
        "totalMappedInboundPorts": 0,
        "totalMappedServers": 1,
        "mappedPorts": [
            {
                "sourceServerId": "uuid-1",
                "sourceServerName": "VBR",
                "targetServerName": "Proxy",
                "sourceService": "Backup server",
                "targetService": "Backup proxy (Linux)",
                "description": "SSH control channel",
                "product": "VBR v13",
                "port": "22",
                "protocol": "TCP",
            },
            {
                "sourceServerId": "uuid-1",
                "sourceServerName": "VBR",
                "targetServerName": "Proxy",
                "sourceService": "Backup server",
                "targetService": "Backup proxy (Linux)",
                "description": "Veeam Transport Service",
                "product": "VBR v13",
                "port": "6162",
                "protocol": "TCP",
            },
        ],
        "allInboundPortsTcp": [],
        "allOutboundPortsTcp": ["22", "6162"],
        "allInboundPortsUdp": [],
        "allOutboundPortsUdp": [],
        "mappedPortsByProtocol": [
            {"index": 0, "serverName": "Proxy", "service": "", "protocol": "TCP", "port": "22"},
            {"index": 1, "serverName": "Proxy", "service": "", "protocol": "TCP", "port": "6162"},
        ],
        "mappedPortsByProtocolInbound": [],
    },
    {
        "id": "uuid-2",
        "sourceServer": "Proxy",
        "totalMappedPorts": 2,
        "totalMappedInboundPorts": 2,
        "totalMappedServers": 1,
        "mappedPorts": [
            {
                "sourceServerId": "uuid-2",
                "sourceServerName": "Proxy",
                "targetServerName": "VBR",
                "sourceService": "Backup proxy (Linux)",
                "targetService": "Backup server",
                "description": "SSH control channel",
                "product": "VBR v13",
                "port": "22",
                "protocol": "TCP",
            },
            {
                "sourceServerId": "uuid-2",
                "sourceServerName": "Proxy",
                "targetServerName": "VBR",
                "sourceService": "Backup proxy (Linux)",
                "targetService": "Backup server",
                "description": "Veeam Transport Service",
                "product": "VBR v13",
                "port": "6162",
                "protocol": "TCP",
            },
        ],
        "allInboundPortsTcp": ["22", "6162"],
        "allOutboundPortsTcp": [],
        "allInboundPortsUdp": [],
        "allOutboundPortsUdp": [],
        "mappedPortsByProtocol": [],
        "mappedPortsByProtocolInbound": [
            {"index": 0, "serverName": "VBR", "service": "", "protocol": "TCP", "port": "22"},
            {"index": 1, "serverName": "VBR", "service": "", "protocol": "TCP", "port": "6162"},
        ],
    },
]


class TestAppImportResponseStructure:
    """Verify that app-import API response fields are compatible with summary code."""

    def test_servers_have_required_fields(self):
        for srv in SAMPLE_APP_IMPORT_RESPONSE:
            assert "sourceServer" in srv
            assert "mappedPorts" in srv
            assert "totalMappedInboundPorts" in srv
            assert "totalMappedServers" in srv

    def test_mapped_ports_have_required_fields(self):
        for srv in SAMPLE_APP_IMPORT_RESPONSE:
            for mp in srv["mappedPorts"]:
                assert "sourceServerId" in mp
                assert "sourceServerName" in mp
                assert "targetServerName" in mp
                assert "sourceService" in mp
                assert "targetService" in mp
                assert "product" in mp
                assert "port" in mp
                assert "protocol" in mp
                assert "description" in mp
                assert "server" not in mp
                assert "direction" not in mp

    def test_ports_by_protocol_have_required_fields(self):
        for srv in SAMPLE_APP_IMPORT_RESPONSE:
            for entry in srv["mappedPortsByProtocol"] + srv["mappedPortsByProtocolInbound"]:
                assert "index" in entry
                assert "serverName" in entry
                assert "service" in entry
                assert "protocol" in entry
                assert "port" in entry
                assert isinstance(entry["port"], str)
                assert "ports" not in entry

    def test_file_roundtrip(self, tmp_path):
        """Verify app-import servers can be written as JSON and loaded back."""
        filepath = tmp_path / "test-import.json"
        with open(filepath, "w") as f:
            json.dump(SAMPLE_APP_IMPORT_RESPONSE, f, indent=2)

        with open(filepath) as f:
            loaded = json.load(f)

        assert len(loaded) == 2
        assert loaded[0]["sourceServer"] == "VBR"
        assert len(loaded[0]["mappedPorts"]) == 2
        assert all("mappedPorts" in s for s in loaded)
