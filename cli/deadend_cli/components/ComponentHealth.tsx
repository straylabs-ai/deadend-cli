import { Box, Text } from "ink";
import { useEffect } from "react";
import { useComponentHealth } from "../hooks/useComponentHealth.ts";
import type { DeadEndRpcClient } from "../runtime/deadend-rpc-client.ts";
import { LoadingSpinner } from "./LoadingSpinner.tsx";

export interface ComponentHealthProps {
  /** RPC client instance */
  rpcClient: DeadEndRpcClient;
  /** Callback when all components are healthy */
  onHealthy?: () => void;
  /** Callback when some components are unhealthy */
  onUnhealthy?: (failedComponents: string[]) => void;
  /** Whether to auto-initialize on mount */
  autoInit?: boolean;
  /** Whether to auto-check health on mount */
  autoCheck?: boolean;
  /** Component layout: "row" shows all in one row, "column" shows each on its own line */
  layout?: "row" | "column";
}

// Short display names for components
const COMPONENT_NAMES: Record<string, string> = {
  docker: "Docker",
  rag: "RAG",
  config: "Config",
  python_sandbox: "Python",
  shell_sandbox: "Shell",
};

// Order to display components
const COMPONENT_ORDER = [
  "docker",
  "config",
  "rag",
  "python_sandbox",
  "shell_sandbox",
];

export function ComponentHealth({
  rpcClient,
  onHealthy,
  onUnhealthy,
  autoInit = false,
  autoCheck = true,
  layout = "row",
}: ComponentHealthProps) {
  const {
    health,
    isChecking,
    isInitializing,
    currentInitComponent,
    initResults,
    error,
    checkHealth,
    initializeAll,
    getComponentHealth,
    unhealthyComponents,
  } = useComponentHealth(rpcClient, { onHealthy, onUnhealthy });

  // Auto-check or auto-init on mount
  useEffect(() => {
    if (autoInit) {
      initializeAll();
    } else if (autoCheck) {
      checkHealth();
    }
  }, [autoInit, autoCheck, initializeAll, checkHealth]);

  // Loading state
  if (isChecking && !health) {
    return (
      <Box>
        <LoadingSpinner text="Checking components" color="cyan" />
      </Box>
    );
  }

  // Initializing state
  if (isInitializing) {
    return (
      <Box flexDirection="column">
        <Text color="cyan">Initializing components...</Text>
        {currentInitComponent && (
          <Box>
            <LoadingSpinner
              text={`Initializing ${COMPONENT_NAMES[currentInitComponent] || currentInitComponent}`}
              color="yellow"
            />
          </Box>
        )}
        {/* Show init results so far */}
        <Box flexDirection={layout === "row" ? "row" : "column"} gap={1}>
          {COMPONENT_ORDER.map((name) => {
            const result = initResults.get(name);
            if (!result) return null;

            const displayName = COMPONENT_NAMES[name] || name;
            const icon = result.success ? "✓" : "✗";
            const color = result.success ? "green" : "red";

            return (
              <Box key={name} marginRight={layout === "row" ? 2 : 0}>
                <Text color={color}>
                  {icon} {displayName}
                </Text>
              </Box>
            );
          })}
        </Box>
      </Box>
    );
  }

  // Error state
  if (error && !health) {
    return (
      <Box>
        <Text color="red">{"✗ "}{error.message}</Text>
      </Box>
    );
  }

  // No health data yet
  if (!health) {
    return (
      <Box>
        <Text color="gray" dimColor>
          Component health not checked yet
        </Text>
      </Box>
    );
  }

  // Health display
  if (layout === "row") {
    return (
      <Box flexDirection="row" gap={1}>
        {COMPONENT_ORDER.map((name) => {
          const componentHealth = getComponentHealth(name);
          if (!componentHealth) return null;

          const displayName = COMPONENT_NAMES[name] || name;
          const icon = componentHealth.healthy ? "✓" : "✗";
          const color = componentHealth.healthy ? "green" : "red";

          return (
            <Box key={name} marginRight={2}>
              <Text color={color}>
                {icon} {displayName}
              </Text>
            </Box>
          );
        })}
      </Box>
    );
  }

  // Column layout
  return (
    <Box flexDirection="column">
      {COMPONENT_ORDER.map((name) => {
        const componentHealth = getComponentHealth(name);
        if (!componentHealth) return null;

        const displayName = COMPONENT_NAMES[name] || name;
        const icon = componentHealth.healthy ? "✓" : "✗";
        const color = componentHealth.healthy ? "green" : "red";

        return (
          <Box key={name} marginBottom={0}>
            <Text color={color}>
              {icon} {displayName.padEnd(12)}
            </Text>
            {!componentHealth.healthy && (
              <Text color="gray" dimColor>
                {" - "}{componentHealth.message}
              </Text>
            )}
          </Box>
        );
      })}

      {/* Summary */}
      <Box marginTop={1}>
        {health.overall_healthy ? (
          <Text color="green" bold>
            All components healthy
          </Text>
        ) : (
          <Text color="red">
            {unhealthyComponents.length} component(s) unhealthy
          </Text>
        )}
      </Box>
    </Box>
  );
}

// Compact inline version for header display
export function ComponentHealthInline({
  rpcClient,
  onHealthy,
  onUnhealthy,
}: Omit<ComponentHealthProps, "layout" | "autoInit" | "autoCheck">) {
  const { health, isChecking, getComponentHealth } = useComponentHealth(rpcClient, {
    onHealthy,
    onUnhealthy,
  });

  useEffect(() => {
    // Don't auto-check here, let parent control it
  }, []);

  if (isChecking || !health) {
    return (
      <Box>
        <Text color="gray" dimColor>
          Checking...
        </Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="row" gap={1}>
      {COMPONENT_ORDER.map((name) => {
        const componentHealth = getComponentHealth(name);
        if (!componentHealth) return null;

        const displayName = COMPONENT_NAMES[name] || name;
        const icon = componentHealth.healthy ? "✓" : "✗";
        const color = componentHealth.healthy ? "green" : "red";

        return (
          <Text key={name} color={color}>
            {icon} {displayName}
          </Text>
        );
      })}
    </Box>
  );
}
