
# Gemini MCP Tool

<div align="center">

[![GitHub Release](https://img.shields.io/github/v/release/jamubc/gemini-mcp-tool?logo=github&label=GitHub)](https://github.com/jamubc/gemini-mcp-tool/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Open Source](https://img.shields.io/badge/Source-❤️-red.svg)](https://github.com/jamubc/gemini-mcp-tool)

</div>

> 📚 **Python-only MCP server** for Gemini CLI (uv-based). Supports changeMode chunking, brainstorming, diagnostics.

This is a Model Context Protocol (MCP) server that allows AI assistants to interact with the [Gemini CLI](https://github.com/google-gemini/gemini-cli) using a Python + uv runtime. It leverages Gemini's large context window, supports changeMode chunking, brainstorming, and a diagnostics tool to auto-discover the CLI binary.

<a href="https://glama.ai/mcp/servers/@jamubc/gemini-mcp-tool">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@jamubc/gemini-mcp-tool/badge" alt="Gemini Tool MCP server" />
</a>

## TLDR: [![Claude](https://img.shields.io/badge/Claude-D97757?logo=claude&logoColor=fff)](#) + [![Google Gemini](https://img.shields.io/badge/Google%20Gemini-886FBF?logo=googlegemini&logoColor=fff)](#) (Python/uv)


**Goal**: Use Gemini's powerful analysis capabilities directly in Claude Code to save tokens and analyze large files.

## Prerequisites

Before using this tool, ensure you have:

1. **Python 3.11+** with **[uv](https://github.com/astral-sh/uv)**
2. **[Google Gemini CLI](https://github.com/google-gemini/gemini-cli)** installed and configured (the server auto-discovers it via PATH, roaming/npm, `npm bin -g`, node_modules/.bin, and `npx` fallback; no hard-coded paths needed).


### Setup (Python + uv)

```bash
uv venv
uv pip install 'mcp[cli]>=1.22.0'
```
Then register the MCP server with (Windows example, adjust paths as needed):
```json
{
  "mcpServers": {
    "gemini-cli-py": {
      "transport": "stdio",
      "command": "uv",
      "args": ["--directory", "D:\\\\github\\\\gemini-cli-bridge-mcp", "run", "python", "server.py"],
      "workingDirectory": "D:\\\\github\\\\gemini-cli-bridge-mcp",
      "env": {
        "GEMINI_DEFAULT_MODEL": "gemini-3-pro-preview",
        "GEMINI_FALLBACK_MODEL": "gemini-2.5-pro",
        "GEMINI_FLASH_MODEL": "gemini-2.5-flash",
        "GEMINI_CACHE_TTL_MS": "600000"
      }
    }
  }
}
```
If PATH is restricted, point `command` to the absolute `uv.exe`. The server auto-finds `gemini` (PATH, Roaming/npm, npm bin -g, node_modules/.bin, npx).

### Verify Installation

Type `/mcp` inside Claude Code to verify the gemini-cli MCP is active.

---

## Configuration

Place the JSON above in your MCP client configuration (Claude Desktop/Code). Update paths for your system. After editing, restart the client or reload MCP.

**Configuration file locations (Claude):**
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: `~/.config/claude/claude_desktop_config.json`

### Tools
- `ask-gemini`, `brainstorm`, `fetch-chunk`, `ping`, `help`, `timeout-test`
- `diagnose_gemini_paths` (new): prints the candidate CLI paths and PATH for quick troubleshooting.

### Troubleshooting
- If `ask-gemini` hangs: likely CLI waiting on stdio. The Python server now detaches CLI stdin (`DEVNULL`); ensure Gemini CLI itself returns quickly in your shell.
- If CLI not found: run `diagnose_gemini_paths` via MCP to see discovered candidates. Add `GEMINI_BIN` only if absolutely necessary.

## Example Workflow

- **Natural language**: "use gemini to explain index.html", "understand the massive project using gemini", "ask gemini to search for latest news"
- **Claude Code**: Type `/gemini-cli` and commands will populate in Claude Code's interface.

## Usage Examples

### With File References (using @ syntax)

- `ask gemini to analyze @src/main.js and explain what it does`
- `use gemini to summarize @. the current directory`
- `analyze @package.json and tell me about dependencies`

### General Questions (without files)

- `ask gemini to search for the latest tech news`
- `use gemini to explain div centering`
- `ask gemini about best practices for React development related to @file_im_confused_about`

### Using Gemini CLI's Sandbox Mode (-s)

The sandbox mode allows you to safely test code changes, run scripts, or execute potentially risky operations in an isolated environment.

- `use gemini sandbox to create and run a Python script that processes data`
- `ask gemini to safely test @script.py and explain what it does`
- `use gemini sandbox to install numpy and create a data visualization`
- `test this code safely: Create a script that makes HTTP requests to an API`

### Tools (for the AI)

These tools are designed to be used by the AI assistant.

- **`ask-gemini`**: Asks Google Gemini for its perspective. Can be used for general questions or complex analysis of files.
  - **`prompt`** (required): The analysis request. Use the `@` syntax to include file or directory references (e.g., `@src/main.js explain this code`) or ask general questions (e.g., `Please use a web search to find the latest news stories`).
  - **`model`** (optional): The Gemini model to use. Defaults to `gemini-2.5-pro`.
  - **`sandbox`** (optional): Set to `true` to run in sandbox mode for safe code execution.
- **`sandbox-test`**: Safely executes code or commands in Gemini's sandbox environment. Always runs in sandbox mode.
  - **`prompt`** (required): Code testing request (e.g., `Create and run a Python script that...` or `@script.py Run this safely`).
  - **`model`** (optional): The Gemini model to use.
- **`Ping`**: A simple test tool that echoes back a message.
- **`Help`**: Shows the Gemini CLI help text.

### Slash Commands (for the User)

You can use these commands directly in Claude Code's interface (compatibility with other clients has not been tested).

- **/analyze**: Analyzes files or directories using Gemini, or asks general questions.
  - **`prompt`** (required): The analysis prompt. Use `@` syntax to include files (e.g., `/analyze prompt:@src/ summarize this directory`) or ask general questions (e.g., `/analyze prompt:Please use a web search to find the latest news stories`).
- **/sandbox**: Safely tests code or scripts in Gemini's sandbox environment.
  - **`prompt`** (required): Code testing request (e.g., `/sandbox prompt:Create and run a Python script that processes CSV data` or `/sandbox prompt:@script.py Test this script safely`).
- **/help**: Displays the Gemini CLI help information.
- **/ping**: Tests the connection to the server.
  - **`message`** (optional): A message to echo back.

## Contributing

Contributions are welcome! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details on how to submit pull requests, report issues, and contribute to the project.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

**Disclaimer:** This is an unofficial, third-party tool and is not affiliated with, endorsed, or sponsored by Google.
