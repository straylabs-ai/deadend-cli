# Introduction

**Deadend CLI** is an agentic security testing framework designed to help security researchers and penetration testers find vulnerabilities in web applications faster and more efficiently. Built with modern AI capabilities, Deadend CLI automates the tedious aspects of security testing while maintaining the flexibility and control that security professionals need.

## What is Deadend CLI?

Deadend CLI is a command-line tool that leverages AI agents to perform autonomous security assessments of web applications. Unlike traditional automated scanners, Deadend CLI uses an agentic approach where an AI agent can:

- **Analyze application source code** and map the codebase structure
- **Plan and execute security tests** based on common vulnerability patterns
- **Adapt its testing strategy** based on findings and application responses
- **Execute payloads safely** in a sandboxed environment
- **Provide detailed findings** and attack path visualizations

## Why Deadend CLI?

Security testing is a time-consuming process that requires deep expertise and careful attention to detail. Traditional tools often produce false positives, miss complex vulnerabilities, or require extensive manual configuration. Deadend CLI addresses these challenges by:

- **Accelerating vulnerability discovery** through intelligent automation
- **Reducing false positives** with context-aware analysis
- **Supporting both autonomous and guided testing** modes
- **Keeping everything local and secure** - your data and findings stay on your machine
- **Working with any AI model** - from cloud APIs to local models running on your hardware

## Key Capabilities

### Autonomous Security Testing
Run full security assessments with minimal intervention. The agent can map applications, identify attack surfaces, and test for common vulnerabilities like those in the OWASP Top 10.

### Flexible Model Support
Use any AI model provider you prefer:
- **Cloud providers**: OpenAI, Anthropic, Google Gemini
- **Local models**: Run models locally using Ollama or other local inference servers

### Sandboxed Execution
All security testing tools and payloads run in isolated sandboxes, ensuring your testing activities don't affect your system or accidentally impact production environments.

### Codebase Analysis
Deep integration with code indexing allows the agent to understand application structure, identify security-relevant code paths, and perform static analysis alongside dynamic testing.

### Multiple Operating Modes
- **YOLO Mode**: Fully autonomous agent that runs end-to-end security assessments
- **Hacker Mode**: Interactive mode for guided testing, specific vulnerability research, or when you need the agent's help with particular tasks

## Who Should Use Deadend CLI?

Deadend CLI is designed for:
- **Security researchers** conducting vulnerability research
- **Penetration testers** performing security assessments
- **Bug bounty hunters** looking to scale their testing efforts
- **Security teams** needing to integrate automated testing into their workflows
- **Developers** who want to understand security issues in their applications

## Getting Started

Ready to start finding vulnerabilities? Check out the [Installation Guide](/installation) to get Deadend CLI set up on your system, then head to the [Usage Guide](/usage) to learn how to run your first security assessment.

