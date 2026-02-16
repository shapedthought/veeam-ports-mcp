"""Tests for generate_app_import file output and _get_output_dir."""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from veeam_ports_mcp.server import _build_app_import, _get_output_dir


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
# _build_app_import structure
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_port_entries():
    return [
        {
            "sourceService": "Backup server",
            "targetService": "Backup proxy (Linux)",
            "port": "22",
            "protocol": "TCP",
            "description": "SSH control channel",
            "subheading": "Backup Server",
        },
        {
            "sourceService": "Backup server",
            "targetService": "Backup proxy (Linux)",
            "port": "6162, 2500 to 3300",
            "protocol": "TCP",
            "description": "Veeam Transport Service",
            "subheading": "Backup Server",
        },
    ]


@pytest.fixture()
def sample_servers():
    return [
        {"name": "VBR", "services": ["Backup server"]},
        {"name": "Proxy", "services": ["Backup proxy (Linux)"]},
    ]


class TestBuildAppImport:
    def test_returns_list_of_server_records(self, sample_port_entries, sample_servers):
        result = _build_app_import(sample_port_entries, sample_servers, "VBR v13")
        assert isinstance(result, list)
        assert len(result) == 2
        for srv in result:
            assert "id" in srv
            assert "sourceServer" in srv
            assert "mappedPorts" in srv
            assert isinstance(srv["mappedPorts"], list)

    def test_output_is_valid_json(self, sample_port_entries, sample_servers, tmp_path):
        result = _build_app_import(sample_port_entries, sample_servers, "VBR v13")
        filepath = tmp_path / "test-import.json"
        with open(filepath, "w") as f:
            json.dump(result, f, indent=2)

        with open(filepath) as f:
            loaded = json.load(f)

        assert len(loaded) == 2
        assert loaded[0]["sourceServer"] in ("VBR", "Proxy")
        assert all("mappedPorts" in s for s in loaded)

    def test_vbr_has_outbound_ports(self, sample_port_entries, sample_servers):
        result = _build_app_import(sample_port_entries, sample_servers, "VBR v13")
        vbr = next(s for s in result if s["sourceServer"] == "VBR")
        assert len(vbr["mappedPorts"]) > 0
        assert vbr["totalMappedPorts"] > 0
