export interface JsonRpcRequest {
  jsonrpc: "2.0";
  id: number | null;
  method: string;
  params?: unknown;
}

export interface JsonRpcError {
  code: number;
  message: string;
  data?: unknown;
}

export interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: number | null;
  result?: unknown;
  error?: JsonRpcError;
  _streaming?: boolean;
}

export interface InitResult {
  success: boolean;
  component: string;
  status?: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface AllInitResult {
  overall_success: boolean;
  components: InitResult[];
  failed_components: string[];
}

export type AgentEventType =
  | "tool_call_start"
  | "tool_call_end"
  | "agent_thought"
  | "agent_start"
  | "agent_end"
  | "agent_error"
  | "agent_routed"
  | "task_created"
  | "task_expanded"
  | "task_status_changed"
  | "confidence_update"
  | "validation_result"
  | "log_message"
  | "approval_required"
  | "workflow_interrupted";

export interface AgentEvent {
  type: AgentEventType;
  timestamp?: string;
  agent_name?: string;
  data: unknown;
}

export interface TaskEvent {
  phase: "init" | "recon" | "exploit" | "supervising" | "done" | "error";
  data?: unknown;
  status?: string;
  reason?: string;
}

export interface PingResponse {
  status: "ok";
}

export interface InstantiateAgentResult {
  status: string;
  agent_id?: string;
  reason?: string;
}

export interface InterruptAgentResult {
  status: string;
  agent_id?: string;
  reason?: string;
}

export interface AgentTaskSnapshotEntry {
  task_id: string;
  parent_task_id?: string | null;
  task: string;
  status: string;
  depth: number;
  confidence_score?: number | null;
  is_current: boolean;
}

export interface AgentTaskSnapshotResult {
  status: string;
  agent_id?: string;
  session_id?: string;
  target?: string | null;
  root_task_id?: string | null;
  current_task_id?: string | null;
  tasks?: AgentTaskSnapshotEntry[];
  reason?: string;
}

export interface ValidationStrategyConfig {
  name: string;
  pattern?: string | null;
  validation_type?: string | null;
  validation_format?: string | null;
}

export interface GetValidationConfigResult {
  status: string;
  validation_format?: string | null;
  validation_type?: string | null;
  strategies?: ValidationStrategyConfig[];
  preset?: string | null;
  available_presets?: string[];
  reason?: string;
}

export interface SetValidationConfigResult {
  status: string;
  validation_format?: string | null;
  validation_type?: string | null;
  strategies?: ValidationStrategyConfig[];
  reason?: string;
}
