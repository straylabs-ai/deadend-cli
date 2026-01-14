import { Box, Text } from "ink";
import type { InitResult } from "../types/rpc.ts";
import { LoadingSpinner } from "./LoadingSpinner.tsx";

export type TaskPhase = "init" | "recon" | "exploit" | "done" | "error";

export interface StatusNotification {
  id: string;
  type: "info" | "warning" | "error";
  message: string;
}

export interface StatusAreaProps {
  /** Component initialization results */
  componentResults?: InitResult[];
  /** Current task phase (if running) */
  taskPhase?: TaskPhase | null;
  /** Current task target */
  taskTarget?: string | null;
  /** Whether a task is currently running */
  isRunning: boolean;
  /** System notifications */
  notifications?: StatusNotification[];
  /** Whether to show component status (collapsed after init) */
  showComponents?: boolean;
}

const phaseLabels: Record<TaskPhase, string> = {
  init: "Initializing",
  recon: "Reconnaissance",
  exploit: "Exploitation",
  done: "Completed",
  error: "Error",
};

const phaseColors: Record<TaskPhase, string> = {
  init: "cyan",
  recon: "magenta",
  exploit: "red",
  done: "green",
  error: "red",
};

export function StatusArea({
  componentResults = [],
  taskPhase,
  taskTarget,
  isRunning,
  notifications = [],
  showComponents = false,
}: StatusAreaProps) {
  const hasContent = showComponents || isRunning || notifications.length > 0;

  if (!hasContent) {
    return null;
  }

  return (
    <Box flexDirection="column" marginBottom={1}>
      {/* Component status (shown during init or when expanded) */}
      {showComponents && componentResults.length > 0 && (
        <Box flexDirection="column" marginBottom={1}>
          {componentResults.map((result) => (
            <Box key={result.component}>
              <Text color={result.success ? "green" : "red"}>
                {result.success ? "✓" : "✗"}
              </Text>
              <Text color="white"> {result.component}</Text>
              <Text color="gray" dimColor>
                {" "}
                - {result.message}
              </Text>
            </Box>
          ))}
        </Box>
      )}

      {/* Current task status */}
      {isRunning && taskPhase && (
        <Box marginBottom={1}>
          <LoadingSpinner
            text={`${phaseLabels[taskPhase]}${taskTarget ? ` (${taskTarget})` : ""}`}
            color={phaseColors[taskPhase]}
          />
        </Box>
      )}

      {/* Notifications */}
      {notifications.map((notification) => {
        const colors: Record<string, string> = {
          info: "blue",
          warning: "yellow",
          error: "red",
        };
        const icons: Record<string, string> = {
          info: "ℹ",
          warning: "⚠",
          error: "✗",
        };
        return (
          <Box key={notification.id}>
            <Text color={colors[notification.type]}>
              {icons[notification.type]} {notification.message}
            </Text>
          </Box>
        );
      })}
    </Box>
  );
}
