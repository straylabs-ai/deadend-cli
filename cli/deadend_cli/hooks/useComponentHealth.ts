import { useState, useCallback } from "react";
import type { AllHealthResult, HealthResult, InitResult } from "../types/rpc.ts";
import type { DeadEndRpcClient } from "../lib/deadend-rpc-client.ts";

export type ComponentName =
  | "docker"
  | "pgvector"
  | "config"
  | "python_sandbox"
  | "shell_sandbox";

export interface UseComponentHealthOptions {
  /** Callback when all components are healthy */
  onHealthy?: () => void;
  /** Callback when some components are unhealthy */
  onUnhealthy?: (failedComponents: string[]) => void;
  /** Callback for initialization progress */
  onInitProgress?: (component: string, result: InitResult) => void;
}

export interface UseComponentHealthReturn {
  /** Current health status of all components */
  health: AllHealthResult | null;
  /** Whether a health check is in progress */
  isChecking: boolean;
  /** Whether initialization is in progress */
  isInitializing: boolean;
  /** Current component being initialized */
  currentInitComponent: string | null;
  /** Initialization results for each component */
  initResults: Map<string, InitResult>;
  /** Current error, if any */
  error: Error | null;
  /** Check health of all components */
  checkHealth: () => Promise<AllHealthResult | null>;
  /** Initialize all components */
  initializeAll: () => Promise<boolean>;
  /** Initialize a specific component */
  initComponent: (name: ComponentName) => Promise<InitResult | null>;
  /** Get health for a specific component */
  getComponentHealth: (name: string) => HealthResult | null;
  /** List of unhealthy components */
  unhealthyComponents: string[];
}

export function useComponentHealth(
  rpcClient: DeadEndRpcClient | null,
  options: UseComponentHealthOptions = {}
): UseComponentHealthReturn {
  const { onHealthy, onUnhealthy, onInitProgress } = options;

  const [health, setHealth] = useState<AllHealthResult | null>(null);
  const [isChecking, setIsChecking] = useState(false);
  const [isInitializing, setIsInitializing] = useState(false);
  const [currentInitComponent, setCurrentInitComponent] = useState<string | null>(null);
  const [initResults, setInitResults] = useState<Map<string, InitResult>>(new Map());
  const [error, setError] = useState<Error | null>(null);

  const checkHealth = useCallback(async (): Promise<AllHealthResult | null> => {
    if (!rpcClient) {
      setError(new Error("RPC client not available"));
      return null;
    }

    setIsChecking(true);
    setError(null);

    try {
      const result = await rpcClient.healthAll();
      setHealth(result);

      if (result.overall_healthy) {
        onHealthy?.();
      } else {
        const failed = result.components
          .filter((c) => !c.healthy)
          .map((c) => c.component);
        onUnhealthy?.(failed);
      }

      return result;
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      setError(error);
      return null;
    } finally {
      setIsChecking(false);
    }
  }, [rpcClient, onHealthy, onUnhealthy]);

  const initComponent = useCallback(
    async (name: ComponentName): Promise<InitResult | null> => {
      if (!rpcClient) {
        setError(new Error("RPC client not available"));
        return null;
      }

      setCurrentInitComponent(name);

      try {
        let result: InitResult;

        switch (name) {
          case "docker":
            result = await rpcClient.initDocker();
            break;
          case "pgvector":
            result = await rpcClient.initPgvector();
            break;
          case "config":
            result = await rpcClient.initConfig();
            break;
          case "python_sandbox":
            result = await rpcClient.initPythonSandbox();
            break;
          case "shell_sandbox":
            result = await rpcClient.initShellSandbox();
            break;
          default:
            throw new Error(`Unknown component: ${name}`);
        }

        setInitResults((prev) => new Map(prev).set(name, result));
        onInitProgress?.(name, result);
        return result;
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        const failedResult: InitResult = {
          success: false,
          component: name,
          status: "error",
          message: error.message,
          details: {},
        };
        setInitResults((prev) => new Map(prev).set(name, failedResult));
        onInitProgress?.(name, failedResult);
        return failedResult;
      } finally {
        setCurrentInitComponent(null);
      }
    },
    [rpcClient, onInitProgress]
  );

  const initializeAll = useCallback(async (): Promise<boolean> => {
    if (!rpcClient) {
      setError(new Error("RPC client not available"));
      return false;
    }

    setIsInitializing(true);
    setError(null);
    setInitResults(new Map());

    const components: ComponentName[] = [
      "docker",
      "pgvector",
      "config",
      "python_sandbox",
      "shell_sandbox",
    ];

    let allSuccess = true;

    for (const component of components) {
      const result = await initComponent(component);
      if (!result || !result.success) {
        allSuccess = false;
        // Continue initializing remaining components even if one fails
      }
    }

    setIsInitializing(false);

    // Check health after initialization
    await checkHealth();

    return allSuccess;
  }, [rpcClient, initComponent, checkHealth]);

  const getComponentHealth = useCallback(
    (name: string): HealthResult | null => {
      if (!health) return null;
      return health.components.find((c) => c.component === name) ?? null;
    },
    [health]
  );

  const unhealthyComponents = health
    ? health.components.filter((c) => !c.healthy).map((c) => c.component)
    : [];

  return {
    health,
    isChecking,
    isInitializing,
    currentInitComponent,
    initResults,
    error,
    checkHealth,
    initializeAll,
    initComponent,
    getComponentHealth,
    unhealthyComponents,
  };
}
