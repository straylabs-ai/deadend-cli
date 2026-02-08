# Deadend CLI
**Autonomous pentesting agent using feedback-driven iteration**
Achieves ~78% on XBOW benchmarks with fully local execution and model-agnostic architecture.
![Deadend CLI](./assets/demo_gif.gif)


*Like the project or want to know more? Feel free to [reach out](#contact)!*

> [!WARNING]
> **Active Development**: This project is undergoing active development. Current features are functional but the interface and workflows are being improved based on new architecture and features.



📄 [Read Technical Deep Dive](https://xoxruns.medium.com/feedback-driven-iteration-and-fully-local-webapp-pentesting-ai-agent-achieving-78-on-xbow-199ef719bf01) | 📊 [Benchmark Results (use VScode ANSI colors to view)](https://github.com/xoxruns/deadend-cli/tree/main/benchmarks-results/xbow)

---

## What is Deadend CLI?

Deadend CLI is an autonomous web application penetration testing agent that uses feedback-driven iteration to adapt exploitation strategies. When standard tools fail, it generates custom Python payloads, observes responses, and iteratively refines its approach until breakthrough.

**Key features:**
- Fully local execution (no cloud dependencies, zero data exfiltration)
- Model-agnostic design (works with any deployable LLM)
- Custom sandboxed tools (Playwright, Docker, WebAssembly)
- ADaPT-based architecture with supervisor-subagent hierarchy
- Confidence-based decision making (fail <20%, expand 20-60%, refine 60-80%, validate >80%)

**Benchmark results:** 78% on XBOW validation suite (76/98 challenges), including blind SQL injection exploits where other agents achieved 0%.

[Read the architecture breakdown in our technical article →](https://xoxruns.medium.com/feedback-driven-iteration-and-fully-local-webapp-pentesting-ai-agent-achieving-78-on-xbow-199ef719bf01)

---

## Core Analysis Capabilities

The framework focuses on **intelligent security analysis** through:

- **🔍 Taint Analysis**: Automated tracking of data flow from sources to sinks
- **🎯 Source/Sink Detection**: Intelligent identification of entry points and vulnerable functions
- **🔗 Contextual Tool Integration**: Smart connection to specialized tools for testing complex logic patterns
- **🧠 AI-Driven Reasoning**: Context-aware analysis that mimics expert security thinking

---

## 🔧 Custom Pentesting Tools

- **Webapp-Specific Tooling**: Custom tools designed specifically for web application penetration testing
- **Authentication Handling**: Built-in support for session management, cookies, and auth flows
- **Fine-Grained Testing**: Precise control over individual requests and parameters
- **Payload Generation**: AI-powered payload creation tailored to target context
- **Automated Payload Testing**: Generate, inject, and validate payloads in a single workflow

---

## Quick Start

### Prerequisites
- Docker (required)
- curl (for installation script)

### Installation

**Recommended: Install from release (Linux x86_64 / macOS ARM64)**

```bash
# Install latest release
curl -fsSL https://raw.githubusercontent.com/xoxruns/deadend-cli/main/install.sh | bash

# Or install a specific version
curl -fsSL https://raw.githubusercontent.com/xoxruns/deadend-cli/main/install.sh | bash -s -- --version v1.0.0

# Custom installation directory (default: ~/.cache/server)
curl -fsSL https://raw.githubusercontent.com/xoxruns/deadend-cli/main/install.sh | bash -s -- --install-dir /path/to/install
```

The installer will:
- Download pre-built binaries for your platform
- Install the RPC server to `~/.cache/server` (or custom directory)
- Install the CLI binary to `~/.local/bin` (or `/usr/local/bin` on macOS)
- Set up Playwright browsers automatically

**Alternative: Build from source**

```bash
git clone https://github.com/xoxruns/deadend-cli.git
cd deadend-cli
uv sync && uv build
```

**Legacy: Install via pipx**

```bash
pipx install deadend_cli
```

### First Run
```bash
# Initialize configuration
deadend init

# Start testing
deadend chat \
  --target "http://localhost:3000" \
  --prompt "find SQL injection vulnerabilities"
```

**Note:** If `deadend` is not found, ensure `~/.local/bin` is in your PATH:
```bash
export PATH="$HOME/.local/bin:$PATH"
# Add to ~/.bashrc or ~/.zshrc to make it permanent
```

---

## Usage Examples

### Basic Vulnerability Testing
```bash
# Test OWASP Juice Shop
docker run -p 3000:3000 bkimminich/juice-shop

deadend chat \
  --target "http://localhost:3000" \
  --prompt "test the login endpoint for SQL injection"
```

### API Security Testing
```bash
deadend chat \
  --target "https://api.example.com" \
  --prompt "test authentication endpoints"
```

### Autonomous Mode
```bash
# Run without approval prompts (CTFs/labs only)
deadend chat \
  --target "http://ctf.example.com" \
  --mode yolo \
  --prompt "find and exploit all vulnerabilities"
```

---

## Commands

### `deadend init`
Initialize configuration and set up pgvector database

### `deadend chat`
Start interactive security testing session
- `--target`: Target URL
- `--prompt`: Initial testing prompt
- `--mode`: `hacker` (approval required) or `yolo` (autonomous)

### `deadend eval-agent`
Run evaluation against challenge datasets
- `--eval-metadata-file`: Challenge dataset file
- `--llm-providers`: AI model providers to test
- `--guided`: Run with subtask decomposition

### `deadend version`
Display current version

---

## Architecture Summary

The agent uses a two-phase approach (reconnaissance → exploitation) with a supervisor-subagent hierarchy:

**Supervisor**: Maintains high-level goals, delegates to specialized subagents
**Subagents**: Focused toolsets (Requester for HTTP, Shell for commands, Python for payloads)
**Policy**: Confidence scores (0-1.0) determine whether to fail, expand, refine, or validate

**Key innovation:** When standard tools fail, the agent generates custom exploitation scripts and iterates based on observed feedback—solving challenges like blind SQL injection where static toolchains achieve 0%.

[Read full architecture details →](https://xoxruns.medium.com/feedback-driven-iteration-and-fully-local-webapp-pentesting-ai-agent-achieving-78-on-xbow-199ef719bf01)

---

## Benchmark Results

> **Note**: To visualize the benchmark results properly, install an ANSI colors extension (e.g., [ANSI Colors](https://marketplace.visualstudio.com/items?itemName=iliazeus.vscode-ansi) for VS Code) to render the rich output.

Evaluated on XBOW's 104-challenge validation suite (black-box mode, January 2026):

| Agent | Success Rate | Infrastructure | Blind SQLi |
|-------|-------------|----------------|------------|
| XBOW (proprietary) | 85% | Proprietary | ? |
| Cyber-AutoAgent | 85% (This is the latest Cyber-Autoagent scoring for october 2025) <s>81%</s>| AWS Bedrock | 0% |
| **Deadend CLI** | **78%** | **Fully local** | **33%** |
| MAPTA | 76.9% | External APIs | 0% |

**Models tested:** Claude Sonnet 4.5 (~78%), Kimi K2 Thinking (~69%)

Strong performance: XSS (91%), Business Logic (86%), SQL injection (83%), IDOR (80%)
Perfect scores: GraphQL, SSRF, NoSQL injection, HTTP method tampering (100%)

---

## Operating Modes

**Hacker Mode (default):** Requires approval for dangerous operations
```bash
deadend chat --target URL --mode hacker
```

**YOLO Mode:** Autonomous execution (CTFs/labs only)
```bash
deadend chat --target URL --mode yolo
```

---

## Technology Stack

- **LiteLLM**: Multi-provider model abstraction (OpenAI, Anthropic, Ollama)
- **Instructor**: Structured LLM outputs
- **pgvector**: Vector database for context
- **Pyodide/WebAssembly**: Python sandbox
- **Playwright**: HTTP request generation (bundled with browser binaries)
- **Docker**: Shell command isolation
- **PyOxidizer**: Standalone binary packaging

---

## Configuration

Configuration is managed via `~/.cache/deadend/config.toml`. Run `deadend init` to set up your configuration interactively.

---

## Current Status & Roadmap

### Stable (v0.0.15)
✅ New architecture
✅ XBOW benchmark evaluation (78%)
✅ Custom sandboxed tools
✅ Multi-model support with liteLLM
✅ Two-phase execution (recon + exploitation)

### In Progress (v0.1.0)
🚧 **CLI Redesign** with enhanced workflows:
- Plan mode (review strategies before execution)
- Preset configuration workflows (API testing, web apps, auth bypass)
- Workflow automation (save/replay attack chains)

🚧 Context optimization (reduce redundant tool calls)
🚧 Secrets management improvements


### Future roadmap
The current architecture proves competitive autonomous pentesting (78%) is achievable without cloud dependencies. Next challenges:

- **Open-Source Models**: Achieve 75%+ with Llama/Qwen (eliminate proprietary dependencies)
- **Hybrid Testing**: Add AST analysis for white-box code inspection
- **Adversarial Robustness**: Train against WAFs, rate limiting, adaptive defenses
- **Multi-Target Orchestration**: Test interconnected systems simultaneously
- **Context Efficiency**: Better information sharing between components

Goal: Make autonomous pentesting accessible (open models), comprehensive (hybrid testing), and robust (works against real defenses).

---

## Contributing

Contributions welcome in:
- Context optimization algorithms
- Vulnerability test cases
- Open-weight model fine-tuning
- Adversarial testing scenarios

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on how to contribute.

---

## Citation
```bibtex
@software{deadend_cli_2026,
  author = {Yassine Bargach},
  title = {Deadend CLI: Feedback-Driven Autonomous Pentesting},
  year = {2026},
  url = {https://github.com/xoxruns/deadend-cli}
}
```

---

## Disclaimer

**For authorized security testing only.** Unauthorized testing is illegal. Users are responsible for compliance with all applicable laws and obtaining proper authorization.

---

## Contact

Have questions, feedback, or want to collaborate?

- 📧 **Email**: [yassine@straylabs.ai](mailto:yassine@straylabs.ai)
- 💬 **Discord**: xoxruns
- 💼 **LinkedIn**: [Yassine Bargach](https://www.linkedin.com/in/yass-99637a105/)
- 🐦 **Twitter**: [@xoxruns](https://x.com/xoxruns)

---

## Links

📄 [Architecture Deep Dive](https://xoxruns.medium.com/feedback-driven-iteration-and-fully-local-webapp-pentesting-ai-agent-achieving-78-on-xbow-199ef719bf01)
📊 [Benchmark Results](https://github.com/xoxruns/deadend-cli/tree/main/benchmarks-results/xbow)
🐛 [Report Issues](https://github.com/xoxruns/deadend-cli/issues)
⭐ [Star this repo](https://github.com/xoxruns/deadend-cli)

![Deadend CLI](./assets/zTJJbo2XDi94T8ynIpozt.png)