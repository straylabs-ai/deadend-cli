# Deadend CLI Architecture

## Overview

The Deadend CLI (`deadend_cli`) is the command-line interface and orchestration layer for the Deadend security testing framework. It provides an interactive chat interface, evaluation capabilities, and workflow management for AI-powered security research agents.

## Module Structure

```
deadend_cli/
├── src/deadend_cli/
│   ├── main.py              # Application entry point
│   ├── cli.py               # Typer-based CLI commands
│   ├── chat.py              # Interactive chat interface
│   ├── workflow_runner.py   # Workflow orchestration engine
│   ├── eval.py              # Evaluation interface
│   ├── init.py              # Configuration initialization
│   ├── console.py           # Console output utilities
│   ├── banner.py            # Startup banner
│   └── rpc_server.py        # RPC server (future use)
└── data/
    └── memory/
        └── reusable_credentials.json  # Default credential storage
```

## Core Components

### 1. Entry Point (`main.py`)

The main entry point initializes the application and copies reusable credentials to the cache directory:

```python
def main():
    """Entry point for the deadend CLI application."""
    # Copy reusable credentials to ~/.cache/deadend/memory/
    # Run the Typer CLI application
    asyncio.run(app())
```

**Key Responsibilities:**
- Bootstrap the application
- Set up credential storage in `~/.cache/deadend/memory/`
- Launch the Typer CLI application

### 2. CLI Commands (`cli.py`)

The CLI is built using [Typer](https://typer.tiangolo.com/) and provides four main commands:

#### `deadend version`
Displays the installed version of Deadend CLI.

```bash
deadend version
# Output: Deadend CLI v0.1.0
```

#### `deadend init`
Initializes the CLI configuration by:
- Checking Docker availability
- Setting up the pgvector database container
- Pulling the sandboxed Kali Linux image
- Prompting for API keys and configuration values
- Saving configuration to `~/.cache/deadend/config.toml`

```bash
deadend init
```

**Configuration Values:**
- `OPENAI_API_KEY`: OpenAI API key (hidden input)
- `OPENAI_MODEL`: OpenAI model name (default: gpt-4o-mini-2024-07-18)
- `ANTHROPIC_API_KEY`: Anthropic API key (hidden input)
- `ANTHROPIC_MODEL`: Anthropic model name
- `GEMINI_API_KEY`: Google Gemini API key (hidden input)
- `GEMINI_MODEL`: Gemini model name (default: gemini-2.5-pro)
- `EMBEDDING_MODEL`: Embedding model for RAG
- `DB_URL`: PostgreSQL database URL
- `ZAP_PROXY_API_KEY`: ZAP proxy API key (hidden input)
- `APP_ENV`: Application environment (default: development)
- `LOG_LEVEL`: Logging level (default: INFO)

#### `deadend chat`
Launches the interactive chat interface for security testing.

```bash
deadend chat --target https://example.com --mode hacker
```

**Options:**
- `--prompt`: Initial prompt to send directly
- `--target`: Target URL or identifier
- `--mode`: Execution mode (yolo or hacker)
  - `yolo`: Autonomous mode, minimal user intervention
  - `hacker`: Interactive mode, requires user approval for actions
- `--openapi-spec`: Path to OpenAPI specification file
- `--knowledge-base`: Path to knowledge base folder

**Workflow:**
1. Checks Docker availability
2. Verifies/starts pgvector database container
3. Loads configuration from cache
4. Starts Python sandbox for secure code execution
5. Configures monitoring with Logfire
6. Launches interactive chat interface
7. Cleans up on exit (terminates sandbox, stops database)

#### `deadend eval-agent`
Runs evaluation tests on a dataset of security challenges.

```bash
deadend eval-agent --eval-metadata-file challenges.json --llm-providers openai --guided
```

**Options:**
- `--eval-metadata-file`: Path to JSON file containing challenge metadata
- `--llm-providers`: List of model providers to use (default: openai)
- `--guided`: Run subtasks instead of one general task

**Workflow:**
1. Checks Docker availability and database status
2. Loads configuration
3. Starts Python sandbox
4. Executes evaluation interface
5. Generates evaluation reports

### 3. Chat Interface (`chat.py`)

The chat interface provides a rich terminal-based experience using Rich and Prompt Toolkit.

#### ChatInterface Class

**Key Features:**
- Real-time status updates with animated spinners
- Structured output rendering with Rich panels and tables
- Interactive input using Prompt Toolkit
- Command support (`/help`, `/clear`, `/new-target`, `/quit`)
- Tool execution approval workflow
- Interrupt handling (Ctrl+I)

**Available Commands:**
- `/help`: Display help message
- `/clear`: Clear conversation context
- `/new-target`: Change the target URL
- `/quit`: Exit the application
- `Ctrl+C`: Exit gracefully
- `Ctrl+I`: Interrupt running agent

#### Execution Modes

**Hacker Mode (Default):**
- Requires user approval for tool execution
- Interactive confirmation dialogs
- Step-by-step control over agent actions

**YOLO Mode:**
- Autonomous execution
- Minimal user intervention
- Faster but less controlled

#### Workflow Phases

The chat interface operates in two main phases:

**Phase 1: Threat Modeling**
```python
async for item in deadend_agent.threat_model_stream(task=user_prompt):
    # Extract target information
    # Analyze technology stack
    # Discover endpoints
    # Generate threat model
```

**Phase 2: Security Testing**
```python
async for item in deadend_agent.start_testing_stream(
    task=user_prompt,
    threat_model=threat_model
):
    # Execute security tests
    # Analyze responses
    # Validate findings
    # Generate final report
```

#### Output Rendering

The interface handles different output types:

1. **ThreatModelOutput**: Displays target information, tech stack, and endpoints
2. **RequesterOutput**: Shows HTTP request analysis and raw responses
3. **RouterOutput**: Indicates agent routing decisions
4. **PlannerOutput**: Presents task breakdown
5. **JudgeOutput**: Final validation and results

### 4. Workflow Runner (`workflow_runner.py`)

The WorkflowRunner orchestrates the entire security testing workflow by managing agents, context, and execution state.

#### Class Architecture

```python
class WorkflowRunner:
    config: Config                          # Configuration object
    model: AIModel                          # AI model instance
    code_indexer_db: RetrievalDatabaseConnector  # RAG database
    sandbox: Sandbox | None                 # Sandbox environment
    context: ContextEngine                  # Context management
    session_id: uuid.UUID                   # Unique session ID
    goal_achieved: bool                     # Completion flag
    interrupted: bool                       # Interruption flag
```

#### Key Methods

**Initialization**
```python
def __init__(
    self,
    model: AIModel,
    config: Config,
    code_indexer_db: RetrievalDatabaseConnector,
    sandbox: Sandbox | None,
    mode: str = "hacker"
)
```

**Target Indexing**
```python
def init_webtarget_indexer(self, target: str) -> None
    """Initialize web target indexer for the given URL."""

async def crawl_target(self)
    """Crawl the web target to gather resources."""

async def embed_target(self)
    """Generate embeddings for crawled content."""
```

**Knowledge Base Management**
```python
def knowledge_base_init(self, folder_path: str) -> None
    """Initialize knowledge base indexer."""

async def knowledge_base_index(self)
    """Generate embeddings for knowledge base documents."""
```

**Workflow Execution**
```python
async def plan_tasks(self, goal: str, target: str) -> PlannerOutput
    """Plan tasks for achieving the goal."""

async def route_task(self, prompt: str) -> RouterOutput
    """Route task to appropriate agent."""

async def run_agent(
    self,
    agent_name: str,
    prompt: str | None,
    message_history: str,
    deferred_tool_results: DeferredToolResults | None = None
)
    """Execute an agent with the given prompt."""

async def start_workflow(
    self,
    prompt: str,
    target: str,
    validation_type: str | None,
    validation_format: str | None
)
    """Start the main workflow execution."""
```

**Context Management**
```python
async def summarize_workflow_context(self) -> None
    """Summarize context using reporter agent."""

def add_assets_to_context(self, assets_folder: str) -> None
    """Add non-binary files from assets folder to context."""
```

**Workflow Control**
```python
def interrupt_workflow(self) -> None
    """Interrupt the workflow execution."""

def reset_workflow_state(self) -> None
    """Reset workflow state for new execution."""

def set_approval_callback(self, callback)
    """Set callback function for user approval."""
```

#### Agent Registry

The WorkflowRunner manages multiple specialized agents:

```python
available_agents = {
    'webapp_recon': "Expert cybersecurity agent for web enumeration",
    'recon_shell': "System reconnaissance with command-line tools",
    'python_interpreter_agent': "Code generation and execution",
    'router_agent': "Routes to specific agent for next step"
}
```

#### Dependency Management

The workflow builds dependency containers for different agent types:

```python
def _build_webapp_recon_deps(self) -> WebappreconDeps
    """Build dependencies for reconnaissance agents."""
    # Creates:
    # - OpenAI embedder client
    # - Shell runner (sandbox)
    # - RAG dependencies
    # - Requester dependencies
    # - Webapp recon dependencies
```

#### Execution Loop

The main workflow loop:

1. **Plan Tasks**: Break down the goal into subtasks
2. **Route Task**: Select appropriate agent for current task
3. **Execute Agent**: Run the selected agent
4. **Handle Tool Approval**: Get user confirmation if needed
5. **Summarize Context**: Condense context to stay under token limits
6. **Validate Results**: Use judge agent to verify goal achievement
7. **Iterate**: Continue until goal is achieved or max iterations reached

```python
MAX_ITERATION = 3

while not self.goal_achieved and iteration < MAX_ITERATION and not self.interrupted:
    # Route to agent
    agent_router = await self.route_task(prompt=prompt)

    # Execute agent
    agent_response = await self.run_agent(
        agent_name=self.context.next_agent,
        prompt=prompt,
        message_history=""
    )

    # Handle tool approval if needed
    if isinstance(agent_response.output, DeferredToolRequests):
        approval = await self._get_user_approval_for_tool_requests(
            agent_response,
            self.context.next_agent
        )

    # Summarize context
    await self.summarize_workflow_context()

    # Validate with judge
    judge_output = await judge_agent.run(
        prompt=context_text,
        ...
    )

    if judge_output.output.goal_achieved:
        self.goal_achieved = True
```

### 5. Evaluation Interface (`eval.py`)

The evaluation interface runs automated tests on security challenges.

#### Key Function

```python
async def eval_interface(
    config: Config,
    eval_metadata_file: str,
    providers: list[str],
    guided: bool
)
```

**Workflow:**
1. Load evaluation metadata from JSON file
2. Initialize model registry
3. Set up RAG database
4. Create sandbox environment
5. Configure monitoring (Logfire)
6. Execute evaluation agent
7. Generate evaluation reports

**Evaluation Metadata Structure:**
```json
{
    "challenge_name": "XSS Challenge",
    "target": "https://example.com",
    "assets_path": "/path/to/assets",
    "steps": [
        {
            "goal": "Find XSS vulnerability",
            "validation_type": "canary",
            "validation_format": "Check for alert popup"
        }
    ]
}
```

**Features:**
- Automated challenge execution
- Multi-model testing support
- Performance metrics collection
- Detailed evaluation reports
- No human intervention mode
- Context engine integration
- Code indexing and RAG support

### 6. Configuration and Initialization (`init.py`)

#### Docker Management

**Check Docker Availability**
```python
def check_docker(client: docker.DockerClient) -> bool
    """Check if Docker daemon is running."""
```

**pgvector Database Setup**
```python
def check_pgvector_container(client: docker.DockerClient) -> bool
    """Check if pgvector container is running."""

def setup_pgvector_database(client: docker.DockerClient) -> bool
    """Setup pgvector database container."""
    # Image: pgvector/pgvector:pg17
    # Container name: deadend_pg
    # Port: 54320
    # Database: codeindexerdb
    # Credentials: postgres/postgres
    # Volume: ~/.cache/deadend/postgres_data
```

**Sandbox Image Management**
```python
def pull_sandboxed_kali_image(client: docker.DockerClient) -> bool
    """Pull the sandboxed Kali Linux image."""
    # Image: xoxruns/sandboxed_kali:latest
```

**Container Lifecycle**
```python
def stop_pgvector_container(client: docker.DockerClient) -> bool
    """Stop the pgvector container."""
```

#### Configuration File

The configuration is stored in TOML format at `~/.cache/deadend/config.toml`:

```toml
OPENAI_API_KEY = "sk-proj-..."
OPENAI_MODEL = "gpt-4o-mini-2024-07-18"
ANTHROPIC_API_KEY = "sk-ant-..."
ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
GEMINI_API_KEY = "AIza..."
GEMINI_MODEL = "gemini-2.5-pro"
EMBEDDING_MODEL = "text-embedding-3-small"
DB_URL = "postgresql://postgres:postgres@localhost:54320/codeindexerdb"
ZAP_PROXY_API_KEY = ""
APP_ENV = "development"
LOG_LEVEL = "INFO"
```

## Data Flow

### Chat Session Flow

```
User Input
    ↓
[ChatInterface]
    ↓
[WorkflowRunner.start_workflow]
    ↓
[Planner] → Plan tasks
    ↓
[Router] → Select agent
    ↓
[Agent Execution] ← (WebappRecon/Shell/Python)
    ↓
[Tool Approval] ← (if mode=hacker)
    ↓
[Context Summarization]
    ↓
[Judge Validation]
    ↓
[Output to User]
```

### Target Indexing Flow

```
Target URL
    ↓
[SourceCodeIndexer.crawl_target]
    ↓
Web Resources (HTML/JS/CSS)
    ↓
[SourceCodeIndexer.serialized_embedded_code]
    ↓
Code Chunks + Embeddings
    ↓
[RAG Database.batch_insert_code_chunks]
    ↓
pgvector Database
    ↓
[Agent Retrieval during execution]
```

### Evaluation Flow

```
Eval Metadata JSON
    ↓
[EvalMetadata Parser]
    ↓
[Sandbox Setup with Volume]
    ↓
[eval_deadend_agent]
    ↓
[Target Indexing + Knowledge Base]
    ↓
[Agent Execution per Challenge]
    ↓
[Metrics Collection]
    ↓
[Evaluation Report]
```

## Dependencies and Integration

### External Dependencies

**Core Framework:**
- `deadend_agent`: Agent framework and core logic
- `deadend_eval`: Evaluation framework
- `deadend_prompts`: Prompt templates

**Infrastructure:**
- `docker`: Container management
- `asyncpg`: Async PostgreSQL driver
- `pgvector`: Vector similarity search

**AI/LLM:**
- `pydantic-ai`: Agent framework
- `openai`: OpenAI API client
- Google Generative AI
- Anthropic API

**CLI/UI:**
- `typer`: CLI framework
- `rich`: Terminal formatting
- `prompt-toolkit`: Interactive input

**Monitoring:**
- `logfire`: Observability and instrumentation

### Integration Points

**With deadend_agent:**
- `Config`: Configuration object
- `AIModel`: Model abstraction
- `Sandbox`: Execution environment
- `RetrievalDatabaseConnector`: RAG database
- `SourceCodeIndexer`: Code indexing
- `ContextEngine`: Context management
- Agent classes: `WebappReconAgent`, `ShellAgent`, etc.

**With External Services:**
- Docker daemon (required)
- PostgreSQL with pgvector (managed container)
- Python sandbox container (managed)
- LLM API providers (OpenAI, Anthropic, Gemini)

## Error Handling and Resilience

### Graceful Degradation

**Docker Unavailable:**
```python
if not check_docker(docker_client):
    console.print("[red]Docker is required...")
    raise typer.Exit(1)
```

**Database Connection Failure:**
```python
try:
    rag_db = await init_rag_database(config.db_url)
except (SQLAlchemyError, OSError) as exc:
    console.print(f"[red]Vector DB not accessible...")
    raise SystemExit(1) from exc
```

**Sandbox Startup Failure:**
```python
try:
    sandbox_manager = sandbox_setup()
except Exception as e:
    console.print(f"[yellow]Sandbox could not be started...")
    # Continue without sandbox
```

### Workflow Interruption

**User Interruption (Ctrl+I):**
```python
def interrupt_agent():
    agent_interrupted = True
    deadend_agent.interrupt_workflow()
```

**Interrupt Propagation:**
```python
if self.interrupted:
    raise InterruptedError("Workflow interrupted...")
```

**Cleanup on Exit:**
```python
finally:
    if python_process.poll() is None:
        python_process.terminate()
    try:
        stop_pgvector_container(docker_client)
    except (DockerException, OSError, ConnectionError) as e:
        console.print(f"[yellow]Warning: Could not stop container...")
```

## Performance Considerations

### Token Management

**Context Summarization:**
The workflow automatically summarizes context to stay under LLM token limits:

```python
async def summarize_workflow_context(self) -> None
    """Summarize context to stay under 150,000 tokens."""
    reporter_agent = ReporterAgent(...)
    await reporter_agent.summarize_context(self.context)
```

**Memory Efficiency:**
- Conversation history limited to 50 messages
- Automatic context compression after each iteration
- Selective file loading (skip binary files)

### Concurrent Operations

**Parallel Indexing:**
```python
# Web target crawling and embedding
web_resources = await crawl_target()
embeddings = await embed_target()

# Database insertion
await rag_db.batch_insert_code_chunks(code_chunks)
```

**Async Agent Execution:**
All agent operations are async, allowing for efficient I/O handling.

## Security Considerations

### Sandboxed Execution

- All code execution happens in Docker containers
- Isolated network environment
- Volume mounts only for evaluation assets
- Container cleanup on exit

### Credential Management

- API keys stored in user cache directory (`~/.cache/deadend/`)
- Hidden input for sensitive values during `init`
- No hardcoded credentials in source
- Reusable credentials copied to isolated location

### Tool Approval Flow

In hacker mode, all dangerous operations require user approval:

```python
async def _get_user_approval_for_tool_requests(
    self,
    deferred_requests: DeferredToolRequests,
    agent_name: str
) -> bool
    """Prompt user for approval on tool requests."""
    # Display tool details
    # Wait for user confirmation
    # Return approval decision
```

## Extension Points

### Custom Agents

Register new agents in the workflow runner:

```python
available_agents = {
    'custom_agent': "Description of custom agent capabilities",
    ...
}
```

Implement agent in `_get_agent()`:

```python
case "custom_agent":
    return CustomAgent(
        model=self.model,
        deps_type=CustomDeps,
        ...
    )
```

### Custom Tools

Add tools to agents during initialization:

```python
custom_tools = [
    Tool(custom_tool_function),
    ...
]

agent = WebappReconAgent(
    ...,
    additional_tools=custom_tools
)
```

### Custom Output Handlers

Extend `ChatInterface` to handle custom output types:

```python
if isinstance(item, CustomOutput):
    # Custom rendering logic
    print_custom_output(item)
```

## Monitoring and Observability

### Logfire Integration

```python
logfire.configure(scrubbing=False, console=None)
logfire.instrument_pydantic_ai()
```

**Tracked Metrics:**
- Agent execution times
- Token usage per agent
- Tool execution counts
- Success/failure rates
- Context size over time

### Console Output

Rich formatting for clear visualization:
- Spinners for long-running operations
- Color-coded status messages
- Structured panels for agent outputs
- Tables for structured data
- Progress indicators for multi-step operations

## Best Practices

### Running Chat Sessions

1. **Always initialize first:**
   ```bash
   deadend init
   ```

2. **Use hacker mode for control:**
   ```bash
   deadend chat --target https://example.com --mode hacker
   ```

3. **Monitor token usage:**
   - Context auto-summarizes every iteration
   - Use `/clear` to reset context if needed

4. **Handle interruptions gracefully:**
   - Use Ctrl+I to stop current operation
   - Workflow state is preserved

### Running Evaluations

1. **Prepare evaluation metadata:**
   ```json
   {
       "challenge_name": "Challenge Name",
       "target": "https://target.com",
       "assets_path": "/path/to/assets",
       "steps": [...]
   }
   ```

2. **Run evaluation:**
   ```bash
   deadend eval-agent --eval-metadata-file metadata.json --llm-providers openai
   ```

3. **Review reports:**
   - Output saved to current directory
   - Includes success rates, timing, and findings

### Troubleshooting

**Docker issues:**
```bash
# Check Docker status
docker ps

# Restart Docker daemon
sudo systemctl restart docker

# Re-run init
deadend init
```

**Database issues:**
```bash
# Check container logs
docker logs deadend_pg

# Restart container
docker restart deadend_pg
```

**Sandbox issues:**
```bash
# Check sandbox container
docker ps -a | grep kali

# Pull image manually
docker pull xoxruns/sandboxed_kali:latest
```

## Future Enhancements

### Planned Features

1. **Shell Wrapper Mode:**
   - Direct shell command integration
   - Real-time command suggestion
   - History-based learning

2. **Custom Tool Integration:**
   - MCP server support
   - Custom tool registration
   - Tool composition

3. **Automated Reporting:**
   - Structured report generation
   - Export to multiple formats (PDF, HTML, JSON)
   - Template customization

4. **Multi-Target Support:**
   - Concurrent target testing
   - Target comparison
   - Bulk scanning

5. **Enhanced Context Management:**
   - Persistent context across sessions
   - Context sharing between targets
   - Smart context retrieval

## Conclusion

The Deadend CLI provides a powerful and flexible interface for AI-powered security testing. Its architecture emphasizes:

- **Modularity**: Clean separation of concerns
- **Extensibility**: Easy to add new agents and tools
- **Resilience**: Graceful error handling and recovery
- **Usability**: Rich terminal interface with clear feedback
- **Security**: Sandboxed execution and approval workflows

For more information on specific components:
- Agent Framework: See `deadend_agent` documentation
- Evaluation Framework: See `deadend_eval` documentation
- Prompt Engineering: See `deadend_prompts` documentation
