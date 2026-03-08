/**
 * @file deadend-rpc-client.ts
 * @description High-level RPC client specifically designed for DeadEnd security testing operations.
 *
 * This module wraps the low-level StdioRpcClient with DeadEnd-specific functionality:
 * - Task execution with phase-based event streaming (recon, exploit, done)
 * - Component health checks and initialization
 * - Approval workflow for dangerous operations
 * - Event subscription for real-time agent monitoring
 *
 * ## Architecture
 *
 * ```
 * ┌─────────────────────────────────────────────────────────────────────────────┐
 * │                              Deno CLI (React/Ink)                           │
 * ├─────────────────────────────────────────────────────────────────────────────┤
 * │  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────────────────┐ │
 * │  │   Chat.tsx      │  │  YoloView.tsx   │  │  NormalView.tsx              │ │
 * │  │  (commands)     │  │  (YOLO mode)    │  │  (supervisor mode)           │ │
 * │  └────────┬────────┘  └────────┬────────┘  └─────────┬────────────────────┘ │
 * │           │                    │                     │                      │
 * │           └────────────────────┼─────────────────────┘                      │
 * │                                ▼                                            │
 * │  ┌─────────────────────────────────────────────────────────────────────────┐│
 * │  │                        DeadEndRpcClient                                 ││
 * │  │  - runTask() / runTaskWithCallbacks()                                   ││
 * │  │  - healthAll() / initDocker() / initPgvector() / ...                    ││
 * │  │  - subscribeEvents() / interrupt() / approve()                          ││
 * │  └────────────────────────────────────────────────────────────────────────┘│
 * │                                │                                            │
 * │                     ┌──────────▼──────────┐                                 │
 * │                     │   StdioRpcClient    │                                 │
 * │                     │   (JSON-RPC 2.0)    │                                 │
 * │                     └─────────┬───────────┘                                 │
 * └───────────────────────────────┼─────────────────────────────────────────────┘
 *                                 │ stdin/stdout
 *                      ┌──────────▼──────────┐
 *                      │   Python RPC Server │
 *                      │   (deadend_cli.rpc) │
 *                      └─────────────────────┘
 * ```
 *
 * ## Task Execution Phases
 *
 * When running a security testing task, events flow through three phases:
 *
 * 1. **Recon Phase**: Threat modeling, target analysis, vulnerability identification
 *    - Events contain reconnaissance data, threat models, attack surface analysis
 *
 * 2. **Exploit Phase**: Active security testing, payload execution
 *    - Events contain tool calls, responses, agent thoughts, findings
 *
 * 3. **Done Phase**: Task completion with final results
 *    - Contains mode, target, and any generated reports
 *
 * ## Usage Example
 *
 * ```typescript
 * // Create and initialize client
 * const client = new DeadEndRpcClient({
 *   pythonCommand: "uv",
 *   commandArgs: ["run", "python", "-m", "deadend_cli.jsonrpc_server"],
 *   onRecon: (data) => console.log("Recon:", data),
 *   onExploit: (data) => console.log("Exploit:", data),
 * });
 * await client.start();
 *
 * // Initialize components
 * await client.initDocker();
 * await client.initPgvector();
 * await client.initShellSandbox();
 *
 * // Run security testing task
 * for await (const event of client.runTask({
 *   target: "http://example.com",
 *   prompt: "Find SQL injection vulnerabilities",
 *   mode: "yolo",
 * })) {
 *   console.log(`Phase: ${event.phase}`);
 * }
 *
 * // Clean shutdown
 * await client.shutdown();
 * client.close();
 * ```
 */

import {
  StdioRpcClient,
  type StdioRpcClientOptions,
} from "./stdio-rpc-client.ts";
import type {
  TaskEvent,
  StreamingRpcClient,
  AgentEvent,
  AllHealthResult,
  HealthResult,
  InitResult,
  ApprovalModeResult,
  AllInitResult,
} from "../types/rpc.ts";

// =============================================================================
// Task Event Types
// =============================================================================

/**
 * Event emitted during the initialization phase.
 *
 * The init phase includes:
 * - Component verification
 * - Target reachability check
 * - Agent initialization
 * - Target crawling and embedding
 *
 * @property phase - Always "init" to identify this event type
 * @property data - Initialization progress data (messages, status, etc.)
 */
export interface InitEvent {
  phase: "init";
  data: unknown;
}

/**
 * Event emitted during the reconnaissance phase.
 *
 * The recon phase includes:
 * - Target crawling and discovery
 * - Threat modeling
 * - Attack surface analysis
 * - Vulnerability hypothesis generation
 *
 * @property phase - Always "recon" to identify this event type
 * @property data - Reconnaissance data (threat models, findings, etc.)
 */
export interface ReconEvent {
  phase: "recon";
  data: unknown;
}

/**
 * Event emitted during the exploitation phase.
 *
 * The exploit phase includes:
 * - Active security testing
 * - Payload execution
 * - Vulnerability verification
 * - Tool calls and results
 *
 * @property phase - Always "exploit" to identify this event type
 * @property data - Exploitation data (tool results, findings, etc.)
 */
export interface ExploitEvent {
  phase: "exploit";
  data: unknown;
}

/**
 * Event emitted during the supervising phase (supervisor mode only).
 *
 * The supervising phase includes:
 * - Step-by-step execution with approval workflow
 * - Agent reasoning and planning
 * - Tool call requests awaiting approval
 *
 * @property phase - Always "supervising" to identify this event type
 * @property data - Supervision data (agent thoughts, tool requests, etc.)
 */
export interface SupervisingEvent {
  phase: "supervising";
  data: unknown;
}

/**
 * Event emitted when a task completes.
 *
 * The done event signals the end of task execution and contains
 * final summary information about the completed task.
 *
 * @property phase - Always "done" to identify this event type
 * @property mode - Execution mode used ("yolo" or "supervisor")
 * @property target - The target URL that was tested
 * @property openapi_spec - Optional OpenAPI specification if provided
 * @property knowledge_base - Optional knowledge base content if provided
 */
export interface DoneEvent {
  phase: "done";
  mode: string;
  target: string;
  openapi_spec?: unknown;
  knowledge_base?: string;
}

/**
 * Event emitted when an error occurs during task execution.
 *
 * The error event is emitted before the stream errors out,
 * providing details about what went wrong.
 *
 * @property phase - Always "error" to identify this event type
 * @property data - Error details (message, error_type, etc.)
 */
export interface ErrorEvent {
  phase: "error";
  data: {
    message: string;
    error_type: string;
  };
}

/**
 * Union type of all possible task events.
 *
 * Use this type when handling events from runTask() and need to
 * discriminate between phases using the `phase` property.
 *
 * @example
 * ```typescript
 * for await (const event of client.runTask(params)) {
 *   switch (event.phase) {
 *     case "init":
 *       handleInit(event.data);
 *       break;
 *     case "recon":
 *       handleRecon(event.data);
 *       break;
 *     case "exploit":
 *       handleExploit(event.data);
 *       break;
 *     case "supervising":
 *       handleSupervising(event.data);
 *       break;
 *     case "done":
 *       handleDone(event);
 *       break;
 *     case "error":
 *       handleError(event.data);
 *       break;
 *   }
 * }
 * ```
 */
export type DeadEndTaskEvent = InitEvent | ReconEvent | ExploitEvent | SupervisingEvent | DoneEvent | ErrorEvent;

// =============================================================================
// Client Options
// =============================================================================

/**
 * Configuration options for DeadEndRpcClient.
 *
 * Extends StdioRpcClientOptions with DeadEnd-specific callback handlers
 * for event-driven programming patterns.
 *
 * ## Callback Execution
 *
 * Callbacks are invoked synchronously when events are received, before
 * the event is yielded from the async generator. This allows side effects
 * (like UI updates) to happen immediately.
 *
 * @property onRecon - Called when a recon phase event is received
 * @property onExploit - Called when an exploit phase event is received
 * @property onDone - Called when the task completes
 * @property onError - Called when an error occurs during task execution
 * @property onEvent - Called for any agent event (from subscribeEvents)
 */
export interface DeadEndRpcClientOptions extends StdioRpcClientOptions {
  /** Callback invoked for each initialization event */
  onInit?: (data: unknown) => void;

  /** Callback invoked for each reconnaissance event */
  onRecon?: (data: unknown) => void;

  /** Callback invoked for each exploitation event */
  onExploit?: (data: unknown) => void;

  /** Callback invoked when task completes */
  onDone?: (event: DoneEvent) => void;

  /** Callback invoked on task errors */
  onError?: (error: Error) => void;

  /** Callback invoked for each agent event (from subscribeEvents) */
  onEvent?: (event: AgentEvent) => void;
}

// =============================================================================
// DeadEndRpcClient
// =============================================================================

/**
 * High-level RPC client for DeadEnd security testing operations.
 *
 * This client provides a domain-specific API for:
 * - Running security testing tasks with streaming results
 * - Managing infrastructure components (Docker, databases, sandboxes)
 * - Subscribing to real-time agent events
 * - Controlling task execution (approval, interruption)
 *
 * ## Component Lifecycle
 *
 * Before running tasks, components must be initialized in order:
 * 1. `initDocker()` - Docker daemon connection (required)
 * 2. `initPgvector()` - Vector database for RAG (optional)
 * 3. `initConfig()` - Load LLM API keys and settings
 * 4. `initShellSandbox()` - Prepare Kali container for shell commands
 * 5. `initPythonSandbox()` - Start Python interpreter sandbox
 * 6. `initPlaywright()` - Browser automation (optional)
 *
 * ## Execution Modes
 *
 * - **YOLO Mode**: Autonomous execution without human intervention
 * - **Supervisor Mode**: Step-by-step execution with approval workflow
 *
 * @example
 * ```typescript
 * const client = new DeadEndRpcClient({
 *   pythonCommand: "uv",
 *   commandArgs: ["run", "python", "-m", "deadend_cli.jsonrpc_server"],
 * });
 *
 * await client.start();
 * await client.initDocker();
 *
 * // Run in YOLO mode
 * for await (const event of client.runTask({
 *   target: "http://vulnerable-app.com",
 *   prompt: "Test for authentication bypasses",
 *   mode: "yolo",
 * })) {
 *   console.log(event);
 * }
 * ```
 */
export class DeadEndRpcClient {
  /** The underlying stdio RPC client for JSON-RPC communication */
  private client: StdioRpcClient;

  /** Configuration options including callbacks */
  private options: DeadEndRpcClientOptions;

  /**
   * Creates a new DeadEndRpcClient.
   *
   * @param options - Configuration options including Python command,
   *                  working directory, and event callbacks
   */
  constructor(options: DeadEndRpcClientOptions = {}) {
    this.client = new StdioRpcClient(options);
    this.options = options;
  }

  /**
   * Starts the RPC client by spawning the Python server subprocess.
   *
   * Must be called before any other methods. The server will be ready
   * to accept RPC calls after this method resolves.
   *
   * @returns Promise that resolves when the server is started
   */
  async start(): Promise<void> {
    await this.client.start();
  }

  /**
   * Checks if the RPC server is responsive.
   *
   * @returns Promise resolving to true if server responds, false otherwise
   */
  async ping(): Promise<boolean> {
    return this.client.ping();
  }

  // ===========================================================================
  // Generic RPC Methods
  // ===========================================================================

  /**
   * Makes a generic RPC call for extensibility.
   *
   * Use this for calling RPC methods not covered by the typed methods.
   *
   * @param method - The RPC method name
   * @param params - Optional parameters for the method
   * @param timeout - Timeout in milliseconds (default: 300000)
   * @returns Promise resolving to the method result
   */
  async call(method: string, params?: unknown, timeout = 30000): Promise<unknown> {
    return this.client.call(method, params, timeout);
  }

  /**
   * Sends a notification (fire-and-forget) to the server.
   *
   * @param method - The RPC method name
   * @param params - Optional parameters for the method
   */
  notify(method: string, params?: unknown): void {
    this.client.notify(method, params);
  }

  /**
   * Makes a generic streaming RPC call for extensibility.
   *
   * @param method - The RPC method name
   * @param params - Optional parameters for the method
   * @yields Each result from the streaming method
   */
  async *callStream(method: string, params?: unknown): AsyncGenerator<unknown, void, unknown> {
    yield* this.client.callStream(method, params);
  }

  /**
   * Closes the RPC client and terminates the server subprocess.
   */
  close(): void {
    this.client.close();
  }

  /**
   * Returns whether the client is currently running.
   */
  get running(): boolean {
    return this.client.running;
  }

  /**
   * Access to the underlying StdioRpcClient for advanced usage.
   *
   * Use this when you need direct access to the low-level client,
   * for example to implement custom streaming behavior.
   */
  get rawClient(): StreamingRpcClient {
    return this.client;
  }

  // ===========================================================================
  // Health Check Methods
  // ===========================================================================

  /**
   * Checks the health of all components at once.
   *
   * Returns a comprehensive health report including:
   * - Docker daemon connectivity
   * - pgvector database status
   * - Python sandbox process status
   * - Shell sandbox readiness
   * - Playwright browser status
   *
   * @returns Promise resolving to AllHealthResult with overall status and per-component details
   */
  async healthAll(): Promise<AllHealthResult> {
    const result = await this.client.call("health_all");
    return result as AllHealthResult;
  }

  /**
   * Checks Docker daemon health.
   *
   * @returns Promise resolving to HealthResult for Docker
   */
  async healthDocker(): Promise<HealthResult> {
    const result = await this.client.call("health_docker");
    return result as HealthResult;
  }

  /**
   * Checks pgvector database health.
   *
   * @returns Promise resolving to HealthResult for pgvector
   */
  async healthPgvector(): Promise<HealthResult> {
    const result = await this.client.call("health_pgvector");
    return result as HealthResult;
  }

  /**
   * Checks Python sandbox process health.
   *
   * @returns Promise resolving to HealthResult for Python sandbox
   */
  async healthPythonSandbox(): Promise<HealthResult> {
    const result = await this.client.call("health_python_sandbox");
    return result as HealthResult;
  }

  /**
   * Checks shell sandbox readiness.
   *
   * @returns Promise resolving to HealthResult for shell sandbox
   */
  async healthShellSandbox(): Promise<HealthResult> {
    const result = await this.client.call("health_shell_sandbox");
    return result as HealthResult;
  }

  /**
   * Checks Playwright browser health.
   *
   * @returns Promise resolving to HealthResult for Playwright
   */
  async healthPlaywright(): Promise<HealthResult> {
    const result = await this.client.call("health_playwright");
    return result as HealthResult;
  }

  // ===========================================================================
  // Initialization Methods
  // ===========================================================================

  /**
   * Initializes the Docker daemon connection.
   *
   * This must be called first as other components depend on Docker.
   * Verifies Docker daemon is running and accessible.
   *
   * @returns Promise resolving to InitResult with success status
   */
  async initDocker(): Promise<InitResult> {
    const result = await this.client.call("init_docker");
    return result as InitResult;
  }

  /**
   * Initializes the pgvector database container.
   *
   * Starts the pgvector container if not running and verifies
   * database connectivity. Used for RAG (retrieval-augmented generation).
   *
   * Requires: initDocker() must be called first
   *
   * @returns Promise resolving to InitResult with success status
   */
  async initPgvector(): Promise<InitResult> {
    const result = await this.client.call("init_pgvector");
    return result as InitResult;
  }

  /**
   * Loads and validates the configuration.
   *
   * Reads API keys and settings from the config file.
   * Reports which LLM providers are configured.
   *
   * @returns Promise resolving to InitResult with success status
   */
  async initConfig(): Promise<InitResult> {
    const result = await this.client.call("init_config");
    return result as InitResult;
  }

  /**
   * Initializes the Python sandbox for code execution.
   *
   * Downloads (if needed) and starts the Python sandbox process.
   * The sandbox provides secure Python code execution for agents.
   *
   * @returns Promise resolving to InitResult with success status
   */
  async initPythonSandbox(): Promise<InitResult> {
    const result = await this.client.call("init_python_sandbox");
    return result as InitResult;
  }

  /**
   * Initializes the shell sandbox (Kali Linux container).
   *
   * Pulls the Kali image if not present and prepares the sandbox
   * manager for creating shell execution containers.
   *
   * Requires: initDocker() must be called first
   *
   * @returns Promise resolving to InitResult with success status
   */
  async initShellSandbox(): Promise<InitResult> {
    const result = await this.client.call("init_shell_sandbox");
    return result as InitResult;
  }

  /**
   * Initializes the Playwright browser for web automation.
   *
   * Launches a headless Chromium browser for web scraping
   * and payload delivery.
   *
   * @returns Promise resolving to InitResult with success status
   */
  async initPlaywright(): Promise<InitResult> {
    const result = await this.client.call("init_playwright");
    return result as InitResult;
  }

  /**
   * Initializes the model registry with configured LLM providers.
   *
   * Loads and validates LLM model configurations from the config.
   * Must be called after initConfig().
   *
   * @returns Promise resolving to InitResult with success status
   */
  async initModelRegistry(): Promise<InitResult> {
    const result = await this.client.call("init_model_registry");
    return result as InitResult;
  }

  /**
   * Initializes all components in the correct order.
   *
   * This is the recommended way to initialize the client as it ensures
   * proper dependency order and provides a comprehensive result.
   *
   * Initialization order:
   * 1. Docker (required by pgvector and shell_sandbox)
   * 2. Config (required by model_registry)
   * 3. pgvector (requires Docker)
   * 4. Model Registry (requires Config)
   * 5. Python sandbox (standalone)
   * 6. Shell sandbox (requires Docker)
   * 7. Playwright (standalone)
   *
   * @param timeout - Optional timeout in milliseconds (default: 300000)
   * @returns Promise resolving to AllInitResult with overall status and per-component details
   *
   * @example
   * ```typescript
   * const result = await client.initAll();
   * if (!result.overall_success) {
   *   console.error("Failed components:", result.failed_components);
   * }
   * ```
   *
   * @example
   * ```typescript
   * // Use custom timeout of 10 minutes
   * const result = await client.initAll(600000);
   * ```
   */
  async initAll(timeout: number): Promise<AllInitResult> {
    const result = await this.client.call("init_all", undefined, timeout);
    return result as AllInitResult;
  }

  // ===========================================================================
  // Event Subscription (Streaming)
  // ===========================================================================

  /**
   * Subscribes to the agent event stream.
   *
   * This method yields all events from agent execution in real-time:
   * - agent_start, agent_end, agent_error
   * - tool_call_start, tool_call_end
   * - agent_thought, agent_routed
   * - approval_required, workflow_interrupted
   *
   * The onEvent callback is invoked for each event before yielding.
   *
   * @yields AgentEvent for each event in the stream
   *
   * @example
   * ```typescript
   * for await (const event of client.subscribeEvents()) {
   *   if (event.type === "tool_call_end") {
   *     console.log("Tool completed:", event.data);
   *   }
   * }
   * ```
   */
  subscribeEvents(): { generator: AsyncGenerator<AgentEvent>; abort: () => void } {
    const { generator, abort } = this.client.stream<AgentEvent>("subscribe_events", {});
    const options = this.options;
    return {
      generator: (async function* () {
        for await (const event of generator) {
          const agentEvent = event as AgentEvent;
          // Invoke callback before yielding
          if (options.onEvent) {
            options.onEvent(agentEvent);
          }
          yield agentEvent;
        }
      }()),
      abort,
    };
  }

  // ===========================================================================
  // Control Methods
  // ===========================================================================

  /**
   * Interrupts a running workflow.
   *
   * Sends an interrupt signal to stop the specified session.
   * The agent will attempt to stop gracefully and emit a
   * workflow_interrupted event.
   *
   * @param sessionId - The session ID to interrupt
   * @param reason - Optional reason for the interruption
   * @returns Promise resolving to interrupt status
   */
  async interrupt(sessionId: string, reason?: string): Promise<{ status: string; session_id: string }> {
    const result = await this.client.call("interrupt", {
      session_id: sessionId,
      reason: reason ?? "User requested interruption",
    });
    return result as { status: string; session_id: string };
  }

  /**
   * Interrupts a running agent by ID.
   *
   * Calls the interrupt_agent RPC (streaming); consumes the first chunk
   * and returns the status. Use when the agent is running to stop the workflow.
   *
   * @param agentId - The agent ID to interrupt
   * @returns Promise resolving to { status: "interrupted", agent_id } or error payload
   */
  async interruptAgent(agentId: string): Promise<{ status: string; agent_id?: string; reason?: string }> {
    const { generator } = this.client.stream<{ status: string; agent_id?: string; reason?: string; phase?: string; data?: unknown }>("interrupt_agent", {
      agent_id: agentId,
    });
    for await (const chunk of generator) {
      return chunk as { status: string; agent_id?: string; reason?: string };
    }
    return { status: "unknown" };
  }

  /**
   * Responds to a tool approval request.
   *
   * When approval mode is enabled, dangerous tool calls require
   * user approval before execution. This method responds to those
   * approval requests.
   *
   * @param requestId - The approval request ID
   * @param approved - Whether to approve the tool call
   * @param modifiedArgs - Optional modified arguments for the tool call
   * @returns Promise resolving to approval status
   */
  async approve(
    requestId: string,
    approved: boolean,
    modifiedArgs?: Record<string, unknown>
  ): Promise<{ status: string; request_id: string }> {
    const result = await this.client.call("approve", {
      request_id: requestId,
      approved,
      modified_args: modifiedArgs,
    });
    return result as { status: string; request_id: string };
  }

  /**
   * Enables approval mode for tool calls.
   *
   * When enabled, all tool calls will require explicit user approval
   * before execution. Approval requests are emitted as events.
   *
   * @returns Promise resolving to approval mode status
   */
  async enableApprovalMode(): Promise<ApprovalModeResult> {
    const result = await this.client.call("enable_approval_mode");
    return result as ApprovalModeResult;
  }

  /**
   * Disables approval mode for tool calls.
   *
   * When disabled, tools execute without requiring approval.
   * This is the default mode (YOLO mode).
   *
   * @returns Promise resolving to approval mode status
   */
  async disableApprovalMode(): Promise<ApprovalModeResult> {
    const result = await this.client.call("disable_approval_mode");
    return result as ApprovalModeResult;
  }

  /**
   * Gets the current approval mode status.
   *
   * @returns Promise resolving to current approval mode state
   */
  async getApprovalMode(): Promise<{ approval_mode: boolean }> {
    const result = await this.client.call("get_approval_mode");
    return result as { approval_mode: boolean };
  }

  // ===========================================================================
  // Agent Management Methods
  // ===========================================================================

  /**
   * Instantiates a new agent for security testing.
   *
   * Creates a DeadEndAgent instance with the specified target and stores it
   * in the agent references for later use with embedTarget and runAgentRecursive.
   * The agent ID is auto-generated and returned in the response.
   *
   * @param target - The target URL to test
   * @param provider - Optional provider name (uses current if not provided)
   * @param modelName - Optional model name (uses current if not provided)
   * @returns Promise resolving to agent creation status and agent ID
   *
   * @example
   * ```typescript
   * const result = await client.instantiateAgent("http://example.com");
   * console.log("Agent ID:", result.agent_id);
   * ```
   */
  async instantiateAgent(
    target: string,
    provider?: string,
    modelName?: string
  ): Promise<{ status: string; agent_id: string }> {
    // Get current provider and model if not specified
    

    const params: Record<string, unknown> = { target };
    
    // Only include provider/model if we have them
    if (provider) {
      params.provider = provider;
    }
    if (modelName) {
      params.model_name = modelName;
    }
    
    const result = await this.client.call("instantiate_agent", params);
    return result as { status: string; agent_id: string };
  }

  /**
   * Embeds target code into the vector database.
   *
   * This method crawls the target, extracts code, and stores embeddings
   * in the vector database for RAG (retrieval-augmented generation).
   *
   * This is a streaming method that yields initialization events as the
   * embedding process progresses.
   *
   * @param agentId - The agent ID from instantiateAgent
   * @param target - The target URL to embed
   * @returns Object with generator and abort function
   *
   * @example
   * ```typescript
   * const { generator, abort } = client.embedTarget(agentId, "http://example.com");
   * for await (const event of generator) {
   *   console.log("Embedding:", event.data);
   * }
   * ```
   */
  embedTarget(
    agentId: string,
    target: string
  ): { generator: AsyncGenerator<InitEvent>; abort: () => void } {
    const { generator, abort } = this.client.stream<TaskEvent>("embed_target", {
      agent_id: agentId,
      target,
    });
    const options = this.options;
    
    return {
      generator: (async function* () {
        for await (const event of generator) {
          const taskEvent = event as TaskEvent;
          
          // Handle error events
          if (taskEvent.phase === "error") {
            const errorData = taskEvent.data as { message?: string; error_type?: string };
            throw new Error(errorData?.message || "Error during target embedding");
          }
          
          // Handle status: "failed" format (legacy error format)
          if ("status" in taskEvent && (taskEvent as { status?: string }).status === "failed") {
            const failedEvent = taskEvent as { reason?: string };
            throw new Error(failedEvent.reason || "Failed to embed target");
          }
          
          // Handle init phase events
          if (taskEvent.phase === "init") {
            // Invoke callback before yielding
            if (options.onInit) {
              options.onInit(taskEvent.data);
            }
            yield { phase: "init", data: taskEvent.data } as InitEvent;
          }
          
          // Handle done phase - stream is complete
          if (taskEvent.phase === "done") {
            break;
          }
        }
      }()),
      abort,
    };
  }

  /**
   * Runs the agent in recursive mode (recon + exploit phases).
   *
   * This method executes the full security testing workflow:
   * 1. Recon phase: Threat modeling and vulnerability analysis
   * 2. Exploit phase: Active testing and exploitation
   *
   * This is a streaming method that yields events for each phase.
   *
   * @param agentId - The agent ID from instantiateAgent
   * @param prompt - The task prompt describing what to test
   * @returns Object with generator and abort function
   *
   * @example
   * ```typescript
   * const { generator, abort } = client.runAgentRecursive(agentId, "Find SQL injection");
   * for await (const event of generator) {
   *   if (event.phase === "recon") {
   *     console.log("Recon:", event.data);
   *   } else if (event.phase === "exploit") {
   *     console.log("Exploit:", event.data);
   *   }
   * }
   * ```
   */
  runAgentRecursive(
    agentId: string,
    prompt: string
  ): { generator: AsyncGenerator<DeadEndTaskEvent>; abort: () => void } {
    const { generator, abort } = this.client.stream<TaskEvent>("run_agent_recursive", {
      agent_id: agentId,
      prompt,
    });
    const options = this.options;
    
    return {
      generator: (async function* () {
        for await (const event of generator) {
          const taskEvent = event as TaskEvent;

          switch (taskEvent.phase) {
            case "recon": {
              // Invoke callback before yielding
              if (options.onRecon) {
                options.onRecon(taskEvent.data);
              }
              yield { phase: "recon", data: taskEvent.data } as ReconEvent;
              break;
            }

            case "exploit": {
              // Invoke callback before yielding
              if (options.onExploit) {
                options.onExploit(taskEvent.data);
              }
              yield { phase: "exploit", data: taskEvent.data } as ExploitEvent;
              break;
            }

            case "error": {
              // Error event contains details before stream errors
              const errorData = taskEvent.data as { message: string; error_type: string };
              yield { phase: "error", data: errorData } as ErrorEvent;
              break;
            }
          }
        }
      }()),
      abort,
    };
  }

  /**
   * Runs the agent in supervisor mode (step-by-step with approval workflow).
   *
   * This method executes the security testing workflow in supervisor mode:
   * 1. Supervising phase: Step-by-step execution with approval requests
   * 2. Recon phase: Reconnaissance and analysis results
   *
   * This is a streaming method that yields events for each phase.
   *
   * @param agentId - The agent ID from instantiateAgent
   * @param prompt - The task prompt describing what to test
   * @returns Object with generator and abort function
   *
   * @example
   * ```typescript
   * const { generator, abort } = client.runAgentSupervisor(agentId, "Find SQL injection");
   * for await (const event of generator) {
   *   if (event.phase === "supervising") {
   *     console.log("Supervising:", event.data);
   *   } else if (event.phase === "recon") {
   *     console.log("Recon:", event.data);
   *   }
   * }
   * ```
   */
  runAgentSupervisor(
    agentId: string,
    prompt: string
  ): { generator: AsyncGenerator<DeadEndTaskEvent>; abort: () => void } {
    const { generator, abort } = this.client.stream<TaskEvent>("run_agent_supervisor", {
      agent_id: agentId,
      prompt,
    });
    const options = this.options;
    
    return {
      generator: (async function* () {
        for await (const event of generator) {
          const taskEvent = event as TaskEvent;

          switch (taskEvent.phase) {
            case "supervising": {
              // Invoke callback before yielding (using onRecon for supervising events)
              if (options.onRecon) {
                options.onRecon(taskEvent.data);
              }
              yield { phase: "supervising", data: taskEvent.data } as SupervisingEvent;
              break;
            }

            case "recon": {
              // In supervisor mode, "recon" events are part of the supervising workflow
              // Map them to "supervising" phase to keep UI consistent
              if (options.onRecon) {
                options.onRecon(taskEvent.data);
              }
              yield { phase: "supervising", data: taskEvent.data } as SupervisingEvent;
              break;
            }

            case "error": {
              // Error event contains details before stream errors
              const errorData = taskEvent.data as { message: string; error_type: string };
              yield { phase: "error", data: errorData } as ErrorEvent;
              break;
            }
          }
        }
      }()),
      abort,
    };
  }

  // ===========================================================================
  // LLM Provider Methods
  // ===========================================================================

  /**
   * Gets the current LLM provider and model.
   *
   * @returns Promise resolving to the current provider and model name
   */
  async getLlmProvider(): Promise<{ provider: string; model: string | null }> {
    const result = await this.client.call("get_llm_provider");
    return result as { provider: string; model: string | null };
  }

  /**
   * Sets the LLM provider to use for task execution.
   *
   * @param provider - The provider name (openai, google, anthropic)
   * @returns Promise resolving to status and new provider
   * @throws Error if provider is not configured
   */
  async setLlmProvider(provider: string): Promise<{ status: string; provider: string }> {
    const result = await this.client.call("set_llm_provider", { provider });
    return result as { status: string; provider: string };
  }

  /**
   * Lists all available LLMs and their provider configured.
   *
   * @returns Promise resolving to current provider and list of all providers with model info
   */
  async GetAllModels(): Promise<{
    models: Record<string, Record<string, string>[]>;
  }> {
    const result = await this.client.call("get_all_models");
    return result as { models: Record<string, Record<string, string>[]> };
  }

  // ===========================================================================
  // Shutdown
  // ===========================================================================

  /**
   * Gracefully shuts down all components.
   *
   * Stops all running components in reverse order:
   * - Playwright browser
   * - Python sandbox process
   * - Shell sandbox containers
   * - pgvector database (optional)
   * - RAG connector
   *
   * @returns Promise resolving to shutdown status for each component
   */
  async shutdown(): Promise<{ status: string; components: Record<string, boolean> }> {
    const result = await this.client.call("shutdown");
    return result as { status: string; components: Record<string, boolean> };
  }
}

/**
 * Convenience function to create and start a DeadEnd client in one step.
 *
 * @param options - Configuration options for the client
 * @returns Promise resolving to a started DeadEndRpcClient
 *
 * @example
 * ```typescript
 * const client = await createDeadEndRpcClient({
 *   pythonCommand: "uv",
 *   commandArgs: ["run", "python", "-m", "deadend_cli.jsonrpc_server"],
 * });
 * // Client is ready to use
 * ```
 */
export async function createDeadEndRpcClient(
  options?: DeadEndRpcClientOptions
): Promise<DeadEndRpcClient> {
  const client = new DeadEndRpcClient(options);
  await client.start();
  return client;
}
