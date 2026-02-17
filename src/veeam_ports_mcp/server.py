"""Veeam Ports MCP Server.

Exposes Veeam product network port requirements via MCP tools.
Wraps the REST API at magicports.veeambp.com/ports_server/.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import Context, FastMCP

logger = logging.getLogger(__name__)

API_BASE = os.environ.get(
    "VEEAM_PORTS_API_BASE", "https://magicports.veeambp.com/ports_server"
)
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
        "3. Use semantic_search for natural language questions — it handles "
        "synonyms and related concepts (e.g. 'firewall rules for backup to NAS').\n"
        "4. Use get_product_ports or get_enriched_ports for exhaustive port data.\n"
        "5. Use search_ports for broad keyword searches across all products.\n"
        "6. Use search_by_port_number to find all products using a given port.\n\n"
        "Server topology:\n"
        "- Use list_services to discover valid service role names for a product "
        "before building server definitions.\n"
        "- Use generate_topology when the user describes their server layout "
        "and wants to know what firewall rules are needed between servers.\n"
        "- Use generate_app_import to create a JSON import file for the "
        "Magic Ports frontend app. The tool writes the file to disk and "
        "returns the file path + summary. Present the file to the user "
        "for download.\n"
        "- Both topology tools support exclude_subsections and exclude_ports "
        "to filter out irrelevant sections (e.g. CDP) or specific ports.\n"
        "- Both tools support format='csv' or format='markdown' for "
        "alternative output formats.\n"
        "- If a service name is not recognized, the API returns warnings "
        "with fuzzy match suggestions — present these to the user.\n\n"
        "Tips:\n"
        "- Port entries include source service, target service, port, protocol, "
        "and description fields.\n"
        "- Subheadings represent product components (e.g. 'Backup Server', "
        "'Proxy Server'). Use get_product_subheadings to see the structure.\n"
        "- When asked about firewall rules, present results as a clear table "
        "with source, target, port, and protocol columns."
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
# Enriched / semantic tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def semantic_search(
    query: str,
    ctx: Context,
    product_name: str | None = None,
    limit: int = 20,
) -> str:
    """Search port requirements using natural language (vector similarity).

    Understands synonyms and related concepts — e.g. 'firewall rules for
    backup to NAS' matches NFS/SMB repository entries even if those exact
    words don't appear in the data.

    Falls back to keyword search if vector embeddings are unavailable.

    Args:
        query: Natural language search query (e.g. 'what ports does the
            proxy need for VMware', 'cloud connectivity', 'database ports')
        product_name: Optional product to filter results (e.g. 'VBR v13').
            If omitted, searches across all products.
        limit: Max results to return (1-100, default 20)
    """
    client = _get_client(ctx)
    limit = max(1, min(100, limit))

    body: dict[str, Any] = {"query": query, "limit": limit}
    if product_name:
        body["product"] = product_name

    data = await _api_post(client, "/semantic-search", body)

    results = data.get("results", [])
    fallback = data.get("fallback", False)

    if not results:
        return f"No results for '{query}'."

    header = f"Semantic search: '{query}'"
    if product_name:
        header += f" (product: {product_name})"
    if fallback:
        header += " [keyword fallback]"
    header += f" — {len(results)} results\n"

    parts = [header]
    for i, entry in enumerate(results, 1):
        score = entry.get("similarity", 0)
        parts.append(f"{i}. (score: {score:.2f})")
        parts.append(_format_port_entry(entry))

        # Show enriched metadata roles if present
        for side in ("source_meta", "target_meta"):
            meta = entry.get(side)
            if meta and meta.get("roles"):
                label = "Source" if side == "source_meta" else "Target"
                roles = ", ".join(meta["roles"])
                parts.append(f"  {label} roles: {roles}")
        parts.append("")

    return "\n".join(parts)


@mcp.tool()
async def get_enriched_ports(product_name: str, ctx: Context) -> str:
    """Get port data with LLM-parsed service metadata for a product.

    Returns the same port entries as get_product_ports, plus enriched
    metadata for each source and target service (canonical name, roles,
    OS, hypervisor, storage type). Useful for understanding service
    relationships and filtering by role.

    Returns 404 if enrichment hasn't been run for this product.

    Args:
        product_name: Exact product name (e.g. 'VBR v13', 'VB365')
    """
    client = _get_client(ctx)

    try:
        entries = await _api_get(
            client, f"/products/{product_name}/enriched-ports"
        )
    except ValueError as exc:
        if "404" in str(exc):
            return (
                f"No enriched data available for '{product_name}'. "
                "Enrichment may not have been run for this product."
            )
        raise

    if not entries:
        return f"No enriched port data found for '{product_name}'."

    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        key = entry.get("subheading", "General") or "General"
        grouped.setdefault(key, []).append(entry)

    parts = [
        f"Enriched port data for {product_name} ({len(entries)} entries)\n"
    ]
    for section, items in grouped.items():
        parts.append(f"### {section}")
        for i, item in enumerate(items, 1):
            parts.append(f"\n{i}.")
            parts.append(_format_port_entry(item))
            for side, label in (
                ("source_meta", "Source"),
                ("target_meta", "Target"),
            ):
                meta = item.get(side)
                if not meta:
                    continue
                details = []
                if meta.get("roles"):
                    details.append(f"roles={','.join(meta['roles'])}")
                if meta.get("os"):
                    details.append(f"os={meta['os']}")
                if meta.get("hypervisor"):
                    details.append(f"hv={meta['hypervisor']}")
                if meta.get("storage_type"):
                    details.append(f"storage={meta['storage_type']}")
                if details:
                    parts.append(f"  {label} meta: {' '.join(details)}")
        parts.append("")

    return "\n".join(parts)


@mcp.tool()
async def generate_topology(
    product_name: str,
    servers_json: str,
    ctx: Context,
    include_loopback: bool = False,
    exclude_subsections: str | None = None,
    exclude_ports: str | None = None,
    format: str = "json",
) -> str:
    """Resolve server topology — given named servers and their services,
    returns all port mappings between them as human-readable text.

    Use this when the user describes their server layout and wants to
    know what firewall rules are needed between servers.

    Args:
        product_name: Exact product name (e.g. 'VBR v13', 'VB365')
        servers_json: JSON array of server definitions. Each object must
            have 'name' (server label) and 'services' (list of service
            names this server provides). Example:
            [
              {"name": "VBR", "services": ["Backup server"]},
              {"name": "Proxy", "services": ["Backup proxy"]},
              {"name": "ESXi", "services": ["ESXi host"]}
            ]
        include_loopback: Include ports where source and target are the
            same server (default: false)
        exclude_subsections: Optional JSON array of subsection names to
            exclude from the results (e.g. '["CDP Components"]')
        exclude_ports: Optional JSON array of port numbers to exclude
            from the results (e.g. '["33035"]')
        format: Output format — 'json' (default), 'csv', or 'markdown'.
            csv and markdown return the raw content as text.
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

    options: dict[str, Any] = {
        "include_loopback": include_loopback,
        "include_unresolved": True,
    }
    if exclude_subsections:
        try:
            options["exclude_subsections"] = json.loads(exclude_subsections)
        except json.JSONDecodeError:
            raise ValueError("exclude_subsections must be a valid JSON array.")
    if exclude_ports:
        try:
            options["exclude_ports"] = json.loads(exclude_ports)
        except json.JSONDecodeError:
            raise ValueError("exclude_ports must be a valid JSON array.")

    body = {"servers": servers, "options": options}

    # For csv/markdown, fetch raw text directly
    if format in ("csv", "markdown"):
        try:
            resp = await client.post(
                f"/products/{product_name}/topology",
                json=body,
                params={"format": format},
            )
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            raise ValueError(f"API error fetching {format} format: {exc}")

    topology = await _api_post(
        client,
        f"/products/{product_name}/topology",
        body,
    )

    result = topology.get("servers", [])
    metadata = topology.get("metadata", {})

    if not result:
        unresolved = metadata.get("unresolved_services", [])
        if unresolved:
            return (
                f"No port mappings resolved for '{product_name}'. "
                f"Unresolved services: {', '.join(unresolved)}"
            )
        return f"No port mappings resolved for product '{product_name}'."

    matched = metadata.get("total_entries_matched", 0)
    skipped = metadata.get("total_entries_skipped", 0)
    unresolved = metadata.get("unresolved_services", [])
    warnings = metadata.get("warnings", [])

    parts = [
        f"Topology for {product_name} "
        f"({matched} entries matched, {skipped} skipped)\n"
    ]

    if unresolved:
        parts.append(f"Unresolved services: {', '.join(unresolved)}\n")

    if warnings:
        parts.append("Warnings:")
        for w in warnings:
            msg = f"  - '{w['service']}' on server '{w['server']}' could not be resolved"
            suggestions = w.get("suggestions", [])
            if suggestions:
                msg += f". Did you mean: {', '.join(suggestions)}?"
            parts.append(msg)
        parts.append("")

    for srv in result:
        name = srv["sourceServer"]
        mapped = srv.get("mappedPorts", [])
        inbound_count = srv.get("totalMappedInboundPorts", 0)
        target_count = srv.get("totalMappedServers", 0)

        parts.append(
            f"## {name} "
            f"({len(mapped)} outbound, {inbound_count} inbound, "
            f"{target_count} targets)"
        )

        # Outbound rules grouped by target
        by_proto = srv.get("mappedPortsByProtocol", [])
        if by_proto:
            parts.append("  Outbound:")
            for group in by_proto:
                ports = ", ".join(group["ports"])
                parts.append(
                    f"    → {group['server']} "
                    f"{group['protocol']}: {ports}"
                )

        # Inbound rules grouped by source
        by_proto_in = srv.get("mappedPortsByProtocolInbound", [])
        if by_proto_in:
            parts.append("  Inbound:")
            for group in by_proto_in:
                ports = ", ".join(group["ports"])
                parts.append(
                    f"    ← {group['server']} "
                    f"{group['protocol']}: {ports}"
                )

        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Service discovery
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_services(product_name: str, ctx: Context) -> str:
    """List all known service roles for a product from the knowledge graph.

    Returns canonical service names with their original name variants
    and any OS/hypervisor/storage qualifiers. Useful for discovering
    valid service names before calling generate_topology or
    generate_app_import.

    Args:
        product_name: Exact product name (e.g. 'VBR v13', 'VB365')
    """
    client = _get_client(ctx)

    try:
        services = await _api_get(
            client, f"/products/{product_name}/services"
        )
    except ValueError as exc:
        if "404" in str(exc):
            return (
                f"No services found for '{product_name}'. "
                "The knowledge graph may not have been built for this product."
            )
        raise

    if not services:
        return f"No services found for product '{product_name}'."

    parts = [
        f"Services for {product_name} ({len(services)} canonical roles):\n"
    ]
    for svc in services:
        canonical = svc.get("canonical", "Unknown")
        originals = svc.get("original_names", [])
        os_list = svc.get("os", [])
        hv_list = svc.get("hypervisor", [])
        storage_list = svc.get("storage_type", [])

        parts.append(f"- **{canonical}**")
        if originals and originals != [canonical]:
            parts.append(f"    Names: {', '.join(originals)}")
        qualifiers = []
        if os_list:
            qualifiers.append(f"OS: {', '.join(os_list)}")
        if hv_list:
            qualifiers.append(f"Hypervisor: {', '.join(hv_list)}")
        if storage_list:
            qualifiers.append(f"Storage: {', '.join(storage_list)}")
        if qualifiers:
            parts.append(f"    {' | '.join(qualifiers)}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# App import / topology tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def generate_app_import(
    product_name: str,
    servers_json: str,
    ctx: Context,
    output_dir: str | None = None,
    exclude_subsections: str | None = None,
    exclude_ports: str | None = None,
    format: str = "json",
) -> str:
    """Generate a JSON file for importing into the Magic Ports frontend app.

    Resolves the port mapping topology between user-defined servers using
    the enriched knowledge graph on the API server. The full JSON is
    written to a file on disk and a compact summary is returned.

    Workflow:
    1. Call list_services to see available service roles for the product.
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
        exclude_subsections: Optional JSON array of subsection names to
            exclude from the results (e.g. '["CDP Components"]')
        exclude_ports: Optional JSON array of port numbers to exclude
            from the results (e.g. '["33035"]')
        format: Output format — 'json' (default), 'csv', or 'markdown'.
            csv and markdown return the raw content as text (no file written).
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

    options: dict[str, Any] = {
        "include_loopback": False,
        "include_unresolved": False,
    }
    if exclude_subsections:
        try:
            options["exclude_subsections"] = json.loads(exclude_subsections)
        except json.JSONDecodeError:
            raise ValueError("exclude_subsections must be a valid JSON array.")
    if exclude_ports:
        try:
            options["exclude_ports"] = json.loads(exclude_ports)
        except json.JSONDecodeError:
            raise ValueError("exclude_ports must be a valid JSON array.")

    body = {"servers": servers, "options": options}

    # For csv/markdown, fetch raw text directly
    if format in ("csv", "markdown"):
        try:
            resp = await client.post(
                f"/products/{product_name}/app-import",
                json=body,
                params={"format": format},
            )
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            raise ValueError(f"API error fetching {format} format: {exc}")

    result = await _api_post(
        client,
        f"/products/{product_name}/app-import",
        body,
    )

    if not result:
        return f"No port mappings resolved for product '{product_name}'."

    # Response is now an object with 'servers' and 'warnings'
    server_list = result.get("servers", [])
    warnings = result.get("warnings", [])

    if not server_list:
        return f"No port mappings resolved for product '{product_name}'."

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
        f"Servers: {len(server_list)}",
        "",
    ]

    for srv in server_list:
        mapped_count = len(srv.get("mappedPorts", []))
        inbound_count = srv.get("totalMappedInboundPorts", 0)
        target_count = srv.get("totalMappedServers", 0)
        summary_lines.append(
            f"  {srv['sourceServer']}: "
            f"{mapped_count} mapped ports, "
            f"{inbound_count} inbound, "
            f"{target_count} target servers"
        )

    if warnings:
        summary_lines.append("")
        summary_lines.append("Warnings:")
        for w in warnings:
            msg = f"  - '{w['service']}' on server '{w['server']}' could not be resolved"
            suggestions = w.get("suggestions", [])
            if suggestions:
                msg += f". Did you mean: {', '.join(suggestions)}?"
            summary_lines.append(msg)

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
