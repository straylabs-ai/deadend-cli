import { Box, Text } from "ink";
import type { InitResult } from "../types/rpc.ts";
import { DirectStatusLine } from "./DirectStatusLine.tsx";

export type TaskPhase = "init" | "recon" | "exploit" | "supervising" | "done" | "error";

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
  supervising: "Supervising",
  done: "Completed",
  error: "Error",
};

const phaseColors: Record<TaskPhase, string> = {
  init: "grey",
  recon: "#1a2ca3",
  exploit: "red",
  supervising: "#f2e3bb",
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
  const hasStaticContent = showComponents || notifications.length > 0;
  const hasAnimatedContent = isRunning && taskPhase;

  // Build status text for the direct status line
  const statusText = taskPhase
    ? `${phaseLabels[taskPhase]}${taskTarget ? ` (${taskTarget})` : ""}`
    : "";
  const statusColor = taskPhase ? phaseColors[taskPhase] : "magenta";

  if (!hasStaticContent && !hasAnimatedContent) {
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

      {/* Current task status - uses absolute positioning to last terminal line */}
      {/* This renders to the last terminal line, completely bypassing Ink's render cycle */}
      <DirectStatusLine
        text={statusText}
        color={statusColor}
        isActive={Boolean(hasAnimatedContent)}
        updateInterval={100}
        mode="absolute"
      />

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
