# Veeam Ports MCP Server

An MCP (Model Context Protocol) server that gives Claude structured access to Veeam product network port requirements. Query ports, generate topology diagrams, and produce firewall rule import files — all from natural language.

Backed by the [Magic Ports](https://magicports.veeambp.com) API, covering 25+ Veeam products.

## Installation

### Claude Desktop

Add to your Claude Desktop config:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "veeam-ports": {
      "command": "uvx",
      "args": ["veeam-ports-mcp"]
    }
  }
}
```

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) — a single binary install. `uvx` downloads and runs the package automatically with no repo clone needed.

### VS Code / Claude Code

```bash
claude mcp add veeam-ports -- uvx veeam-ports-mcp
```

### Development Install

```bash
git clone https://github.com/shapedthought/veeam-ports-mcp.git
cd veeam-ports-mcp
uv sync
```

Claude Desktop config for a local dev install:

```json
{
  "mcpServers": {
    "veeam-ports": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/veeam-ports-mcp",
        "veeam-ports-mcp"
      ]
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `list_products` | List all Veeam products with port data |
| `list_services` | List available service roles for a product — call this before `generate_topology` or `generate_app_import` |
| `get_product_ports` | Get all port requirements for a product |
| `get_product_subheadings` | Get section headings for a product — use to find valid `exclude_subsections` values |
| `search_ports` | Free-text keyword search across all products |
| `search_by_port_number` | Find which products and services use a specific port |
| `get_source_details` | Source services with their section groupings |
| `get_enriched_ports` | Port data with LLM-parsed service metadata |
| `generate_topology` | Resolve firewall rules between named servers in your environment |
| `generate_app_import` | Generate a JSON import file for the Magic Ports frontend app |

## Topology & Import File Workflow

1. Call `list_services` to see available service roles for the product
2. Ask the user which servers they have and what roles each one serves
3. Call `generate_topology` or `generate_app_import` with the server definitions
4. Optionally exclude subsections (e.g. `CDP Components`) or specific ports with `exclude_subsections` / `exclude_ports`

```
User: "Generate firewall rules for my VBR v13 environment.
       I have a VBR server, two Linux proxies, a repo, and ESXi hosts behind vCenter."

Claude: [calls list_services → generate_app_import]
        "Import file saved: ~/Documents/veeam-ports-exports/magic-ports-vbr-v13-import.json"
```

Generated files are saved to `~/Documents/veeam-ports-exports/` by default.

## Example Prompts

- "What ports does VBR v13 need?"
- "Which products use port 902 and why?"
- "Show me all ports the backup server uses to talk to ESXi hosts"
- "Generate firewall rules for my VBR environment — I have a VBR server, a Linux proxy, a repo server, and ESXi hosts managed by vCenter"
- "Create a Magic Ports import file for my VB365 deployment, excluding the proxy ports"
- "What ports does the Veeam ONE server need open?"

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `VEEAM_PORTS_API_BASE` | `https://magicports.veeambp.com/ports_server` | API base URL |
| `VEEAM_PORTS_OUTPUT_DIR` | `~/Documents/veeam-ports-exports` | Directory for generated import files |

## Debugging

Use the MCP Inspector to test tools interactively:

```bash
npx @modelcontextprotocol/inspector uvx veeam-ports-mcp
```

## License

MIT
