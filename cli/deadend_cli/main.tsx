import { render, Box, Text } from "ink";
import { useState, useEffect, useRef } from "react";
import { Banner } from "./components/Banner.tsx";
import { Chat } from "./components/chat.tsx";
import { Presetup } from "./components/Presetup.tsx";
import { LoadingSpinner } from "./components/LoadingSpinner.tsx";
import { DeadEndRpcClient } from "./lib/deadend-rpc-client.ts";
import { configExists } from "./lib/config.ts";
import { parseArgs, showHelp, type CliArgs } from "./lib/cli-args.ts";
import type { InitResult } from "./types/rpc.ts";

interface AppProps {
  cliArgs: CliArgs;
}

function App({ cliArgs }: AppProps) {
  const [shouldExit, setShouldExit] = useState(false);
  const [showPresetup, setShowPresetup] = useState(false);
  const [isChecking, setIsChecking] = useState(true);
  const [rpcClient, setRpcClient] = useState<DeadEndRpcClient | null>(null);
  const [rpcError, setRpcError] = useState<string | null>(null);
  const [initStatus, setInitStatus] = useState<string>("Connecting to RPC server...");
  const [initComplete, setInitComplete] = useState(false);
  const [componentResults, setComponentResults] = useState<InitResult[]>([]);

  // Ref to track rpcClient for cleanup (avoids stale closure in signal handler)
  const rpcClientRef = useRef<DeadEndRpcClient | null>(null);

  // Shutdown helper 
  const cleanupClient = async () => {
    if (!rpcClientRef.current) return;

    try {
      await rpcClientRef.current.shutdown();
    } catch (err) {
      console.error("Failed to shutdown RPC server gracefully:", err);
    } finally {
      rpcClientRef.current.close();
      rpcClientRef.current = null;
    }
  }

  // Initialize RPC client and components
  useEffect(() => {
    const initClient = async () => {
      try {
        // Try to create and start the real RPC client
        // Use uv to run the Python RPC server module
        // The Python package is in ../../deadend_cli relative to this file
        const scriptDir = import.meta.dirname ?? Deno.cwd();
        const pythonPkgDir = `${scriptDir}/../../deadend_cli`;

        setInitStatus("Starting RPC server...");
        const client = new DeadEndRpcClient({
          pythonCommand: "uv",
          commandArgs: ["run", "python", "-m", "deadend_cli.rpc_server"],
          cwd: pythonPkgDir,
        });
        await client.start();

        // Test connection with ping
        setInitStatus("Connecting to RPC server...");
        const isAlive = await client.ping();
        if (!isAlive) {
          throw new Error("RPC server not responding");
        }

        // Initialize all components at once using init_all
        setInitStatus("Initializing all components...");
        const initResult = await client.initAll();

        // Store component results for display
        setComponentResults(initResult.components);

        // Log individual component results
        for (const component of initResult.components) {
          if (component.success) {
            console.log(`✓ ${component.component}: ${component.message}`);
          } else {
            console.error(`✗ ${component.component}: ${component.message}`);
          }
        }

        // Check for critical failures (all components required for task execution)
        const criticalComponents = ["docker", "config", "model_registry", "pgvector", "shell_sandbox"];
        const criticalFailures = initResult.failed_components.filter(
          (c) => criticalComponents.includes(c)
        );

        if (criticalFailures.length > 0) {
          throw new Error(
            `Critical components failed: ${criticalFailures.join(", ")}`
          );
        }

        // Warn about non-critical failures
        if (initResult.failed_components.length > 0) {
          console.warn(
            `Warning: Some components failed to initialize: ${initResult.failed_components.join(", ")}`
          );
        }

        rpcClientRef.current = client;
        setRpcClient(client);
        setInitComplete(true);
      } catch (err) {
        console.error("Failed to initialize:", err);
        setRpcError(err instanceof Error ? err.message : String(err));
        setInitComplete(true);
      }
    };

    initClient();

    // Cleanup on unmount
    return () => {
      void cleanupClient();
    };
  }, []);

  // Set up signal handler for SIGINT (Ctrl+C) to cleanup RPC server
  useEffect(() => {
    const signalHandler = () => {
      void ( async () => {
        await cleanupClient();
        Deno.exit(0);
      })();
    };

    Deno.addSignalListener("SIGINT", signalHandler);

    return () => {
      Deno.removeSignalListener("SIGINT", signalHandler);
    };
  }, []);

  // Check if config exists on mount
  useEffect(() => {
    configExists().then((exists) => {
      setIsChecking(false);
      setShowPresetup(!exists);
    });
  }, []);

  const handleExit = () => {
    setShouldExit(true);
    // Exit the process
    setTimeout(() => {
      Deno.exit(0);
    }, 100);
  };

  const handlePresetupComplete = () => {
    setShowPresetup(false);
  };

  if (shouldExit) {
    return null;
  }

  if (isChecking || !rpcClient || !initComplete) {
    return (
      <Box flexDirection="column">
        <Box marginBottom={1}>
          <Banner />
        </Box>
        <Box flexDirection="column"borderColor="grey">
          <Box marginBottom={1}>
            <LoadingSpinner text={initStatus} color="grey" />
          </Box>
          {componentResults.length > 0 && (
            <Box flexDirection="column" marginTop={1}>
              <Text color="white" bold>Component Status:</Text>
              {componentResults.map((result) => (
                <Box key={result.component}>
                  <Text color={result.success ? "green" : "red"}>
                    {result.success ? "✓" : "✗"} {result.component}
                  </Text>
                  <Text color="gray" dimColor> - {result.message}</Text>
                </Box>
              ))}
            </Box>
          )}
          {rpcError && (
            <Box marginTop={1}>
              <Text color="red" bold>
                Error: Failed to initialize RPC client: {rpcError}
              </Text>
            </Box>
          )}
        </Box>
      </Box>
    );
  }

  if (showPresetup) {
    return (
      <Box flexDirection="column" height="100%">
        <Box marginTop={2} />
        <Box
          borderStyle="round"
          borderColor="red"
          padding={2}
          paddingTop={3}
          marginBottom={3}
        >
          <Banner />
        </Box>
        <Box flexDirection="column" flexGrow={1}>
          <Presetup onComplete={handlePresetupComplete} />
        </Box>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" height="100%">
      <Box marginTop={2} />
      <Box
        borderStyle="round"
        borderColor="red"
        padding={2}
        paddingTop={3}
        marginBottom={3}
      >
        <Box flexDirection="row">
          <Box flexShrink={0}>
            <Banner />
          </Box>
          <Box flexDirection="column" marginLeft={2} flexGrow={1}>
            <Text color="red" bold>
              AI agent CLI for pentesting
            </Text>
            <Box marginTop={1}>
              <Text color="white">
                Explore sinks & sources, find vulnerabilities, test exploits, report everything.
              </Text>
            </Box>
            <Box marginTop={1} flexDirection="column">
              <Text color="magenta" bold>
                How to use:
              </Text>
              <Box marginTop={0}>
                <Text color="white">• Set your target, and prompt a specific task, for ex: Look for IDORs in target.</Text>
              </Box>
              <Box>
                <Text color="white">• Type / to see available commands</Text>
              </Box>
              {/* <Box>
                <Text color="white">• Press Enter to send messages</Text>
              </Box> */}
            </Box>
            {cliArgs.mode && (
              <Box marginTop={1}>
                <Text color="yellow">
                  Mode: {cliArgs.mode}
                </Text>
              </Box>
            )}
            {cliArgs.target && (
              <Box marginTop={0}>
                <Text color="cyan">
                  Target: {cliArgs.target}
                </Text>
              </Box>
            )}
            {cliArgs.codebase && (
              <Box marginTop={0}>
                <Text color="gray" dimColor>
                  Codebase: {cliArgs.codebase}
                </Text>
              </Box>
            )}
            {cliArgs.prompt && (
              <Box marginTop={0}>
                <Text color="green">
                  Initial prompt: {cliArgs.prompt}
                </Text>
              </Box>
            )}
          </Box>
        </Box>
      </Box>
      <Box flexDirection="column" flexGrow={1}>
        <Chat rpcClient={rpcClient} onExit={handleExit} cliArgs={cliArgs} componentResults={componentResults} />
      </Box>
    </Box>
  );
}

if (import.meta.main) {
  const cliArgs = parseArgs();

  // Show help and exit if --help is provided
  if (cliArgs.help) {
    showHelp();
    Deno.exit(0);
  }

  render(<App cliArgs={cliArgs} />);
}

