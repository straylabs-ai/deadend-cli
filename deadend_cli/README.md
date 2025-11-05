# Deadend CLI 

> [!WARNING]  
> This project is still ongoing, any feedback (good or bad) would be awesome ! 
> A lot of things might change, the code needs some optimization on the code chunking 
> a better explanation of what is happening and so on ! But It's coming ! 

## Table of Contents

- [What in the world is this ?](#what-in-the-world-is-this-)
- [A quick demo](#a-quick-demo)
- [🎯 Project Vision & Approach](#-project-vision--approach)
  - [Current State & Development Philosophy](#current-state--development-philosophy)
  - [Core Analysis Capabilities](#core-analysis-capabilities)
  - [Target Scope & Limitations](#target-scope--limitations)
- [🚀 Future Features & Roadmap](#-future-features--roadmap)
  - [Planned Enhancements](#planned-enhancements)
  - [Known Issues & Limitations](#known-issues--limitations)
- [✨ Available Features](#-available-features)
  - [🤖 Multi-Model AI Support](#-multi-model-ai-support)
  - [🌐 Web Application Analysis](#-web-application-analysis)
  - [📚 Knowledge Management](#-knowledge-management)
  - [🔧 Advanced Testing Capabilities](#-advanced-testing-capabilities)
  - [🐳 Secure Execution Environment](#-secure-execution-environment)
- [Installation](#installation)
  - [Prerequisites](#prerequisites)
  - [Install with pipx (Recommended)](#install-with-pipx-recommended)
  - [Build from source](#build-from-source)
- [How to use the CLI](#-how-to-use)
  - [📋 Core Commands](#-core-commands)
  - [🤖 AI Agents & Their Capabilities](#-ai-agents--their-capabilities)
  - [🛠️ Available Tools & Capabilities](#️-available-tools--capabilities)
  - [🎯 Operating Modes](#-operating-modes)
  - [🔍 Security Testing Capabilities](#-security-testing-capabilities)
  - [💬 Interactive Chat Features](#-interactive-chat-features)
  - [🔧 Advanced Features](#-advanced-features)
- [Usage](#usage)
  - [CLI Structure](#cli-structure)
  - [First-time Setup](#first-time-setup)
  - [Environment Variables](#environment-variables)
  - [Running the Chat Agent](#running-the-chat-agent)
  - [Example: OWASP Juice Shop](#example-owasp-juice-shop)
- [Enjoy](#enjoy)
- [⚠️ Disclaimer](#️-disclaimer)

## What in the world is this ? 
Deadend CLI is a prototype AI Agent for security researchers, pentesters and developers. 

Inspired by Google Zero's project Naptime, this project aims to build a prototype of an agentic AI tool that helps gain time and give a better understanding on analysis.
![cli.png](./assets/cli.png)

## 🎯 Project Vision & Approach

> [!WARNING]
> **Evaluation in Progress**: This project is currently undergoing active evaluation and testing across multiple vulnerability types (OWASP Top 10, business logic flaws, authentication bypasses, etc.). Results, performance metrics, and capabilities may vary significantly during this development phase. Do not use in Production environments.

Deadend CLI represents a new paradigm in automated security testing, designed to bridge the gap between traditional static/dynamic analysis tools and the nuanced, context-aware analysis that experienced security professionals perform.

### Current State & Development Philosophy

While the current implementation leverages workflow automation and tool orchestration, the project's core innovation lies in its **AI-assisted vulnerability analysis system**. By combining intelligent code indexing with contextual retrieval mechanisms, Deadend CLI aims to provide deeper insights than traditional automated scanners.

### Core Analysis Capabilities

The framework focuses on **intelligent security analysis** through:

- **🔍 Taint Analysis**: Automated tracking of data flow from sources to sinks
- **🎯 Source/Sink Detection**: Intelligent identification of entry points and vulnerable functions
- **🔗 Contextual Tool Integration**: Smart connection to specialized tools for testing complex logic patterns
- **🧠 AI-Driven Reasoning**: Context-aware analysis that mimics expert security thinking

### Target Scope & Limitations

**Primary Focus**: Web applications and APIs

**Complementary Approach**: Deadend CLI is designed to **enhance**, not replace, existing SAST/DAST tools. It specifically targets vulnerabilities that require human-like reasoning and context understanding:

- **🔐 Broken Access Controls**: Complex authorization bypass scenarios
- **🆔 IDOR Vulnerabilities**: Indirect object reference exploitation patterns  
- **⚙️ Business Logic Flaws**: Application-specific logic vulnerabilities
- **🔄 State Management Issues**: Session and authentication state manipulation
- **📊 Data Validation Bypasses**: Complex input validation circumvention

This approach enables discovery of vulnerabilities that traditional scanners often miss due to their inability to understand application context and business logic.

## 🚀 Future Features & Roadmap

### Planned Enhancements

**🔐 Advanced Authentication Handling**
- Comprehensive authentication flow testing including OAuth, JWT, session management
- Multi-factor authentication bypass techniques
- Credential stuffing and brute force attack automation

**📊 Attack Evaluation Framework**
- Automated testing against OWASP Top 10 vulnerabilities
- Custom attack pattern recognition and validation
- Performance benchmarking against known vulnerability databases

**⚡ Smart Terminal Integration**
- Intelligent command output parsing and summarization
- Context-aware command suggestions based on target analysis
- Automated tool chaining for faster reconnaissance workflows
- Real-time vulnerability correlation from multiple tool outputs

**🔧 MCP (Model Context Protocol) Integration**
- Enhanced AI model communication protocols
- Improved context sharing between different analysis modules
- Better integration with external security tools and APIs

**🐍 Python Exploitation Sandbox**
- Secure code generation and execution environment
- Custom exploit development and testing capabilities
- Integration with popular exploitation frameworks
- Automated payload generation and testing

**📁 Advanced Code Analysis**
- Comprehensive source code indexing and navigation
- Interactive code browser with vulnerability highlighting
- Taint analysis visualization and flow tracking
- Integration with static analysis tools

### Known Issues & Limitations

**⚠️ Current Limitations**

- **Interrupt Handling**: The agent doesn't gracefully handle user interruptions during long-running operations
- **Performance Optimization**: Multiple API calls and inefficient context management impact response times
- **Context Management**: Large request payloads and context window limitations affect analysis depth
- **Tool Integration**: Limited integration with specialized security tools and frameworks

## ✨ Available Features

### 🤖 Multi-Model AI Support
- **OpenAI Models**: GPT-4, GPT-4o-mini with latest capabilities
- **Google Gemini**: Gemini 2.5 Pro for advanced reasoning
- **Anthropic Claude**: Claude models for detailed analysis
- *More providers coming soon*

### 🌐 Web Application Analysis
- **Resource Indexing**: Complete web application structure mapping
- **Local Storage**: Secure local indexing without external dependencies
- **Dynamic Analysis**: Real-time interaction with target applications
- **API Discovery**: Automated endpoint detection and analysis

### 📚 Knowledge Management
- **Personal Notes Indexing**: Index and search your security research notes
- **Local Knowledge Base**: Private, offline knowledge management
- **Context-Aware Search**: Intelligent retrieval based on current analysis context
- **Research Documentation**: Automated documentation of findings

### 🔧 Advanced Testing Capabilities
- **Raw HTTP Requests**: Direct HTTP request manipulation and testing
- **Proxy Integration**: Seamless integration with Burp Suite, OWASP ZAP, and other proxies
- **Request/Response Analysis**: Deep inspection of web traffic
- **Custom Payload Testing**: Flexible payload injection and testing

### 🐳 Secure Execution Environment
- **Docker Sandbox**: Isolated shell environment for safe command execution
- **Containerized Tools**: Pre-configured security tools in secure containers
- **Resource Isolation**: Complete isolation from host system
- **Tool Chain Integration**: Seamless integration with popular pentesting tools

## Installation 

### Prerequisites

**Docker is required** - The application uses Docker to run the pgvector database and other services. Make sure Docker is installed and running before proceeding.

Install Docker from: https://docs.docker.com/get-docker/

**Playwright is required** - The agent also uses playwright for browser interactions. To install, run the following commands :
```bash
# https://playwright.dev/python/docs/intro
pip install pytest-playwright
# or 
pipx install pytest-playwright

# followed by :
playwright install
```

The latter should download the headless browsers needed for the functioning of the app.

### Install with pipx (Recommended)

The `deadend-cli` is available on PyPI and can be installed using pipx:

```bash
# Install pipx if you don't have it
# --> https://github.com/pypa/pipx

# Install deadend_cli
pipx install deadend_cli 
```

### Build from source 

Clone the repository and build using `uv`:

```bash
git clone https://github.com/xoxruns/deadend-cli.git
cd deadend-cli

# Install dependencies and build
uv sync 
uv build
```

## How to use

The Deadend CLI provides an interactive chat interface and specialized agents for security testing.

**Prerequisites**: Docker must be installed and running on your system before using the CLI.

**First-time Setup**: You need to run `deadend-cli init` to initialize all the environment variables and configurations (saved to cache). This command will:
- Check Docker installation and availability
- Set up the required pgvector database container
- Prompt you to configure API keys and environment variables
- Save the configuration to `~/.cache/deadend/config.toml`

After initialization, you can use the other CLI commands for security testing.

### 📋 Core Commands

#### `deadend-cli init`
- **Purpose**: Initialize the CLI configuration and set up required services
- **What it does**:
  - Checks Docker installation and availability
  - Sets up pgvector database container for vector storage
  - Prompts for environment variable configuration
  - Saves configuration to `~/.cache/deadend/config.toml`
  - Validates API keys for AI model providers

#### `deadend-cli chat`
- **Purpose**: Start the interactive AI-powered security testing chat interface
- **Key Parameters**:
  - `--target`: Target URL or identifier for analysis
  - `--prompt`: Initial prompt to pre-fill the chat
  - `--mode`: Choose between `hacker` (requires approval) or `yolo` (autonomous)
  - `--openapi-spec`: Path to OpenAPI specification file for API context
  - `--knowledge-base`: Folder path to personal knowledge base

#### `deadend-cli eval-agent`
- **Purpose**: Run evaluation agent on datasets of security challenges
- **Key Parameters**:
  - `--eval-metadata-file`: Dataset file containing challenge information
  - `--llm-providers`: List of AI model providers to use
  - `--guided`: Run subtasks instead of single general task

#### `deadend-cli version`
- **Purpose**: Display the current version of the Deadend framework

### 🤖 AI Agents & Their Capabilities

#### **Webapp Recon Agent**
- **Specialization**: Web application reconnaissance and vulnerability testing
- **Capabilities**:
  - HTTP request validation and execution
  - Payload injection and testing
  - Web application code analysis through RAG
  - Endpoint discovery and enumeration
  - Authentication bypass testing
  - Input validation testing

#### **Recon Shell Agent**
- **Specialization**: Infrastructure-level security assessment
- **Capabilities**:
  - Network scanning and enumeration
  - System reconnaissance using command-line tools
  - File system analysis
  - Service enumeration
  - Network topology mapping
  - Infrastructure vulnerability assessment

#### **Router Agent**
- **Specialization**: Intelligent task routing and agent selection
- **Capabilities**:
  - Analyzes user requests to determine appropriate agent
  - Routes tasks to specialized agents based on context
  - Manages workflow orchestration
  - Optimizes agent selection for specific security tasks

#### **Judge Agent**
- **Specialization**: Goal achievement assessment and validation
- **Capabilities**:
  - Evaluates whether security objectives have been met
  - Validates vulnerability findings
  - Assesses attack success
  - Provides final assessment and recommendations

### 🛠️ Available Tools & Capabilities

#### **HTTP Request Tools**
- **`send_payload`**: Execute raw HTTP requests with custom payloads
- **`is_valid_request`**: Validate HTTP request format and safety
- **Proxy Integration**: Seamless integration with Burp Suite, OWASP ZAP
- **Request/Response Analysis**: Deep inspection of web traffic

#### **Shell Execution Tools**
- **`sandboxed_shell_tool`**: Execute commands in isolated Docker containers
- **Security Tool Integration**: Access to nmap, nikto, sqlmap, and other tools
- **Command Output Parsing**: Intelligent analysis of tool outputs
- **Safe Execution**: All commands run in sandboxed environments

#### **Code Analysis Tools**
- **`webapp_code_rag`**: Search and analyze source code using RAG
- **Source Code Indexing**: Comprehensive code structure mapping
- **Vulnerability Pattern Detection**: AI-powered code analysis
- **Taint Analysis**: Track data flow from sources to sinks

#### **Web Resource Extraction**
- **Complete Resource Mapping**: Extract all web resources (HTML, JS, CSS, etc.)
- **Dynamic Content Analysis**: Capture dynamically loaded content
- **Performance Metrics**: Analyze loading times and resource efficiency
- **Screenshot Capture**: Visual analysis of web pages

### 🎯 Operating Modes

#### **Hacker Mode** (Default)
- **Approval Required**: All potentially dangerous operations require user approval
- **Interactive Control**: User can review and approve each action
- **Safe Testing**: Ideal for production environments or sensitive targets
- **Manual Oversight**: Full control over the testing process

#### **Yolo Mode**
- **Autonomous Operation**: AI agents execute actions without approval
- **Rapid Testing**: Faster execution for development and testing environments
- **Full Automation**: Complete hands-off security testing
- **Use Case**: Ideal for CTF challenges, lab environments, or rapid prototyping

### 🔍 Security Testing Capabilities

#### **Web Application Security**
- **OWASP Top 10 Testing**: Comprehensive coverage of common vulnerabilities
- **Authentication Bypass**: Test login mechanisms and session management
- **Authorization Testing**: Check access controls and privilege escalation
- **Input Validation**: Test for injection vulnerabilities (SQL, XSS, etc.)
- **Business Logic Flaws**: Identify application-specific vulnerabilities

#### **API Security Testing**
- **OpenAPI Integration**: Load API specifications for targeted testing
- **Endpoint Discovery**: Automated API endpoint enumeration
- **Parameter Testing**: Comprehensive parameter fuzzing and validation
- **Authentication Testing**: API key, JWT, and OAuth testing

#### **Infrastructure Security**
- **Network Scanning**: Port scanning and service enumeration
- **System Reconnaissance**: OS fingerprinting and service analysis
- **Vulnerability Assessment**: Automated vulnerability detection
- **Configuration Analysis**: Security misconfiguration identification

### 💬 Interactive Chat Features

#### **Rich Terminal Interface**
- **Real-time Output**: Live display of agent actions and results
- **Formatted Results**: Beautiful tables and panels for data presentation
- **Progress Tracking**: Visual indicators for long-running operations
- **Error Handling**: Clear error messages and recovery suggestions

#### **Chat Commands**
- **`/help`**: Show available commands and keyboard shortcuts
- **`/clear`**: Clear conversation context and start fresh
- **`/new-target`**: Change the target URL during the session
- **`/quit`**: Exit the application safely

#### **Keyboard Shortcuts**
- **`Ctrl+C`**: Exit the application
- **`Ctrl+I`**: Interrupt running agent operations
- **`Enter`**: Submit input and continue conversation

### 🔧 Advanced Features

#### **Knowledge Base Integration**
- **Personal Notes**: Index and search your security research notes
- **Context-Aware Search**: Intelligent retrieval based on current analysis
- **Research Documentation**: Automated documentation of findings
- **Local Storage**: Private, offline knowledge management

#### **Multi-Model Support**
- **Provider Flexibility**: Switch between OpenAI, Google, and Anthropic models
- **Model Comparison**: Use multiple providers for evaluation
- **Fallback Mechanisms**: Automatic failover between providers
- **Custom Configuration**: Fine-tune model parameters

#### **Docker Integration**
- **Automatic Setup**: Self-configuring pgvector database
- **Container Management**: Automatic start/stop of required services
- **Resource Isolation**: Complete isolation from host system
- **Tool Containers**: Pre-configured security tools in containers



## Usage 

### CLI Structure

The Deadend CLI provides the following commands:

- `deadend-cli init` - Initialize the CLI configuration and set up required services
- `deadend-cli chat` - Start the interactive chat agent
- `deadend-cli eval-agent` - Run evaluation agent on a dataset of challenges
- `deadend-cli version` - Show the version of the Deadend framework

### First-time Setup

**Important**: Before using the CLI, you must run the initialization command:

```bash
deadend-cli init
```

This command will:
- Check if Docker is installed and running
- Set up the pgvector database container
- Prompt you to configure environment variables
- Save the configuration to `~/.cache/deadend/config.toml`

### Environment Variables

The init command will prompt you for the following environment variables:

```bash
OPENAI_API_KEY=sk-proj-<your-api-key>
OPENAI_MODEL="gpt-4o-mini-2024-07-18"
ANTHROPIC_API_KEY=<your-anthropic-key>
ANTHROPIC_MODEL=""
GEMINI_API_KEY=<your-gemini-key>
GEMINI_MODEL="gemini-2.5-pro"
EMBEDDING_MODEL="text-embedding-3-small"
DB_URL="postgresql://postgres:postgres@localhost:54320/codeindexerdb"
APP_ENV="development"
LOG_LEVEL="INFO"
```

### Running the Chat Agent

After initialization, you can start the chat agent:

```bash
deadend-cli chat --target "http://localhost:3000" --prompt "analyze this web application for vulnerabilities"
```

### Example: OWASP Juice Shop

1. Start the OWASP Juice Shop web application:
```bash
docker run --rm -p 127.0.0.1:3000:3000 bkimminich/juice-shop
```

2. Initialize the CLI (if not done already):
```bash
deadend-cli init
```

3. Run the chat agent:
```bash
deadend-cli chat --target "http://localhost:3000/#/login" --prompt "extract the login endpoint and test for a sql injection"
```


## Enjoy
If You find this project cool enough to explore more, drop a star, and if you have a idea that we could implement, create an issue and/or contribute directly to the repo ! 

## ⚠️ Disclaimer

**This project is intended for educational and research purposes only.**

> Unauthorized or malicious use of this tool against systems that you do not own or have explicit permission to test is illegal and unethical. The developers of this project are not responsible for any misuse or damage caused by this tool.

> Always conduct cybersecurity research and testing in compliance with all applicable laws, ethical guidelines, and with the proper consent.