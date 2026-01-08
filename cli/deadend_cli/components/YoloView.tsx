import { Box, Text, useInput } from "ink";
import { useState, useEffect, useCallback } from "react";
import type { DeadEndRpcClient, DoneEvent } from "../lib/deadend-rpc-client.ts";
import type { AgentEvent } from "../types/rpc.ts";
import { EventStreamView } from "./EventStreamView.tsx";
import { LoadingSpinner } from "./LoadingSpinner.tsx";

export type YoloPhase = "recon" | "exploit" | "done" | "error";

export interface YoloViewProps {
  /** Target URL to test */
  target: string;
  /** Task/prompt to execute */
  task: string;
  /** RPC client instance */
  rpcClient: DeadEndRpcClient;
  /** Callback when execution completes */
  onComplete?: (result: DoneEvent) => void;
  /** Callback when user cancels */
  onCancel?: () => void;
}

export function YoloView({
  target,
  task,
  rpcClient,
  onComplete,
  onCancel,
}: YoloViewProps) {
  const [phase, setPhase] = useState<YoloPhase>("recon");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DoneEvent | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [hasStarted, setHasStarted] = useState(false);

  // Handle keyboard input
  useInput((input, key) => {
    // Ctrl+C or Escape to cancel
    if ((key.ctrl && input === "c") || key.escape) {
      handleCancel();
    }
    // Enter to continue after completion
    if (key.return && phase === "done") {
      onComplete?.(result!);
    }
  });

  const handleCancel = useCallback(async () => {
    if (isRunning) {
      try {
        await rpcClient.interrupt("current", "User cancelled");
      } catch {
        // Ignore interrupt errors
      }
    }
    onCancel?.();
  }, [isRunning, rpcClient, onCancel]);

  const addEvent = useCallback((event: AgentEvent) => {
    setEvents((prev) => [...prev, event]);
  }, []);

  // Start the YOLO workflow after health check passes
  const startWorkflow = useCallback(async () => {
    setIsRunning(true);
    setPhase("recon");
    setEvents([]);

    try {
      // Run the task with streaming events
      for await (const taskEvent of rpcClient.runTask({
        prompt: task,
        target: target,
        mode: "yolo",
      })) {
        // Update phase based on task event
        if (taskEvent.phase === "recon") {
          setPhase("recon");
          // Convert task event data to agent event format for display
          if (taskEvent.data) {
            addEvent({
              type: "log_message",
              timestamp: new Date().toISOString(),
              session_id: "yolo",
              data: {
                message: typeof taskEvent.data === "string"
                  ? taskEvent.data
                  : JSON.stringify(taskEvent.data),
                level: "info",
              },
            });
          }
        } else if (taskEvent.phase === "exploit") {
          setPhase("exploit");
          if (taskEvent.data) {
            addEvent({
              type: "log_message",
              timestamp: new Date().toISOString(),
              session_id: "yolo",
              data: {
                message: typeof taskEvent.data === "string"
                  ? taskEvent.data
                  : JSON.stringify(taskEvent.data),
                level: "info",
              },
            });
          }
        } else if (taskEvent.phase === "done") {
          setPhase("done");
          setResult(taskEvent as DoneEvent);
        }
      }
    } catch (err) {
      let errorMessage: string;
      if (err instanceof Error) {
        errorMessage = err.message;
      } else if (typeof err === "object" && err !== null) {
        // Handle RPC error objects
        const errObj = err as Record<string, unknown>;
        errorMessage = errObj.message as string || errObj.error as string || JSON.stringify(err);
      } else {
        errorMessage = String(err);
      }
      setError(errorMessage);
      setPhase("error");
    } finally {
      setIsRunning(false);
    }
  }, [rpcClient, task, target, addEvent]);

  // Subscribe to detailed events from the event bus
  useEffect(() => {
    if (phase !== "recon" && phase !== "exploit") {
      return;
    }

    let cancelled = false;

    const subscribeToEvents = async () => {
      try {
        for await (const event of rpcClient.subscribeEvents()) {
          if (cancelled) break;
          addEvent(event);
        }
      } catch {
        // Subscription ended, ignore
      }
    };

    subscribeToEvents();

    return () => {
      cancelled = true;
    };
  }, [phase, rpcClient, addEvent]);

  // Start workflow immediately on mount
  useEffect(() => {
    if (!hasStarted) {
      setHasStarted(true);
      startWorkflow();
    }
  }, [hasStarted, startWorkflow]);

  // Error phase
  if (phase === "error") {
    return (
      <Box flexDirection="column" padding={1}>
        <Box marginBottom={1}>
          <Text color="red" bold>
            YOLO Mode - Error
          </Text>
        </Box>

        <Box marginBottom={1}>
          <Text color="red">{"✗ "}{error}</Text>
        </Box>

        <Box marginTop={2}>
          <Text color="gray">Press Ctrl+C to return</Text>
        </Box>
      </Box>
    );
  }

  // Done phase
  if (phase === "done" && result) {
    return (
      <Box flexDirection="column" padding={1}>
        <Box marginBottom={1}>
          <Text color="green" bold>
            YOLO Mode - Complete
          </Text>
        </Box>

        <Box marginBottom={1}>
          <Text>Target: </Text>
          <Text color="yellow">{result.target}</Text>
        </Box>

        {/* Show all events including permanent results */}
        <EventStreamView events={events} maxVisible={5} showPermanent={true} />

        <Box marginTop={2}>
          <Text color="gray">Press Enter to continue, Ctrl+C to return</Text>
        </Box>
      </Box>
    );
  }

  // Recon or Exploit phase (running)
  const phaseLabel = phase === "recon" ? "Reconnaissance" : "Exploitation";
  const phaseColor = "magenta";

  return (
    <Box flexDirection="column" padding={1}>
      {/* Target info */}
      <Box marginBottom={1}>
        <Text color="magenta">⌬ </Text>
        <Text bold>Target</Text>
        <Text color="yellow">({target})</Text>
      </Box>

      {/* Running indicator */}
      {isRunning && (
        <Box marginBottom={1}>
          <LoadingSpinner text={phaseLabel} color={phaseColor} />
        </Box>
      )}

      {/* Event stream */}
      <Box flexDirection="column" marginTop={1}>
        <EventStreamView events={events} maxVisible={8} showPermanent={false} />
      </Box>

      {/* Footer */}
      <Box marginTop={2}>
        <Text color="gray" dimColor>
          Press Ctrl+C to stop
        </Text>
      </Box>
    </Box>
  );
}
