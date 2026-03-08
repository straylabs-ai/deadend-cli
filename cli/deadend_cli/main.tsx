import { render, Box, Text } from "ink";
import { useState, useEffect, useRef, useMemo } from "react";
import { logger } from "./runtime/logger.ts";
import { Banner } from "./components/Banner.tsx";
import { Chat } from "./components/chat.tsx";
import { PresetupWizard } from "./components/PresetupWizard.tsx";
import { DirectStatusLine } from "./components/DirectStatusLine.tsx";
import { BlinkDot } from "./components/BlinkDot.tsx";
import { colors } from "./components/colors.ts";
import { DeadEndRpcClient } from "./runtime/deadend-rpc-client.ts";
import { configExists } from "./runtime/config.ts";
import { configManager } from "./config/manager.ts";
import { parseArgs, showHelp, type CliArgs } from "./runtime/cli-args.ts";
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
      logger.error("Failed to shutdown RPC server gracefully:", err);
    } finally {
      rpcClientRef.current.close();
      rpcClientRef.current = null;
    }
  }

  // Initialize RPC client and components
  useEffect(() => {
    const initClient = async () => {
      try {
        setInitStatus("Starting server...");
        
        // Set up log file path for RPC server stderr output
        const homeDir = Deno.env.get("HOME") || Deno.env.get("USERPROFILE") || "~";
        const logDir = `${homeDir}/.cache/deadend/logs`;
        const logFile = `${logDir}/rpc-server-${Date.now()}.log`;
        
        // Determine if we're in dev/debug mode or production
        const isDevMode = Deno.env.get("DENO_TASK") === "dev" || 
                         Deno.env.get("DENO_TASK") === "debug" ||
                         Deno.env.get("DEBUG") === "true" ||
                         Deno.args.includes("--dev");
        
        let client: DeadEndRpcClient;
        
        if (isDevMode) {
          // Development mode: use uv to run Python module
          const scriptDir = import.meta.dirname ?? Deno.cwd();
          const pythonPkgDir = `${scriptDir}/../../deadend_cli`;
          
          client = new DeadEndRpcClient({
            pythonCommand: "uv",
            commandArgs: ["run", "python", "-m", "deadend_cli.jsonrpc_server", "--log-file", logFile],
            cwd: pythonPkgDir,
            logFile: logFile,
          });
        } else {
          // Production mode: use deadend.sh from installed package
          const rpcBinary = Deno.env.get("DEADEND_RPC_BINARY") ??
                           `${homeDir}/.cache/deadend/server/deadend.sh`;
          
          // Check if deadend.sh exists
          try {
            await Deno.stat(rpcBinary);
          } catch {
            throw new Error(
              `Server binary not found at ${rpcBinary}. ` +
              `Please run the install script to download it: ` +
              `curl -fsSL https://raw.githubusercontent.com/xoxruns/deadend-cli/main/install.sh | bash`
            );
          }
          
          client = new DeadEndRpcClient({
            pythonCommand: rpcBinary,
            commandArgs: ["--log-file", logFile],
            cwd: Deno.cwd(),
            logFile: logFile,
          });
        }
        
        await client.start();

        // Test connection with ping
        setInitStatus("Agent startup...");
        const isAlive = await client.ping();
        if (!isAlive) {
          throw new Error("RPC server not responding");
        }

        // Initialize all components at once using init_all
        setInitStatus("Initializing all components...");
        // We can wait longer here for pgvector and the sandbox
        const initResult = await client.initAll(300000);

        // Store component results for display
        setComponentResults(initResult.components);

        // Log individual component results
        for (const component of initResult.components) {
          if (component.success) {
            logger.log(`✓ ${component.component}: ${component.message}`);
          } else {
            logger.error(`✗ ${component.component}: ${component.message}`);
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
          logger.warn(
            `Warning: Some components failed to initialize: ${initResult.failed_components.join(", ")}`
          );
        }
        rpcClientRef.current = client;
        setRpcClient(client);
        setInitComplete(true);
      } catch (err) {
        logger.error("Failed to initialize:", err);
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

  // Check if config exists and has providers configured
  useEffect(() => {
    const checkConfig = async () => {
      const exists = await configExists();
      if (!exists) {
        setIsChecking(false);
        setShowPresetup(true);
        return;
      }
      
      // If config exists, check if it has providers configured
      try {
        await configManager.load();
        const config = configManager.getConfig();
        if (!config || !config.configured_models || config.configured_models.length === 0) {
          setIsChecking(false);
          setShowPresetup(true);
        } else {
          setIsChecking(false);
          setShowPresetup(false);
        }
      } catch (error) {
        logger.warn("Failed to load config, showing presetup:", error);
        setIsChecking(false);
        setShowPresetup(true);
      }
    };
    
    checkConfig();
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

  // Static banner content - memoized to prevent re-renders
  // MUST be called before any conditional returns to follow Rules of Hooks
  const staticBanner = useMemo(() => (
    <Box flexDirection="column" marginTop={1} marginBottom={1}>
      <Banner />
      <Text dimColor>
        deadend CLI v0.1.3 {"\u00B7"} Type /help for commands
      </Text>
      {(cliArgs.mode || cliArgs.target || cliArgs.prompt) && (
        <Box marginTop={1} flexDirection="row">
          {cliArgs.mode && (
            <Text color={colors.accent}>[{cliArgs.mode}] </Text>
          )}
          {cliArgs.target && (
            <Text color={colors.status.error}>{cliArgs.target} </Text>
          )}
          {cliArgs.prompt && (
            <Text color={colors.text.secondary}>{"\u2192"} {cliArgs.prompt}</Text>
          )}
        </Box>
      )}
      <Text dimColor>{"\u2500".repeat(60)}</Text>
    </Box>
  ), [cliArgs.mode, cliArgs.target, cliArgs.codebase, cliArgs.prompt]);

  // All hooks must be called before any conditional returns
  if (shouldExit) {
    return null;
  }

  if (isChecking || !rpcClient || !initComplete) {
    return (
      <Box flexDirection="column">
        <Box marginBottom={1}>
          <Banner />
        </Box>
        <Box flexDirection="column">
          <DirectStatusLine
            text={initStatus}
            color="grey"
            isActive={!rpcError}
            updateInterval={100}
          />
          {componentResults.length > 0 && (
            <Box flexDirection="column" marginTop={1}>
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
          {rpcError && (
            <Box marginTop={1} flexDirection="row">
              <Box width={2} flexShrink={0}>
                <Text color={colors.status.error}>{"\u2717"}</Text>
              </Box>
              <Text color={colors.status.error}>
                {" "}Failed to initialize: {rpcError}
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
        <Box />
          <Banner />
        <Box flexDirection="column" flexGrow={1}>
          <PresetupWizard rpcClient={rpcClient} onComplete={handlePresetupComplete} />
        </Box>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      {/* Chat handles all rendering including banner in its Static component */}
      <Chat
        rpcClient={rpcClient}
        onExit={handleExit}
        cliArgs={cliArgs}
        componentResults={componentResults}
        banner={staticBanner}
      />
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

