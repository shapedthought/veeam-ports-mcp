"""Tests for semantic_search tool formatting."""

import pytest

from veeam_ports_mcp.server import _format_port_entry


class TestFormatPortEntry:
    """Verify _format_port_entry produces expected text."""

    def test_basic_entry(self):
        entry = {
            "sourceService": "Backup Server",
            "targetService": "ESXi Host",
            "port": "443",
            "protocol": "TCP",
            "description": "VMware API",
        }
        text = _format_port_entry(entry)
        assert "Source: Backup Server" in text
        assert "Target: ESXi Host" in text
        assert "443 (TCP)" in text
        assert "Description: VMware API" in text

    def test_missing_fields_show_na(self):
        text = _format_port_entry({})
        assert "N/A" in text

    def test_subsection_shown_when_present(self):
        entry = {
            "sourceService": "Proxy",
            "targetService": "Host",
            "port": "902",
            "protocol": "TCP",
            "description": "",
            "subheadingL2": "VMware Backup Proxy",
        }
        text = _format_port_entry(entry)
        assert "Subsection: VMware Backup Proxy" in text

    def test_empty_description_omitted(self):
        entry = {
            "sourceService": "A",
            "targetService": "B",
            "port": "80",
            "protocol": "TCP",
            "description": "",
        }
        text = _format_port_entry(entry)
        assert "Description" not in text
