import { Box, Text } from "ink";
import type { InitResult } from "../types/rpc.ts";
import { DirectStatusLine } from "./DirectStatusLine.tsx";
import { BlinkDot } from "./BlinkDot.tsx";
import { colors } from "./colors.ts";

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
  init: colors.phase.init,
  recon: colors.phase.recon,
  exploit: colors.phase.exploit,
  supervising: colors.phase.supervising,
  done: colors.phase.done,
  error: colors.phase.error,
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

  const statusText = taskPhase
    ? `${phaseLabels[taskPhase]}${taskTarget ? ` \u2014 ${taskTarget}` : ""}`
    : "";
  const statusColor = taskPhase ? phaseColors[taskPhase] : "magenta";

  if (!hasStaticContent && !hasAnimatedContent) {
    return null;
  }

  return (
    <Box flexDirection="column" marginBottom={1}>
      {/* Component health grid */}
      {showComponents && componentResults.length > 0 && (
        <Box flexDirection="column" marginBottom={1}>
          {componentResults.map((result) => (
            <Box key={result.component} flexDirection="row">
              <Box width={2} flexShrink={0}>
                <BlinkDot
                  color={result.success ? colors.status.success : colors.status.error}
                />
              </Box>
              <Text> {result.component}</Text>
              <Text dimColor> {result.message}</Text>
            </Box>
          ))}
        </Box>
      )}

      {/* Animated phase indicator */}
      <DirectStatusLine
        text={statusText}
        color={statusColor}
        isActive={Boolean(hasAnimatedContent)}
        updateInterval={100}
        mode="absolute"
      />

      {/* Notifications */}
      {notifications.map((n) => {
        const nColors: Record<string, string> = {
          info: colors.status.info,
          warning: colors.status.warning,
          error: colors.status.error,
        };
        const icons: Record<string, string> = {
          info: "\u25CF",  // ●
          warning: "\u26A0", // ⚠
          error: "\u2717",  // ✗
        };
        return (
          <Box key={n.id} flexDirection="row">
            <Box width={2} flexShrink={0}>
              <Text color={nColors[n.type]}>{icons[n.type]}</Text>
            </Box>
            <Text color={nColors[n.type]}> {n.message}</Text>
          </Box>
        );
      })}
    </Box>
  );
}
