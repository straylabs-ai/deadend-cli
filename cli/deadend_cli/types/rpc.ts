/**
 * @file rpc.ts
 * @description Type definitions for JSON-RPC 2.0 communication between the Deno CLI and Python backend.
 *
 * This module defines all the TypeScript interfaces and types used for:
 * - JSON-RPC 2.0 protocol structures (requests, responses, errors)
 * - RPC client interfaces for both single and streaming calls
 * - Task execution events and parameters
 * - Agent events from the Python backend
 * - Component health and initialization status
 * - Approval workflow types
 *
 * ## Type Hierarchy
 *
 * ```
 * RpcClient (base interface)
 *    └── StreamingRpcClient (adds streaming + lifecycle)
 *
 * AgentEvent (all events from agents)
 *    ├── agent_start, agent_end, agent_error
 *    ├── tool_call_start, tool_call_end
 *    ├── agent_thought, agent_routed
 *    └── approval_required, workflow_interrupted, ...
 *
 * TaskEvent (task execution phases)
 *    ├── recon phase
 *    ├── exploit phase
 *    └── done phase
 * ```
 *
 * ## Correspondence with Python Types
 *
 * These types mirror the Python `rpc_models.py` definitions to ensure
 * type safety across the RPC boundary. When modifying types here,
 * ensure the Python models are updated to match.
 */

// =============================================================================
// JSON-RPC 2.0 Protocol Types
// =============================================================================

/**
 * JSON-RPC 2.0 request object.
 *
 * Sent from client to server to invoke a method.
 *
 * @property jsonrpc - Must be exactly "2.0" per the JSON-RPC specification
 * @property id - Request identifier for correlating responses. null for notifications
 * @property method - The name of the method to invoke
 * @property params - Optional parameters for the method (positional or named)
 *
 * @see https://www.jsonrpc.org/specification#request_object
 *
 * @example
 * ```json
 * {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
 * ```
 */
export interface JsonRpcRequest {
  jsonrpc: "2.0";
  id: string | number | null;
  method: string;
  params?: unknown;
}

/**
 * JSON-RPC 2.0 response object.
 *
 * Sent from server to client in response to a request.
 * Contains either a result (success) or error (failure), never both.
 *
 * @property jsonrpc - Must be exactly "2.0" per the JSON-RPC specification
 * @property id - The same id as the request this is responding to
 * @property result - The result of the method call (on success)
 * @property error - Error object if the call failed
 *
 * @see https://www.jsonrpc.org/specification#response_object
 *
 * @example Success
 * ```json
 * {"jsonrpc": "2.0", "id": 1, "result": {"status": "ok"}}
 * ```
 *
 * @example Error
 * ```json
 * {"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "Invalid Request"}}
 * ```
 */
export interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: string | number | null;
  result?: unknown;
  error?: JsonRpcError;
}

/**
 * JSON-RPC 2.0 error object.
 *
 * Contains error information when an RPC call fails.
 *
 * @property code - A number indicating the type of error
 *                  - -32700: Parse error
 *                  - -32600: Invalid Request
 *                  - -32601: Method not found
 *                  - -32602: Invalid params
 *                  - -32603: Internal error
 *                  - -32000 to -32099: Server error (reserved)
 * @property message - A short description of the error
 * @property data - Optional additional data about the error
 *
 * @see https://www.jsonrpc.org/specification#error_object
 */
export interface JsonRpcError {
  code: number;
  message: string;
  data?: unknown;
}

/**
 * JSON-RPC 2.0 error codes.
 *
 * Standard and custom error codes used by the RPC server.
 * These mirror the Python RPCErrorCode class in rpc_models.py.
 */
export const RpcErrorCode = {
  // Standard JSON-RPC errors
  PARSE_ERROR: -32700,
  INVALID_REQUEST: -32600,
  METHOD_NOT_FOUND: -32601,
  INVALID_PARAMS: -32602,
  INTERNAL_ERROR: -32603,

  // Custom error codes (reserved range: -32000 to -32099)
  COMPONENT_ERROR: -32001,
  INITIALIZATION_FAILED: -32002,
  HEALTH_CHECK_FAILED: -32003,
  SHUTDOWN_ERROR: -32004,
  EVENT_STREAM_ERROR: -32005,
  APPROVAL_ERROR: -32006,
  INTERRUPT_ERROR: -32007,

  // LLM-related error codes
  LLM_ERROR: -32010,
  LLM_RATE_LIMIT: -32011,
  LLM_QUOTA_EXCEEDED: -32012,
  LLM_AUTH_ERROR: -32013,
  LLM_CONNECTION_ERROR: -32014,
  LLM_MODEL_NOT_FOUND: -32015,
  LLM_INVALID_REQUEST: -32016,
} as const;

/**
 * Type for RPC error code values.
 */
export type RpcErrorCodeValue = (typeof RpcErrorCode)[keyof typeof RpcErrorCode];

/**
 * Check if an error code is an LLM-related error.
 */
export function isLlmError(code: number): boolean {
  return code >= -32019 && code <= -32010;
}

/**
 * Get a user-friendly message for an LLM error code.
 */
export function getLlmErrorMessage(code: number): string {
  switch (code) {
    case RpcErrorCode.LLM_QUOTA_EXCEEDED:
      return "API quota exceeded. Please check your plan and billing details.";
    case RpcErrorCode.LLM_RATE_LIMIT:
      return "Rate limit exceeded. Please wait and try again.";
    case RpcErrorCode.LLM_AUTH_ERROR:
      return "API authentication failed. Please check your API key.";
    case RpcErrorCode.LLM_CONNECTION_ERROR:
      return "Failed to connect to the API. Please check your internet connection.";
    case RpcErrorCode.LLM_MODEL_NOT_FOUND:
      return "The requested model was not found. Please verify the model name.";
    case RpcErrorCode.LLM_INVALID_REQUEST:
      return "Invalid request to the API.";
    case RpcErrorCode.LLM_ERROR:
      return "An error occurred with the LLM service.";
    default:
      return "An unknown error occurred.";
  }
}

// =============================================================================
// RPC Client Interfaces
// =============================================================================

/**
 * Base interface for JSON-RPC clients.
 *
 * Provides the fundamental operations for making RPC calls:
 * - call(): Make a request and wait for a response
 * - notify(): Send a one-way message (no response expected)
 *
 * Implementations must handle request/response correlation,
 * serialization, and transport.
 */
export interface RpcClient {
  /**
   * Makes an RPC call and returns the result.
   *
   * @param method - The method name to call
   * @param params - Optional parameters for the method
   * @returns Promise resolving to the method result
   * @throws {JsonRpcError} If the RPC call returns an error
   */
  call(method: string, params?: unknown): Promise<unknown>;

  /**
   * Sends a notification (fire-and-forget).
   *
   * Notifications do not receive responses, so this method
   * returns void rather than a Promise.
   *
   * @param method - The method name to call
   * @param params - Optional parameters for the method
   */
  notify(method: string, params?: unknown): void;
}

/**
 * Extended RPC client interface with streaming and lifecycle support.
 *
 * Adds capabilities beyond basic RPC calls:
 * - callStream(): Stream multiple responses from a single request
 * - ping(): Health check to verify server connectivity
 * - close(): Clean shutdown of the client
 *
 * Used by StdioRpcClient for full-featured RPC communication.
 */
export interface StreamingRpcClient extends RpcClient {
  /**
   * Makes a streaming RPC call that yields multiple responses.
   *
   * Use for methods that return a stream of events rather than
   * a single result (e.g., run_task, subscribe_events).
   *
   * @param method - The method name to call
   * @param params - Optional parameters for the method
   * @yields Each response from the streaming method
   */
  callStream(method: string, params?: unknown): AsyncGenerator<unknown, void, unknown>;

  /**
   * Checks if the server is responsive.
   *
   * @returns Promise resolving to true if server responds, false otherwise
   */
  ping(): Promise<boolean>;

  /**
   * Closes the client and releases resources.
   *
   * After calling close(), the client cannot be used for further calls.
   */
  close(): void;
}

/**
 * Interface for RPC service implementations (server-side).
 *
 * Used to define handlers for incoming RPC requests.
 */
export interface RpcService {
  /**
   * Handles an incoming RPC request.
   *
   * @param method - The method name being called
   * @param params - Parameters passed to the method
   * @returns Promise resolving to the method result
   */
  handle(method: string, params?: unknown): Promise<unknown>;
}

// =============================================================================
// Task Execution Types
// =============================================================================

/**
 * The phases of task execution.
 *
 * Tasks progress through these phases in order:
 * 1. **init**: Initialization and setup progress
 * 2. **recon**: Reconnaissance and threat modeling
 * 3. **exploit**: Active security testing
 * 4. **supervising**: Supervisor mode execution (supervisor mode only)
 * 5. **done**: Task completion
 * 6. **error**: Error occurred during execution
 */
export type TaskPhase = "init" | "recon" | "exploit" | "supervising" | "done" | "error";

/**
 * Parameters for running a security testing task.
 *
 * @property prompt - The security testing task description
 *                    Example: "Find SQL injection vulnerabilities in the login form"
 * @property target - The target URL to test
 *                    Example: "http://vulnerable-app.com"
 * @property openapi_spec - Optional OpenAPI/Swagger specification for the target API
 * @property knowledge_base - Optional additional knowledge to inject into the agent
 * @property mode - Execution mode:
 *                  - "yolo": Autonomous execution without human intervention
 *                  - "safe": Conservative execution with minimal impact
 *                  - "supervisor": Step-by-step execution with approval workflow
 */
export interface RunTaskParams {
  prompt: string;
  target: string;
  openapi_spec?: unknown;
  knowledge_base?: string;
  mode?: "yolo" | "safe" | "supervisor";
  /** LLM provider to use (openai, anthropic, gemini, bedrock, openrouter, local) */
  provider?: string;
  /** Model name to use (overrides default for provider) */
  model?: string;
}

/**
 * Event emitted during task execution.
 *
 * Different phases have different data structures:
 * - **recon**: data contains threat model information
 * - **exploit**: data contains tool calls and results
 * - **done**: includes mode, target, and optional specs
 *
 * @property phase - The current phase of execution
 * @property data - Phase-specific data (recon/exploit phases)
 * @property mode - The execution mode used (done phase only)
 * @property target - The target URL tested (done phase only)
 * @property openapi_spec - OpenAPI spec if provided (done phase only)
 * @property knowledge_base - Knowledge base if provided (done phase only)
 */
export interface TaskEvent {
  phase: TaskPhase;
  data?: unknown;
  mode?: string;
  target?: string;
  openapi_spec?: unknown;
  knowledge_base?: string;
}

/**
 * Response from the ping RPC method.
 *
 * Used to verify the server is responsive and healthy.
 */
export interface PingResponse {
  status: "ok";
}

// =============================================================================
// Agent Event Types
// =============================================================================

/**
 * All possible event types emitted by agents.
 *
 * Events are categorized by their source and purpose:
 *
 * **Agent Lifecycle:**
 * - agent_start: Agent begins processing a task
 * - agent_end: Agent completes a task (with confidence score)
 * - agent_error: Agent encounters an unrecoverable error
 *
 * **Agent Reasoning:**
 * - agent_thought: Agent's internal reasoning/planning
 * - agent_routed: Router agent selected a specialized agent
 *
 * **Tool Execution:**
 * - tool_call_start: Tool invocation begins
 * - tool_call_end: Tool invocation completes (with result)
 *
 * **Approval Workflow:**
 * - approval_required: Tool needs user approval before execution
 * - approval_response: User's approval decision
 *
 * **Control Flow:**
 * - workflow_interrupted: User or system interrupted execution
 *
 * **Task Management:**
 * - task_created, task_expanded, task_status_changed
 * - confidence_update, validation_result
 *
 * **Logging:**
 * - execution_record: Detailed execution trace
 * - log_message: General log output
 */
export type EventType =
  | "agent_start"
  | "agent_end"
  | "agent_error"
  | "agent_thought"
  | "agent_routed"
  | "tool_call_start"
  | "tool_call_end"
  | "approval_required"
  | "approval_response"
  | "workflow_interrupted"
  | "task_created"
  | "task_expanded"
  | "task_status_changed"
  | "confidence_update"
  | "validation_result"
  | "execution_record"
  | "log_message";

/**
 * Base interface for all agent events.
 *
 * Every event from the Python backend includes these common fields
 * for identification and correlation.
 *
 * @property type - The type of event (discriminator for event data)
 * @property timestamp - ISO 8601 timestamp when the event occurred
 * @property session_id - Unique identifier for the execution session
 * @property agent_name - Name of the agent that generated the event
 * @property task_id - ID of the task being processed
 * @property data - Type-specific event data (see individual data interfaces)
 */
export interface AgentEvent {
  type: EventType;
  timestamp: string;
  session_id: string;
  agent_name?: string;
  task_id?: string;
  data: Record<string, unknown>;
}

// =============================================================================
// Event Data Types
// =============================================================================

/**
 * Data for agent_start events.
 *
 * Emitted when an agent begins processing a task.
 *
 * @property task - The task description being processed
 * @property task_id - Unique identifier for this task
 * @property depth - Recursion depth in ADaPT algorithm (0 = root)
 * @property parent_task_id - ID of parent task if this is a subtask
 */
export interface AgentStartData {
  task: string;
  task_id?: string;
  depth: number;
  parent_task_id?: string;
}

/**
 * Data for agent_end events.
 *
 * Emitted when an agent completes a task. Includes confidence score
 * and summary of the execution.
 *
 * @property task - The task that was processed
 * @property task_id - Unique identifier for this task
 * @property confidence_score - How confident the agent is in completion (0.0-1.0)
 * @property notes - Summary notes about the execution
 * @property thought_summary - Condensed version of agent's reasoning
 * @property attempts_count - Number of attempts made
 * @property attempts - Detailed record of each attempt
 */
export interface AgentEndData {
  task: string;
  task_id?: string;
  confidence_score: number;
  notes?: string;
  thought_summary?: string;
  attempts_count: number;
  attempts: Record<string, unknown>[];
}

/**
 * Data for agent_error events.
 *
 * Emitted when an agent encounters an unrecoverable error.
 *
 * @property task - The task that failed
 * @property task_id - Unique identifier for this task
 * @property error_type - Classification of the error
 * @property error_message - Human-readable error description
 * @property partial_reasoning - Any reasoning completed before the error
 */
export interface AgentErrorData {
  task: string;
  task_id?: string;
  error_type: string;
  error_message: string;
  partial_reasoning?: string;
}

/**
 * Data for agent_thought events.
 *
 * Emitted when an agent has an internal reasoning step.
 *
 * @property thought - The full reasoning text
 * @property summary - Condensed version of the thought
 */
export interface AgentThoughtData {
  thought: string;
  summary?: string;
}

/**
 * Data for agent_routed events.
 *
 * Emitted when the router agent selects a specialized agent.
 *
 * @property task - The task being routed
 * @property selected_agent - Name of the agent selected
 * @property reasoning - Why this agent was chosen
 * @property available_agents - List of agents that were considered
 */
export interface AgentRoutedData {
  task: string;
  selected_agent: string;
  reasoning: string;
  available_agents: string[];
}

/**
 * Data for tool_call_start events.
 *
 * Emitted when a tool invocation begins.
 *
 * @property tool_name - Name of the tool being called
 * @property tool_call_id - Unique identifier for this tool call
 * @property args - JSON string of the arguments passed to the tool
 */
export interface ToolCallStartData {
  tool_name: string;
  tool_call_id?: string;
  args: string;
}

/**
 * Data for tool_call_end events.
 *
 * Emitted when a tool invocation completes.
 *
 * @property tool_name - Name of the tool that was called
 * @property tool_call_id - Unique identifier for this tool call
 * @property success - Whether the tool call succeeded
 * @property result - The result returned by the tool (on success)
 * @property error - Error message (on failure)
 * @property duration_ms - How long the tool call took in milliseconds
 */
export interface ToolCallEndData {
  tool_name: string;
  tool_call_id?: string;
  success: boolean;
  result: string;
  error?: string;
  duration_ms?: number;
}

/**
 * Data for approval_required events.
 *
 * Emitted when a tool call requires user approval before execution.
 * Only emitted when approval mode is enabled.
 *
 * @property request_id - Unique identifier for this approval request
 * @property tool_name - Name of the tool awaiting approval
 * @property tool_args - Arguments that will be passed to the tool
 * @property description - Human-readable description of what the tool will do
 */
export interface ApprovalRequiredData {
  request_id: string;
  tool_name: string;
  tool_args: Record<string, unknown>;
  description: string;
}

/**
 * Data for approval_response events.
 *
 * Emitted when the user responds to an approval request.
 *
 * @property request_id - The approval request being responded to
 * @property approved - Whether the user approved the tool call
 * @property modified_args - Optional modified arguments to use instead
 */
export interface ApprovalResponseData {
  request_id: string;
  approved: boolean;
  modified_args?: Record<string, unknown>;
}

/**
 * Data for workflow_interrupted events.
 *
 * Emitted when the user or system interrupts execution.
 *
 * @property reason - Why the workflow was interrupted
 */
export interface WorkflowInterruptedData {
  reason: string;
}

/**
 * Data for log_message events.
 *
 * General logging output from the agent system.
 *
 * @property message - The log message content
 * @property level - Severity level of the message
 * @property source - Component that generated the message
 */
export interface LogMessageData {
  message: string;
  level: "debug" | "info" | "warning" | "error";
  source?: string;
}

// =============================================================================
// Component Health Types
// =============================================================================

/**
 * Possible states for infrastructure components.
 *
 * Components progress through these states during their lifecycle:
 * 1. not_initialized → initializing → ready
 * 2. ready → unhealthy (on health check failure)
 * 3. ready → stopped (on graceful shutdown)
 * 4. Any state → error (on unrecoverable failure)
 */
export type ComponentStatus =
  | "not_initialized"
  | "initializing"
  | "ready"
  | "unhealthy"
  | "stopped"
  | "error";

/**
 * Result of a component health check.
 *
 * Returned by health_* RPC methods to report component status.
 *
 * @property component - Name of the component (docker, rag, config, etc.)
 * @property healthy - Whether the component is functioning correctly
 * @property status - Current lifecycle state of the component
 * @property message - Human-readable status message
 * @property latency_ms - Response time for health check (if applicable)
 * @property details - Additional component-specific information
 */
export interface HealthResult {
  component: string;
  healthy: boolean;
  status: ComponentStatus;
  message: string;
  latency_ms?: number;
  details: Record<string, unknown>;
}

/**
 * Result of checking all components at once.
 *
 * Returned by health_all RPC method.
 *
 * @property overall_healthy - True only if ALL components are healthy
 * @property components - Individual health results for each component
 * @property timestamp - ISO 8601 timestamp of the health check
 */
export interface AllHealthResult {
  overall_healthy: boolean;
  components: HealthResult[];
  timestamp: string;
}

/**
 * Result of component initialization.
 *
 * Returned by init_* RPC methods to report initialization status.
 *
 * @property success - Whether initialization succeeded
 * @property component - Name of the component initialized
 * @property status - Current state after initialization
 * @property message - Human-readable result message
 * @property details - Additional initialization details
 */
export interface InitResult {
  success: boolean;
  component: string;
  status: ComponentStatus;
  message: string;
  details: Record<string, unknown>;
}

/**
 * Result of initializing all components at once.
 *
 * Returned by init_all RPC method to report initialization status of all components.
 *
 * @property overall_success - True only if ALL components initialized successfully
 * @property components - Individual initialization results for each component
 * @property failed_components - Names of components that failed to initialize
 * @property timestamp - ISO 8601 timestamp of the initialization
 */
export interface AllInitResult {
  overall_success: boolean;
  components: InitResult[];
  failed_components: string[];
  timestamp: string;
}

// =============================================================================
// Control Types
// =============================================================================

/**
 * Parameters for the interrupt RPC method.
 *
 * @property session_id - ID of the session to interrupt
 * @property reason - Optional reason for the interruption
 */
export interface InterruptParams {
  session_id: string;
  reason?: string;
}

/**
 * Parameters for the approve RPC method.
 *
 * @property request_id - ID of the approval request to respond to
 * @property approved - Whether to approve the tool call
 * @property modified_args - Optional modified arguments to use
 */
export interface ApproveParams {
  request_id: string;
  approved: boolean;
  modified_args?: Record<string, unknown>;
}

/**
 * Result of enabling/disabling approval mode.
 *
 * @property status - "enabled" or "disabled"
 * @property approval_mode - Current state of approval mode
 */
export interface ApprovalModeResult {
  status: "enabled" | "disabled";
  approval_mode: boolean;
}
