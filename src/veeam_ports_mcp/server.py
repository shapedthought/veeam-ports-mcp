"""Veeam Ports MCP Server.

Exposes Veeam product network port requirements via MCP tools.
Wraps the REST API at magicports.veeambp.com/ports_server/.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import Context, FastMCP

logger = logging.getLogger(__name__)

API_BASE = "https://magicports.veeambp.com/ports_server"
REQUEST_TIMEOUT = 30.0

# Directory for generated import files.
# Falls back to system temp if the preferred path doesn't exist or can't be created.
OUTPUT_DIR = os.environ.get(
    "VEEAM_PORTS_OUTPUT_DIR",
    str(Path.home() / "Documents" / "veeam-ports-exports"),
)


# ---------------------------------------------------------------------------
# Lifespan — shared httpx client
# ---------------------------------------------------------------------------

@dataclass
class AppContext:
    client: httpx.AsyncClient


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage the httpx client lifecycle."""
    async with httpx.AsyncClient(
        base_url=API_BASE,
        timeout=REQUEST_TIMEOUT,
        headers={"Accept": "application/json"},
    ) as client:
        try:
            resp = await client.get("/health")
            resp.raise_for_status()
            logger.info("API health check passed")
        except Exception as exc:
            logger.warning("API health check failed: %s", exc)
        yield AppContext(client=client)


mcp = FastMCP(
    "Veeam Ports",
    instructions=(
        "You have access to Veeam product network port requirement data. "
        "Use these tools to answer questions about firewall rules, "
        "required ports, protocols, and network connectivity for Veeam products.\n\n"
        "Workflow:\n"
        "1. Call list_products first to discover valid product names.\n"
        "2. Product names must match exactly (e.g. 'VBR v13', not 'VBR' or 'Veeam Backup').\n"
        "3. Use search_ports for broad questions across all products "
        "(e.g. 'which products use SMTP').\n"
        "4. Use get_product_ports to get all port data for a specific product.\n"
        "5. Use search_by_port_number to find all products using a given port "
        "(e.g. '443', '9392').\n\n"
        "Tips:\n"
        "- Port entries include source service, target service, port, protocol, "
        "and description fields.\n"
        "- Subheadings represent product components (e.g. 'Backup Server', "
        "'Proxy Server'). Use get_product_subheadings to see the structure.\n"
        "- When asked about firewall rules, present results as a clear table "
        "with source, target, port, and protocol columns.\n"
        "- Use generate_app_import to create a JSON import file for the "
        "Magic Ports frontend app. The tool writes the file to disk and "
        "returns the file path + summary. Present the file to the user "
        "for download. First call get_source_details to see available "
        "services, then ask the user which servers they have."
    ),
    lifespan=app_lifespan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client(ctx: Context) -> httpx.AsyncClient:
    return ctx.request_context.lifespan_context.client


def _get_output_dir() -> str:
    """Get (and create if needed) the output directory for generated files."""
    d = OUTPUT_DIR
    if not os.path.isdir(d):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            d = tempfile.gettempdir()
    return d


async def _api_get(
    client: httpx.AsyncClient, path: str, params: dict | None = None
) -> Any:
    """GET request with standardised error handling."""
    try:
        resp = await client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        raise ValueError(
            "Cannot connect to the Veeam Ports API. "
            "Please check your internet connection."
        )
    except httpx.TimeoutException:
        raise ValueError(
            "Request to the Veeam Ports API timed out. Please try again."
        )
    except httpx.HTTPStatusError as exc:
        raise ValueError(
            f"API error: {exc.response.status_code} {exc.response.reason_phrase}"
        )


async def _api_post(
    client: httpx.AsyncClient, path: str, body: dict
) -> Any:
    """POST request with standardised error handling."""
    try:
        resp = await client.post(path, json=body)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        raise ValueError(
            "Cannot connect to the Veeam Ports API. "
            "Please check your internet connection."
        )
    except httpx.TimeoutException:
        raise ValueError(
            "Request to the Veeam Ports API timed out. Please try again."
        )
    except httpx.HTTPStatusError as exc:
        raise ValueError(
            f"API error: {exc.response.status_code} {exc.response.reason_phrase}"
        )


def _format_port_entry(entry: dict[str, Any]) -> str:
    """Format a single port record as readable text."""
    lines = [
        f"  Source: {entry.get('sourceService', 'N/A')}",
        f"  Target: {entry.get('targetService', 'N/A')}",
        f"  Port: {entry.get('port', 'N/A')} ({entry.get('protocol', 'N/A')})",
    ]
    desc = entry.get("description", "").strip()
    if desc:
        lines.append(f"  Description: {desc}")
    sub2 = entry.get("subheadingL2", "")
    if sub2:
        lines.append(f"  Subsection: {sub2}")
    return "\n".join(lines)


def _format_port_list(entries: list[dict[str, Any]], title: str) -> str:
    """Format a list of port entries grouped by subheading."""
    if not entries:
        return f"{title}\n\nNo results found."

    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        key = entry.get("subheading", "General") or "General"
        grouped.setdefault(key, []).append(entry)

    parts = [f"{title} ({len(entries)} entries)\n"]
    for section, items in grouped.items():
        parts.append(f"### {section}")
        for i, item in enumerate(items, 1):
            parts.append(f"\n{i}.")
            parts.append(_format_port_entry(item))
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_products(ctx: Context) -> str:
    """List all Veeam products that have port requirement data available.

    Call this first to discover valid product names before using
    other tools. Returns product names like 'VBR v13', 'VB365', etc.
    """
    client = _get_client(ctx)
    products = await _api_get(client, "/")
    product_list = "\n".join(f"- {p}" for p in products)
    return f"Available Veeam products ({len(products)}):\n\n{product_list}"


@mcp.tool()
async def get_product_ports(product_name: str, ctx: Context) -> str:
    """Get all network port requirements for a specific Veeam product.

    Returns every port entry including source service, target service,
    port number, protocol, and description. Use list_products first
    to find valid product names.

    Args:
        product_name: Exact product name (e.g. 'VBR v13', 'VB365', 'VONE')
    """
    client = _get_client(ctx)
    entries = await _api_get(client, f"/products/{product_name}/ports")
    return _format_port_list(entries, f"Port requirements for {product_name}")


@mcp.tool()
async def get_product_subheadings(product_name: str, ctx: Context) -> str:
    """Get the section headings that organise a product's port requirements.

    Each subheading represents a component or role within the product
    (e.g. 'Backup Server', 'Proxy Server'). Useful for understanding
    the product architecture before diving into specific ports.

    Args:
        product_name: Exact product name (e.g. 'VBR v13', 'VB365')
    """
    client = _get_client(ctx)
    subheadings = await _api_get(client, f"/products/{product_name}/subheadings")
    if not subheadings:
        return f"No subheadings found for product '{product_name}'."
    listing = "\n".join(f"- {s}" for s in subheadings)
    return f"Sections for {product_name} ({len(subheadings)}):\n\n{listing}"


@mcp.tool()
async def search_ports(query: str, ctx: Context) -> str:
    """Search across all Veeam products for port requirements matching a query.

    Searches product names, source/target services, port numbers,
    protocols, descriptions, and section headings. Useful for questions
    like 'which products use SMTP' or 'what needs port 443'.

    Args:
        query: Search text (e.g. 'SMTP', 'backup server', 'cloud gateway')
    """
    client = _get_client(ctx)
    entries = await _api_get(client, "/search", params={"q": query})
    return _format_port_list(entries, f"Search results for '{query}'")


@mcp.tool()
async def search_by_port_number(port: str, ctx: Context) -> str:
    """Find all Veeam product entries that use a specific port number.

    Searches the port field across all products. Useful for firewall
    audits or checking which Veeam services need a particular port opened.

    Args:
        port: Port number to search for (e.g. '443', '9392', '6180')
    """
    client = _get_client(ctx)
    entries = await _api_get(client, f"/search/port/{port}")
    return _format_port_list(entries, f"Entries using port {port}")


@mcp.tool()
async def get_source_details(product_name: str, ctx: Context) -> str:
    """Get the source services for a product, grouped by section.

    Shows which components/roles (source services) exist within each
    section of a product's port requirements. Useful for understanding
    the network topology before querying specific port details.

    Args:
        product_name: Exact product name (e.g. 'VBR v13', 'VB365')
    """
    client = _get_client(ctx)
    entries = await _api_post(
        client, "/sourceDetails", {"productName": product_name}
    )
    if not entries:
        return f"No source details found for product '{product_name}'."

    grouped: dict[str, list[str]] = {}
    for entry in entries:
        section = entry.get("subheading", "General") or "General"
        source = entry.get("sourceService", "Unknown")
        grouped.setdefault(section, []).append(source)

    parts = [f"Source services for {product_name}:\n"]
    for section, sources in grouped.items():
        parts.append(f"### {section}")
        for s in sources:
            parts.append(f"  - {s}")
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# App import generator
# ---------------------------------------------------------------------------

def _normalise_service(name: str) -> str:
    """Strip OS qualifiers for fuzzy matching."""
    lower = name.lower().strip()
    for suffix in ("(microsoft windows)", "(linux)", "(linux/unix)"):
        lower = lower.replace(suffix, "").strip()
    return lower


def _has_conflicting_os(entry_service: str, server_service: str) -> bool:
    """Check if a port entry's service specifies an OS that conflicts
    with the user's server service.

    Returns True if the entry is explicitly for a DIFFERENT OS than what
    the server provides. Generic entries (no OS qualifier) never conflict.
    """
    entry_lower = entry_service.lower()
    server_lower = server_service.lower()

    os_tags = {
        "(microsoft windows)": "windows",
        "(linux)": "linux",
        "(linux/unix)": "linux",
    }

    entry_os = None
    server_os = None

    for tag, os_name in os_tags.items():
        if tag in entry_lower:
            entry_os = os_name
        if tag in server_lower:
            server_os = os_name

    # Only conflict if BOTH have an OS and they differ
    if entry_os and server_os and entry_os != server_os:
        return True

    return False


def _find_server(
    service_name: str,
    server_map: dict[str, dict],
) -> str | None:
    """Find which user-defined server a port entry's service belongs to.

    Matching priority:
    1. Exact match (case-insensitive)
    2. Normalised match (strip OS qualifiers), with OS conflict rejection
    3. Bidirectional substring match, with OS conflict rejection
    """
    svc_lower = service_name.lower().strip()
    svc_norm = _normalise_service(service_name)

    # Pass 1: exact match (case-insensitive)
    for srv_name, srv in server_map.items():
        for svc in srv["services"]:
            if svc.lower().strip() == svc_lower:
                return srv_name

    # Pass 2: normalised match (e.g. "Backup proxy" matches "Backup proxy (Linux)")
    for srv_name, srv in server_map.items():
        for svc in srv["services"]:
            if _normalise_service(svc) == svc_norm:
                if not _has_conflicting_os(service_name, svc):
                    return srv_name

    # Pass 3: bidirectional substring on normalised names (with OS conflict check)
    for srv_name, srv in server_map.items():
        for svc in srv["services"]:
            srv_norm = _normalise_service(svc)
            if srv_norm in svc_norm or svc_norm in srv_norm:
                if not _has_conflicting_os(service_name, svc):
                    return srv_name

    return None


def _build_app_import(
    port_entries: list[dict[str, Any]],
    servers: list[dict[str, Any]],
    product: str,
) -> list[dict[str, Any]]:
    """Build the frontend app import JSON structure."""
    # Create server records with UUIDs
    server_map: dict[str, dict] = {}
    for srv in servers:
        srv_id = str(uuid.uuid4())
        server_map[srv["name"]] = {
            "id": srv_id,
            "services": srv["services"],
            "mappedPorts": [],
        }

    # Match each port entry to source and target servers
    for entry in port_entries:
        src_service = entry.get("sourceService", "")
        tgt_service = entry.get("targetService", "")
        src_server = _find_server(src_service, server_map)
        tgt_server = _find_server(tgt_service, server_map)

        if not src_server:
            continue

        src_id = server_map[src_server]["id"]
        tgt_name = tgt_server if tgt_server else tgt_service

        server_map[src_server]["mappedPorts"].append({
            "sourceServerId": src_id,
            "sourceServerName": src_server,
            "targetServerName": tgt_name,
            "sourceService": src_service,
            "targetService": tgt_service,
            "description": entry.get("description", ""),
            "product": product,
            "port": entry.get("port", ""),
            "protocol": entry.get("protocol", ""),
        })

    # Build inbound map: for each server, find all ports targeting it
    inbound_map: dict[str, list[dict]] = {name: [] for name in server_map}
    for srv_name, srv in server_map.items():
        for mp in srv["mappedPorts"]:
            tgt = mp["targetServerName"]
            if tgt in inbound_map:
                inbound_map[tgt].append(mp)

    # Build the output structure
    result = []
    for srv_name, srv in server_map.items():
        mapped = srv["mappedPorts"]

        # Outbound ports by protocol
        out_tcp = []
        out_udp = []
        for mp in mapped:
            port = mp["port"]
            proto = mp.get("protocol", "").upper()
            if "TCP" in proto and port not in out_tcp:
                out_tcp.append(port)
            if "UDP" in proto and port not in out_udp:
                out_udp.append(port)

        # Inbound ports by protocol
        inbound = inbound_map[srv_name]
        in_tcp = []
        in_udp = []
        for mp in inbound:
            port = mp["port"]
            proto = mp.get("protocol", "").upper()
            if "TCP" in proto and port not in in_tcp:
                in_tcp.append(port)
            if "UDP" in proto and port not in in_udp:
                in_udp.append(port)

        # Group outbound by target server + protocol
        outbound_grouped: dict[str, dict[str, list[str]]] = {}
        for mp in mapped:
            tgt = mp["targetServerName"]
            proto = mp.get("protocol", "").upper()
            outbound_grouped.setdefault(tgt, {}).setdefault(proto, [])
            if mp["port"] not in outbound_grouped[tgt][proto]:
                outbound_grouped[tgt][proto].append(mp["port"])

        mapped_by_proto = []
        idx = 0
        for tgt, protocols in outbound_grouped.items():
            for proto, ports in protocols.items():
                mapped_by_proto.append({
                    "index": idx,
                    "serverName": tgt,
                    "service": "",
                    "protocol": proto,
                    "port": ", ".join(ports),
                })
                idx += 1

        # Group inbound by source server + protocol
        inbound_grouped: dict[str, dict[str, list[str]]] = {}
        for mp in inbound:
            src = mp["sourceServerName"]
            proto = mp.get("protocol", "").upper()
            inbound_grouped.setdefault(src, {}).setdefault(proto, [])
            if mp["port"] not in inbound_grouped[src][proto]:
                inbound_grouped[src][proto].append(mp["port"])

        mapped_by_proto_in = []
        idx = 0
        for src, protocols in inbound_grouped.items():
            for proto, ports in protocols.items():
                mapped_by_proto_in.append({
                    "index": idx,
                    "serverName": src,
                    "service": "",
                    "protocol": proto,
                    "port": ", ".join(ports),
                })
                idx += 1

        # Count unique target servers
        unique_targets = set(mp["targetServerName"] for mp in mapped)

        result.append({
            "id": srv["id"],
            "sourceServer": srv_name,
            "totalMappedPorts": len(mapped),
            "totalMappedInboundPorts": len(inbound),
            "totalMappedServers": len(unique_targets),
            "mappedPorts": mapped,
            "allInboundPortsTcp": in_tcp,
            "allInboundPortsUdp": in_udp,
            "allOutboundPortsTcp": out_tcp,
            "allOutboundPortsUdp": out_udp,
            "mappedPortsByProtocol": mapped_by_proto,
            "mappedPortsByProtocolInbound": mapped_by_proto_in,
        })

    return result


@mcp.tool()
async def generate_app_import(
    product_name: str,
    servers_json: str,
    ctx: Context,
    output_dir: str | None = None,
) -> str:
    """Generate a JSON file for importing into the Magic Ports frontend app.

    Creates the port mapping topology structure that the Angular frontend
    can import. You must define the servers in your environment and which
    services each server provides.

    The full JSON is written to a file on disk. The tool returns the file
    path and a summary of the generated data. Present the file path to the
    user so they can import it into the Magic Ports app.

    Workflow:
    1. Call get_source_details to see available services for the product.
    2. Ask the user which servers they have and what roles they serve.
    3. Call this tool with the server definitions.
    4. Present the generated file to the user for download/import.

    Args:
        product_name: Exact product name (e.g. 'VBR v13', 'VB365')
        servers_json: JSON array of server definitions. Each object must
            have 'name' (server label) and 'services' (list of service
            names this server provides). Example:
            [
              {"name": "VBR", "services": ["Backup server"]},
              {"name": "Proxy", "services": ["Backup proxy"]},
              {"name": "Repo", "services": ["Backup repository"]},
              {"name": "ESXi", "services": ["ESXi server", "vCenter Server"]}
            ]
        output_dir: Optional directory to write the file to. Defaults to
            ~/Documents/veeam-ports-exports or VEEAM_PORTS_OUTPUT_DIR env var.
    """
    client = _get_client(ctx)

    try:
        servers = json.loads(servers_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid servers_json: {exc}")

    if not isinstance(servers, list):
        raise ValueError("servers_json must be a JSON array.")
    for srv in servers:
        if "name" not in srv or "services" not in srv:
            raise ValueError(
                "Each server must have 'name' and 'services' fields."
            )

    entries = await _api_get(client, f"/products/{product_name}/ports")
    if not entries:
        return f"No port data found for product '{product_name}'."

    result = _build_app_import(entries, servers, product_name)

    # Write full JSON to file, return compact summary
    if output_dir:
        dest = output_dir
        os.makedirs(dest, exist_ok=True)
    else:
        dest = _get_output_dir()

    safe_product = product_name.replace(" ", "-").lower()
    filename = f"magic-ports-{safe_product}-import.json"
    filepath = os.path.join(dest, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    file_size = os.path.getsize(filepath)

    # Build compact summary for the LLM
    summary_lines = [
        "Import file generated successfully.",
        "",
        f"File: {filepath}",
        f"Size: {file_size:,} bytes",
        f"Product: {product_name}",
        f"Servers: {len(result)}",
        "",
    ]

    for srv in result:
        mapped_count = len(srv.get("mappedPorts", []))
        inbound_count = srv.get("totalMappedInboundPorts", 0)
        target_count = srv.get("totalMappedServers", 0)
        summary_lines.append(
            f"  {srv['sourceServer']}: "
            f"{mapped_count} outbound ports, "
            f"{inbound_count} inbound ports, "
            f"{target_count} target servers"
        )

    summary_lines.append("")
    summary_lines.append(
        "Present this file to the user for download. "
        "They can import it into the Magic Ports app."
    )

    return "\n".join(summary_lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Run the MCP server (stdio transport)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
