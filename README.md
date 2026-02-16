# Veeam Ports MCP Server

An MCP (Model Context Protocol) server that provides access to Veeam product network port requirements. Query ports, protocols, and firewall rules for all Veeam products directly from Claude Desktop, VS Code, or any MCP-compatible client.

## What It Does

This server wraps the [Veeam Magic Ports](https://magicports.veeambp.com) API, giving LLMs structured access to network port data for 25+ Veeam products including VBR, VB365, VONE, VCC, and all Veeam Explorers.

### Available Tools

| Tool | Description |
|------|-------------|
| `list_products` | List all Veeam products with port data |
| `get_product_ports` | Get all port requirements for a product |
| `get_product_subheadings` | Get section headings for a product |
| `search_ports` | Free-text search across all products |
| `search_by_port_number` | Find entries using a specific port |
| `get_source_details` | Source services grouped by section |

## Installation

### Claude Desktop

Add to your Claude Desktop config file:

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

For Claude Desktop with a local dev install:

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

## Example Prompts

- "What ports does VBR v13 need?"
- "Which Veeam products use port 443?"
- "Show me the firewall rules for VB365"
- "What SMTP ports are used across Veeam products?"
- "List the network requirements for the Veeam backup server component"

## Debugging

Use the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector uv run veeam-ports-mcp
```

## License

MIT
