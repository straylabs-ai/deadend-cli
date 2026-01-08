import { render, Box, Text } from "ink";
import { useState, useEffect } from "react";
import { Banner } from "./components/Banner.tsx";
import { Chat } from "./components/chat.tsx";
import { Presetup } from "./components/Presetup.tsx";
import { DeadEndRpcClient } from "./lib/deadend-rpc-client.ts";
import { DummyRpcClient } from "./lib/dummy-rpc-client.ts";
import { configExists } from "./lib/config.ts";
import { parseArgs, showHelp, type CliArgs } from "./lib/cli-args.ts";

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

          const client = new DeadEndRpcClient({
            pythonCommand: "uv",
            commandArgs: ["run", "python", "-m", "deadend_cli.rpc_server"],
            cwd: pythonPkgDir,
          });
          await client.start();

          // Test connection with ping
          const isAlive = await client.ping();
          if (!isAlive) {
            throw new Error("RPC server not responding");
          }

          // Initialize all components
          setInitStatus("Initializing Docker...");
          const dockerResult = await client.initDocker();
          if (!dockerResult.success) {
            throw new Error(`Docker init failed: ${dockerResult.message}`);
          }

          setInitStatus("Initializing pgvector database...");
          const pgResult = await client.initPgvector();
          if (!pgResult.success) {
            console.error("pgvector init failed:", pgResult.message);
            // Continue anyway - pgvector is optional for some operations
          }

          setInitStatus("Loading configuration...");
          const configResult = await client.initConfig();
          if (!configResult.success) {
            console.error("Config init failed:", configResult.message);
          }

          setInitStatus("Initializing shell sandbox...");
          const shellResult = await client.initShellSandbox();
          if (!shellResult.success) {
            console.error("Shell sandbox init failed:", shellResult.message);
          }

          setInitStatus("Initializing Python sandbox...");
          const pythonResult = await client.initPythonSandbox();
          if (!pythonResult.success) {
            console.error("Python sandbox init failed:", pythonResult.message);
          }

          // Playwright is optional and can be slow, skip for now
          // const playwrightResult = await client.initPlaywright();

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
      <Box flexDirection="column" height="100%" justifyContent="center" alignItems="center">
        <Text color="cyan">
          {initStatus}
        </Text>
        {rpcError && (
          <Box marginTop={1}>
            <Text color="yellow" dimColor>
              Note: Using offline mode ({rpcError})
            </Text>
          </Box>
        )}
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

