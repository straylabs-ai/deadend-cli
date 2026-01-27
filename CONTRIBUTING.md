# Contributing to Deadend CLI

Thank you for your interest in contributing to Deadend CLI! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Code Style & Conventions](#code-style--conventions)
- [Making Contributions](#making-contributions)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)

## Getting Started

### Prerequisites

- **Python 3.11+** required
- **Docker** - Required for running the pgvector database and sandbox execution
- **uv >= 0.5.30** - Package manager for dependency management (older versions may fail to parse `uv.lock`; run `uv self update`)
- **Playwright** - For browser automation

### Setting Up Your Development Environment

1. **Fork and clone the repository**:

   ```bash
   git clone https://github.com/<your-username>/deadend-cli.git
   cd deadend-cli
   ```

2. **Install dependencies**:

   ```bash
   uv sync
   ```

3. **Install Playwright browsers**:

   ```bash
   pipx install pytest-playwright
   playwright install
   ```

4. **Initialize the CLI**:
   ```bash
   deadend-cli init
   ```

## Development Setup

### Building from Source

```bash
uv sync
uv build
```

### Running Tests

```bash
pytest
```

### Code Formatting

Format your code before committing:

```bash
# Format with black
black .

# Sort imports
isort .

# Lint with flake8
flake8 .
```

## Project Structure

```
deadend-cli/
├── deadend_cli/              # CLI entry point and workflow orchestration
│   └── src/deadend_cli/
├── deadend_agent/            # Core agent framework
│   └── src/deadend_agent/
│       ├── agents/           # Specialized AI agents
│       ├── tools/            # Agent tools (shell, browser, RAG, etc.)
│       ├── rag/              # RAG database and retrieval
│       ├── sandbox/          # Docker sandbox management
│       ├── embedders/        # Code indexing and embeddings
│       └── context/          # Context engine and memory
├── deadend_prompts/          # Jinja2 prompt templates
├── deadend_eval/             # Evaluation framework
└── tests/                    # Test suite
```

## Code Style & Conventions

### Python Style

- Use **black** for code formatting
- Use **isort** for import sorting
- Follow **flake8** linting rules
- Use type hints throughout

### Pydantic v2

This project uses Pydantic v2. Key conventions:

```python
from pydantic import BaseModel, Field

class MyModel(BaseModel):
    # Use Field(default_factory=list) for mutable defaults
    items: list[str] = Field(default_factory=list)

    # Use .model_dump(), not .dict()
    def to_dict(self):
        return self.model_dump()
```

### Async/Await

All I/O operations should be async:

```python
async def my_function():
    result = await some_async_operation()
    return result
```

### Agent Output Pattern

Agent outputs should extend `AgentOutput`:

```python
class AgentOutput(BaseModel):
    confidence_score: float  # 0.0 to 1.0
    notes: str | None = None
    updated_state: dict[str, Any] | None = None
```

### Conventions Summary

- **Confidence scores**: Always 0.0 to 1.0 (float), not percentages
- **Task status**: Use `"pending"`, `"expanding"`, `"completed"`, `"failed"`, `"validated"`
- **Forward references**: Use `from __future__ import annotations`
- **Type constraints**: Use `Literal["value1", "value2"]` for constrained strings

## Making Contributions

### Types of Contributions

- **Bug fixes**: Fix issues and improve stability
- **New features**: Add new capabilities aligned with the project vision
- **Documentation**: Improve docs, examples, and guides
- **Tests**: Expand test coverage
- **Performance**: Optimize code and reduce API calls

### Before You Start

1. Check existing [issues](https://github.com/xoxruns/deadend-cli/issues) for related work
2. For significant changes, open an issue first to discuss your approach
3. Ensure your contribution aligns with the project's security research focus

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov

# Run specific test file
pytest tests/test_specific.py

# Run async tests
pytest -v  # pytest-asyncio handles async tests
```

### Writing Tests

- Use `pytest` for all tests
- Use `@pytest.mark.asyncio` for async tests
- Use `pytest-mock` for mocking

Example:

```python
import pytest

@pytest.mark.asyncio
async def test_my_async_function():
    result = await my_async_function()
    assert result is not None
```

## Submitting Changes

### Pull Request Process

1. **Create a branch**:

   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following the code style guidelines

3. **Run tests and formatting**:

   ```bash
   black .
   isort .
   flake8 .
   pytest
   ```

4. **Commit your changes**:

   ```bash
   git add .
   git commit -m "Add: brief description of changes"
   ```

5. **Push and create a PR**:

   ```bash
   git push origin feature/your-feature-name
   ```

6. Open a Pull Request against the `main` branch

### Commit Message Guidelines

- Use clear, descriptive commit messages
- Start with a verb: `Add`, `Fix`, `Update`, `Remove`, `Refactor`
- Keep the first line under 72 characters

### PR Requirements

- All tests must pass
- Code must be formatted with black and isort
- No flake8 errors
- Update documentation if needed
- Add tests for new functionality

## Questions or Issues?

- Open an issue on [GitHub](https://github.com/xoxruns/deadend-cli/issues)
- Check the README for usage documentation

## License

By contributing, you agree that your contributions will be licensed under the same license as the project.

---

Thank you for contributing to Deadend CLI!
