import { render, Box, Text } from "ink";
import { useState, useEffect } from "react";
import { Banner } from "./components/Banner.tsx";
import { Chat } from "./components/chat.tsx";
import { Presetup } from "./components/Presetup.tsx";
import { LoadingSpinner } from "./components/LoadingSpinner.tsx";
import { DeadEndRpcClient } from "./lib/deadend-rpc-client.ts";
import { DummyRpcClient } from "./lib/dummy-rpc-client.ts";
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
  const [rpcClient, setRpcClient] = useState<DeadEndRpcClient | DummyRpcClient | null>(null);
  const [rpcError, setRpcError] = useState<string | null>(null);
  const [useRealClient, setUseRealClient] = useState(true);
  const [initStatus, setInitStatus] = useState<string>("Connecting to RPC server...");
  const [initComplete, setInitComplete] = useState(false);
  const [componentResults, setComponentResults] = useState<InitResult[]>([]);

  // Initialize RPC client and components
  useEffect(() => {
    const initClient = async () => {
      if (useRealClient) {
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

          // Check for critical failures (Docker, Config, Model Registry are required)
          const criticalComponents = ["docker", "config", "model_registry"];
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

          setRpcClient(client);
          setInitComplete(true);
        } catch (err) {
          // Fall back to dummy client
          console.error("Failed to initialize:", err);
          setRpcError(err instanceof Error ? err.message : String(err));
          setRpcClient(new DummyRpcClient(500));
          setInitComplete(true);
        }
      } else {
        setRpcClient(new DummyRpcClient(500));
        setInitComplete(true);
      }
    };

    initClient();

    // Cleanup on unmount
    return () => {
      if (rpcClient && "close" in rpcClient) {
        (rpcClient as DeadEndRpcClient).close();
      }
    };
  }, [useRealClient]);

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
      <Box flexDirection="column" padding={2}>
        <Box marginBottom={1}>
          <Banner />
        </Box>
        <Box flexDirection="column" borderStyle="round" borderColor="cyan" padding={1}>
          <Box marginBottom={1}>
            <LoadingSpinner text={initStatus} color="cyan" />
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
              <Text color="yellow" dimColor>
                Note: Using offline mode ({rpcError})
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
            {cliArgs.codebase && (
              <Box marginTop={0}>
                <Text color="gray" dimColor>
                  Codebase: {cliArgs.codebase}
                </Text>
              </Box>
            )}
          </Box>
        </Box>
      </Box>
      <Box flexDirection="column" flexGrow={1}>
        <Chat rpcClient={rpcClient} onExit={handleExit} />
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

