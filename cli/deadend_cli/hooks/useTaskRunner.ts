import { useState, useCallback, useRef, useEffect } from "react";
import type { DeadEndRpcClient } from "../runtime/deadend-rpc-client.ts";
import type { Message } from "../types/message.ts";
import { createMessage, agentEventToMessage } from "../types/message.ts";
import type { TaskPhase } from "../components/StatusArea.tsx";
import { useLlmDefaults } from "./useLlmDefaults.ts";

export type ExecutionMode = "yolo" | "supervisor";

export interface TaskState {
  isRunning: boolean;
  phase: TaskPhase | null;
  target: string | null;
  task: string | null;
  /** Agent ID for the current session */
  agentId: string | null;
  /** Whether the target has been embedded */
  isTargetEmbedded: boolean;
}

export interface UseTaskRunnerOptions {
  /** Callback when a message should be added to chat */
  onMessage: (message: Message) => void;
  /** Callback when task completes */
  onComplete?: () => void;
  /** Callback when task is cancelled */
  onCancel?: () => void;
  /** Callback when an error occurs */
  onError?: (error: string) => void;
}

export interface RunTaskOptions {
  task: string;
  mode: ExecutionMode;
}

export interface SetTargetOptions {
  target: string;
}

export interface UseTaskRunnerReturn {
  /** Current task state */
  taskState: TaskState;
  /** Set target and prepare agent (instantiate + embed) */
  setTarget: (options: SetTargetOptions) => Promise<void>;
  /** Run a task with prompt (requires target to be set first) */
  runTask: (options: RunTaskOptions) => Promise<void>;
  /** Cancel the running task (optionally skip RPC interrupt when already sent, e.g. via Esc) */
  cancel: (options?: { skipRpc?: boolean }) => Promise<void>;
}

/**
 * Helper to extract error message from various error types
 */
function extractErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  
  if (error && typeof error === "object" && "message" in error) {
    const rpcError = error as { message: string; code?: number; data?: unknown };
    let message = rpcError.message;
    
    if (rpcError.code !== undefined) {
      message = `[${rpcError.code}] ${message}`;
    }
    
    if (rpcError.data) {
      const dataStr = typeof rpcError.data === "string" 
        ? rpcError.data 
        : JSON.stringify(rpcError.data);
      if (dataStr && dataStr !== "{}") {
        message += ` - ${dataStr}`;
      }
    }
    
    return message;
  }
  
  return String(error);
}

/**
 * Check if target is already set and ready to use
 */
function isTargetReady(state: TaskState, target: string): boolean {
  return (
    state.target === target &&
    state.isTargetEmbedded === true &&
    state.agentId !== null
  );
}

/**
 * Check if we can reuse existing agent for the same target
 */
function canReuseAgent(state: TaskState, target: string): {
  canReuse: boolean;
  agentId: string | null;
} {
  if (state.target === target && state.agentId) {
    return { canReuse: true, agentId: state.agentId };
  }
  return { canReuse: false, agentId: null };
}

export function useTaskRunner(
  rpcClient: DeadEndRpcClient | null,
  options: UseTaskRunnerOptions
): UseTaskRunnerReturn {
  const { onMessage, onComplete, onCancel, onError } = options;

  // Get provider and model for future uses and calls 
  const { defaults: llmDefaults, isLoading: llmDefaultsLoading }  = useLlmDefaults();
  
  const pendingTargetRef = useRef<string | null>(null);

  const [taskState, setTaskState] = useState<TaskState>({
    isRunning: false,
    phase: null,
    target: null,
    task: null,
    agentId: null,
    isTargetEmbedded: false,
  });

  const cancelledRef = useRef(false);
  const eventSubscriptionRef = useRef<AbortController | null>(null);
  const isEmbeddingRef = useRef(false);

  // ============================================================================
  // Cancel Handler
  // ============================================================================

  const cancel = useCallback(async (options?: { skipRpc?: boolean }) => {
    cancelledRef.current = true;

    // Stop event subscription
    if (eventSubscriptionRef.current) {
      eventSubscriptionRef.current.abort();
      eventSubscriptionRef.current = null;
    }

    // Notify server to interrupt (unless caller already sent interrupt_agent, e.g. Esc)
    if (!options?.skipRpc && rpcClient && taskState.isRunning) {
      try {
        await rpcClient.interrupt("current", "User cancelled");
      } catch {
        // Ignore interrupt errors
      }
    }

    // Update state
    setTaskState((prev) => ({
      ...prev,
      isRunning: false,
      phase: null,
      task: null,
    }));

    onCancel?.();
  }, [rpcClient, taskState.isRunning, onCancel]);

  // ============================================================================
  // Target Setup: Instantiate Agent and Embed Target
  // ============================================================================

  const setTarget = useCallback(
    async ({ target }: SetTargetOptions) => {
      // Validation
      if (!rpcClient) {
        onError?.("RPC client not available");
        return;
      }

      if (llmDefaultsLoading || !llmDefaults) {
        pendingTargetRef.current = target;
        onMessage(createMessage("system", "Loading LLM configuration, will retry...", "info"));
        return;
      }
      // Prevent concurrent operations
      if (isEmbeddingRef.current) {
        onMessage(createMessage("system", "Embedding already in progress, please wait...", "info"));
        return;
      }

      // Check if target is already ready
      if (isTargetReady(taskState, target)) {
        onMessage(createMessage("system", `Target already set and ready: ${target}`, "info"));
        return;
      }

      
      // Initialize state
      cancelledRef.current = false;
      isEmbeddingRef.current = true;

      const { canReuse, agentId: existingAgentId } = canReuseAgent(taskState, target);
      const wasAlreadyEmbedded = taskState.isTargetEmbedded && taskState.target === target;

      setTaskState((prev) => ({
        ...prev,
        isRunning: true,
        phase: "init",
        target,
        agentId: canReuse ? prev.agentId : null,
        isTargetEmbedded: canReuse ? prev.isTargetEmbedded : false,
      }));

      pendingTargetRef.current = null;
      try {
        let providerName: string | null;
        let modelName: string;
        if (llmDefaults) {
          providerName = llmDefaults.provider;
          if (typeof llmDefaults.model === "string") {
              modelName = llmDefaults.model
          }
          else{
            modelName = ""
          }
        }
        else {
          providerName = "";
          modelName = "";
        }


        // If we still don't have provider, error out
        if (!providerName) {
          onError?.("No LLM provider configured. Please configure a provider first.");
          return;
        }

        // Step 1: Get or create agent
        const agentId = await getOrCreateAgent(
          rpcClient,
          target,
          existingAgentId,
          providerName,
          modelName,
          onMessage
        );

        setTaskState((prev) => ({ ...prev, agentId }));

        // Step 2: Embed target (skip if already embedded for this target)
        if (wasAlreadyEmbedded) {
          onMessage(createMessage("system", `Target already embedded: ${target}`, "info"));
          setTaskState((prev) => ({
            ...prev,
            isRunning: false,
            phase: null,
            isTargetEmbedded: true,
          }));
          return;
        }

        await embedTarget(rpcClient, agentId, target, cancelledRef, onMessage);

        // Success
        if (!cancelledRef.current) {
          setTaskState((prev) => ({
            ...prev,
            isRunning: false,
            phase: null,
            isTargetEmbedded: true,
          }));
          onMessage(createMessage("system", `Target ready: ${target}`, "info"));
        }
      } catch (error) {
        if (!cancelledRef.current) {
          const errorMessage = extractErrorMessage(error);
          onMessage(createMessage("system", `Error: ${errorMessage}`, "error"));
          onError?.(errorMessage);
          setTaskState((prev) => ({
            ...prev,
            isRunning: false,
            phase: "error",
          }));
        }
      } finally {
        isEmbeddingRef.current = false;
      }
    },
    [rpcClient, onMessage, onError, taskState, llmDefaults]
  );


  useEffect(() => {
      if (pendingTargetRef.current && !llmDefaultsLoading && llmDefaults) {
        const target = pendingTargetRef.current
        pendingTargetRef.current = null
        setTarget({target}).catch(() => {});
      }
  }, [llmDefaults, llmDefaultsLoading, setTarget])

  // ============================================================================
  // Task Execution: Run Agent with Prompt
  // ============================================================================

  const runTask = useCallback(
    async ({ task, mode: _mode }: RunTaskOptions) => {
      // Validation
      if (!rpcClient) {
        onError?.("RPC client not available");
        return;
      }

      if (!taskState.agentId) {
        onError?.("No agent initialized. Set a target first.");
        return;
      }

      if (!taskState.isTargetEmbedded) {
        onError?.("Target not yet embedded. Wait for target setup to complete.");
        return;
      }

      // Initialize
      cancelledRef.current = false;
      setTaskState((prev) => ({
        ...prev,
        isRunning: true,
        phase: "recon",
        task,
      }));

      // Start event subscription
      eventSubscriptionRef.current = new AbortController();
      startEventSubscription(
        rpcClient,
        cancelledRef,
        eventSubscriptionRef,
        onMessage
      );

      try {
        // Execute task
        await executeTask(
          rpcClient,
          taskState.agentId,
          task,
          _mode,
          cancelledRef,
          setTaskState,
          onMessage,
          onError
        );

        // Success
        if (!cancelledRef.current) {
          setTaskState((prev) => ({ ...prev, phase: "done" }));
          onMessage(
            createMessage("system", `Task completed. Target: ${taskState.target}`, "info")
          );
          onComplete?.();
        }
      } catch (error) {
        if (!cancelledRef.current) {
          const errorMessage = extractErrorMessage(error);
          onMessage(createMessage("system", `Error: ${errorMessage}`, "error"));
          onError?.(errorMessage);
        }
      } finally {
        // Cleanup
        if (eventSubscriptionRef.current) {
          eventSubscriptionRef.current.abort();
          eventSubscriptionRef.current = null;
        }

        if (!cancelledRef.current) {
          setTaskState((prev) => ({
            ...prev,
            isRunning: false,
            phase: null,
            task: null,
          }));
        }
      }
    },
    [rpcClient, taskState.agentId, taskState.isTargetEmbedded, taskState.target, onMessage, onComplete, onError]
  );

  return {
    taskState,
    setTarget,
    runTask,
    cancel,
  };
}

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Get existing agent or create a new one
 */
async function getOrCreateAgent(
  rpcClient: DeadEndRpcClient,
  target: string,
  existingAgentId: string | null,
  providerName: string,
  modelName: string,
  onMessage: (message: Message) => void
): Promise<string> {
  if (existingAgentId) {
    onMessage(createMessage("system", `Reusing existing agent: ${existingAgentId}`, "event_log"));
    return existingAgentId;
  }

  onMessage(createMessage("system", "Initializing agent...", "event_log"));

  const result = await rpcClient.instantiateAgent(
    target,
    providerName,
    modelName
  );
  
  if (result.status !== "ok" || !result.agent_id) {
    const reason = (result as { reason?: string }).reason || "Unknown error";
    throw new Error(`Failed to instantiate agent: ${reason}`);
  }

  onMessage(createMessage("system", `Agent created: ${result.agent_id}`, "event_log"));
  return result.agent_id;
}

/**
 * Embed target code into vector database
 */
async function embedTarget(
  rpcClient: DeadEndRpcClient,
  agentId: string,
  target: string,
  cancelledRef: React.RefObject<boolean>,
  onMessage: (message: Message) => void
): Promise<void> {
  const { generator, abort } = rpcClient.embedTarget(agentId, target);

  try {
    for await (const event of generator) {
      if (cancelledRef.current) {
        abort();
        break;
      }

      if (event.data) {
        const dataObj = event.data as { message?: string };
        if (dataObj.message) {
          onMessage(createMessage("system", dataObj.message, "event_log"));
        }
      }
    }
  } catch (error) {
    if (cancelledRef.current) {
      abort();
    }
    throw error;
  }
}

/**
 * Start event subscription for real-time agent events
 */
function startEventSubscription(
  rpcClient: DeadEndRpcClient,
  cancelledRef: React.RefObject<boolean>,
  eventSubscriptionRef: React.RefObject<AbortController | null>,
  onMessage: (message: Message) => void
): void {
  const { generator, abort } = rpcClient.subscribeEvents();

  const subscribe = async () => {
    try {
      for await (const event of generator) {
        if (cancelledRef.current || eventSubscriptionRef.current?.signal.aborted) {
          abort();
          break;
        }
        const message = agentEventToMessage(event);
        onMessage(message);
      }
    } catch {
      // Subscription ended, ignore
    }
  };

  subscribe();
}

/**
 * Execute task with agent (recon + exploit phases for yolo, supervising + recon for supervisor)
 */
async function executeTask(
  rpcClient: DeadEndRpcClient,
  agentId: string,
  task: string,
  mode: ExecutionMode,
  cancelledRef: React.RefObject<boolean>,
  setTaskState: React.Dispatch<React.SetStateAction<TaskState>>,
  onMessage: (message: Message) => void,
  onError?: (error: string) => void
): Promise<void> {
  // Route to appropriate method based on mode
  const { generator, abort } = mode === "supervisor"
    ? rpcClient.runAgentSupervisor(agentId, task)
    : rpcClient.runAgentRecursive(agentId, task);

  try {
    for await (const event of generator) {
      if (cancelledRef.current) {
        abort();
        break;
      }

      // Update phase based on event
      switch (event.phase) {
        case "recon":
          setTaskState((prev) => ({ ...prev, phase: "recon" }));
          break;

        case "exploit":
          setTaskState((prev) => ({ ...prev, phase: "exploit" }));
          break;

        case "supervising":
          setTaskState((prev) => ({ ...prev, phase: "supervising" }));
          break;

        case "error": {
          const errorData = event.data as { message: string; error_type: string };
          const errorMessage = `${errorData.error_type}: ${errorData.message}`;
          onMessage(createMessage("system", errorMessage, "error"));
          setTaskState((prev) => ({ ...prev, phase: "error" }));
          onError?.(errorMessage);
          break;
        }
      }
    }
  } finally {
    if (cancelledRef.current) {
      abort();
    }
  }
}
