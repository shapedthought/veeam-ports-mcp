"""Veeam Ports MCP Server.

Exposes Veeam product network port requirements via MCP tools.
Wraps the REST API at magicports.veeambp.com/ports_server/.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from mcp.server.fastmcp import Context, FastMCP

logger = logging.getLogger(__name__)

API_BASE = "https://magicports.veeambp.com/ports_server"
REQUEST_TIMEOUT = 30.0


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
        "with source, target, port, and protocol columns."
    ),
    lifespan=app_lifespan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client(ctx: Context) -> httpx.AsyncClient:
    return ctx.request_context.lifespan_context.client


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
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Run the MCP server (stdio transport)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
