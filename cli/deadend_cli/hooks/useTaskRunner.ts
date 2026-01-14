import { useState, useCallback, useRef } from "react";
import type { DeadEndRpcClient, DoneEvent } from "../lib/deadend-rpc-client.ts";
import type { Message } from "../types/message.ts";
import type { AgentEvent } from "../types/rpc.ts";
import { createMessage, agentEventToMessage } from "../types/message.ts";
import type { TaskPhase } from "../components/StatusArea.tsx";

export type ExecutionMode = "yolo" | "supervisor";

export interface TaskState {
  isRunning: boolean;
  phase: TaskPhase | null;
  target: string | null;
  task: string | null;
}

export interface UseTaskRunnerOptions {
  /** Callback when a message should be added to chat */
  onMessage: (message: Message) => void;
  /** Callback when task completes */
  onComplete?: (result: DoneEvent) => void;
  /** Callback when task is cancelled */
  onCancel?: () => void;
  /** Callback when an error occurs */
  onError?: (error: string) => void;
}

export interface RunTaskOptions {
  target: string;
  task: string;
  mode: ExecutionMode;
  /** LLM provider to use */
  provider?: string;
  /** Model name to use */
  model?: string;
}

export interface UseTaskRunnerReturn {
  /** Current task state */
  taskState: TaskState;
  /** Start a task */
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

    setTaskState({
      isRunning: false,
      phase: null,
      target: null,
      task: null,
    });

    onCancel?.();
  }, [rpcClient, taskState.isRunning, onCancel]);

  const runTask = useCallback(
    async ({ target, task, mode, provider, model }: RunTaskOptions) => {
      if (!rpcClient) {
        onError?.("RPC client not available");
        return;
      }

      cancelledRef.current = false;

      setTaskState({
        isRunning: true,
        phase: "init",
        target,
        task,
      });

      // Start event subscription for detailed events
      eventSubscriptionRef.current = new AbortController();
      const subscribeToEvents = async () => {
        try {
          for await (const event of rpcClient.subscribeEvents()) {
            if (cancelledRef.current || eventSubscriptionRef.current?.signal.aborted) {
              break;
            }
            // Convert event to message and add to chat
            const message = agentEventToMessage(event);
            onMessage(message);
          }
        } catch {
          // Subscription ended, ignore
        }
      };
      subscribeToEvents();

      try {
        // Run the task with streaming events
        for await (const taskEvent of rpcClient.runTask({
          prompt: task,
          target: target,
          mode: mode,
          provider: provider,
          model: model,
        })) {
          if (cancelledRef.current) {
            break;
          }

          // Update phase based on task event
          if (taskEvent.phase === "init") {
            setTaskState((prev) => ({ ...prev, phase: "init" }));
            // Show init progress
            if (taskEvent.data) {
              const dataObj = taskEvent.data as { message?: string };
              const message = createMessage(
                "system",
                dataObj.message ?? "Initializing...",
                "event_log"
              );
              onMessage(message);
            }
          } else if (taskEvent.phase === "recon") {
            setTaskState((prev) => ({ ...prev, phase: "recon" }));
          } else if (taskEvent.phase === "exploit") {
            setTaskState((prev) => ({ ...prev, phase: "exploit" }));
          } else if (taskEvent.phase === "error") {
            const errorData = taskEvent.data as { message: string; error_type: string };
            const errorMessage = createMessage(
              "system",
              `${errorData.error_type}: ${errorData.message}`,
              "error"
            );
            onMessage(errorMessage);
            setTaskState((prev) => ({ ...prev, phase: "error" }));
            onError?.(`${errorData.error_type}: ${errorData.message}`);
          } else if (taskEvent.phase === "done") {
            setTaskState((prev) => ({ ...prev, phase: "done" }));
            const doneMessage = createMessage(
              "system",
              `Task completed. Target: ${(taskEvent as DoneEvent).target}`,
              "info"
            );
            onMessage(doneMessage);
            onComplete?.(taskEvent as DoneEvent);
          }
        }
      } catch (err) {
        if (!cancelledRef.current) {
          const errorMessage =
            err instanceof Error
              ? err.message
              : typeof err === "object" && err !== null
              ? (err as Record<string, unknown>).message as string ||
                JSON.stringify(err)
              : String(err);

          const message = createMessage("system", `Error: ${errorMessage}`, "error");
          onMessage(message);
          onError?.(errorMessage);
        }
      } finally {
        // Cleanup
        if (eventSubscriptionRef.current) {
          eventSubscriptionRef.current.abort();
          eventSubscriptionRef.current = null;
        }

        if (!cancelledRef.current) {
          setTaskState({
            isRunning: false,
            phase: null,
            target: null,
            task: null,
          });
        }
      }
    },
    [rpcClient, onMessage, onComplete, onError]
  );

  return {
    taskState,
    runTask,
    cancel,
  };
}
