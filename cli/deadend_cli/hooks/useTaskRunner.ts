import { useState, useCallback, useRef } from "react";
import type { DeadEndRpcClient } from "../lib/deadend-rpc-client.ts";
import type { Message } from "../types/message.ts";
import { createMessage, agentEventToMessage } from "../types/message.ts";
import type { TaskPhase } from "../components/StatusArea.tsx";

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
  /** Cancel the running task */
  cancel: () => Promise<void>;
}

export function useTaskRunner(
  rpcClient: DeadEndRpcClient | null,
  options: UseTaskRunnerOptions
): UseTaskRunnerReturn {
  const { onMessage, onComplete, onCancel, onError } = options;

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

  const cancel = useCallback(async () => {
    cancelledRef.current = true;

    // Abort event subscription
    if (eventSubscriptionRef.current) {
      eventSubscriptionRef.current.abort();
      eventSubscriptionRef.current = null;
    }

    // Try to interrupt the task on the server
    if (rpcClient && taskState.isRunning) {
      try {
        await rpcClient.interrupt("current", "User cancelled");
      } catch {
        // Ignore interrupt errors
      }
    }

    setTaskState((prev) => ({
      ...prev,
      isRunning: false,
      phase: null,
      task: null,
    }));

    onCancel?.();
  }, [rpcClient, taskState.isRunning, onCancel]);

  /**
   * Set target: instantiate agent and embed target
   */
  const setTarget = useCallback(
    async ({ target }: SetTargetOptions) => {
      if (!rpcClient) {
        onError?.("RPC client not available");
        return;
      }

      cancelledRef.current = false;

      setTaskState((prev) => ({
        ...prev,
        isRunning: true,
        phase: "init",
        target,
        agentId: null,
        isTargetEmbedded: false,
      }));

      try {
        // Step 1: Instantiate agent
        onMessage(createMessage("system", "Initializing agent...", "event_log"));

        const agentResult = await rpcClient.instantiateAgent(target);
        if (agentResult.status !== "ok" || !agentResult.agent_id) {
          const reason = (agentResult as { reason?: string }).reason || "Unknown error";
          throw new Error(`Failed to instantiate agent: ${reason}`);
        }

        const agentId = agentResult.agent_id;
        setTaskState((prev) => ({ ...prev, agentId }));

        onMessage(createMessage("system", `Agent created: ${agentId}`, "event_log"));

        // Step 2: Embed target (streaming)
        for await (const event of rpcClient.embedTarget(agentId, target)) {
          if (cancelledRef.current) break;

          if (event.data) {
            const dataObj = event.data as { message?: string };
            if (dataObj.message) {
              onMessage(createMessage("system", dataObj.message, "event_log"));
            }
          }
        }

        if (!cancelledRef.current) {
          setTaskState((prev) => ({
            ...prev,
            isRunning: false,
            phase: null,
            isTargetEmbedded: true,
          }));

          onMessage(createMessage("system", `Target ready: ${target}`, "info"));
        }
      } catch (err) {
        if (!cancelledRef.current) {
          // Handle different error types
          let errorMessage: string;
          if (err instanceof Error) {
            errorMessage = err.message;
          } else if (err && typeof err === "object" && "message" in err) {
            // Handle JsonRpcError objects from RPC calls
            const rpcError = err as { message: string; code?: number; data?: unknown };
            errorMessage = rpcError.message;
            // Include error code if available
            if (rpcError.code !== undefined) {
              errorMessage = `[${rpcError.code}] ${errorMessage}`;
            }
            // Include additional error details if available
            if (rpcError.data) {
              const dataStr = typeof rpcError.data === "string" 
                ? rpcError.data 
                : JSON.stringify(rpcError.data);
              if (dataStr && dataStr !== "{}") {
                errorMessage += ` - ${dataStr}`;
              }
            }
          } else {
            errorMessage = String(err);
          }
          onMessage(createMessage("system", `Error: ${errorMessage}`, "error"));
          onError?.(errorMessage);

          setTaskState((prev) => ({
            ...prev,
            isRunning: false,
            phase: "error",
          }));
        }
      }
    },
    [rpcClient, onMessage, onError]
  );

  /**
   * Run task: execute runAgentRecursive with prompt
   */
  const runTask = useCallback(
    async ({ task, mode }: RunTaskOptions) => {
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

      cancelledRef.current = false;

      setTaskState((prev) => ({
        ...prev,
        isRunning: true,
        phase: "recon",
        task,
      }));

      // Start event subscription for detailed events
      eventSubscriptionRef.current = new AbortController();
      const subscribeToEvents = async () => {
        try {
          for await (const event of rpcClient.subscribeEvents()) {
            if (cancelledRef.current || eventSubscriptionRef.current?.signal.aborted) {
              break;
            }
            const message = agentEventToMessage(event);
            onMessage(message);
          }
        } catch {
          // Subscription ended, ignore
        }
      };
      subscribeToEvents();

      try {
        // Run agent recursive (recon + exploit phases)
        for await (const taskEvent of rpcClient.runAgentRecursive(
          taskState.agentId,
          task
        )) {
          if (cancelledRef.current) break;

          if (taskEvent.phase === "recon") {
            setTaskState((prev) => ({ ...prev, phase: "recon" }));
          } else if (taskEvent.phase === "exploit") {
            setTaskState((prev) => ({ ...prev, phase: "exploit" }));
          } else if (taskEvent.phase === "error") {
            const errorData = taskEvent.data as { message: string; error_type: string };
            onMessage(
              createMessage(
                "system",
                `${errorData.error_type}: ${errorData.message}`,
                "error"
              )
            );
            setTaskState((prev) => ({ ...prev, phase: "error" }));
            onError?.(`${errorData.error_type}: ${errorData.message}`);
          }
        }

        // Task completed
        if (!cancelledRef.current) {
          setTaskState((prev) => ({ ...prev, phase: "done" }));
          onMessage(
            createMessage("system", `Task completed. Target: ${taskState.target}`, "info")
          );
          onComplete?.();
        }
      } catch (err) {
        if (!cancelledRef.current) {
          const errorMessage =
            err instanceof Error
              ? err.message
              : typeof err === "object" && err !== null
              ? (err as Record<string, unknown>).message as string || JSON.stringify(err)
              : String(err);

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
