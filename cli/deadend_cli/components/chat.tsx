/**
 * @file chat.tsx
 * @description Main chat component for the DeadEnd CLI.
 *
 * This component provides:
 * - Unified chat interface with inline streaming events
 * - Command input and parsing
 * - Mode switching between YOLO (autonomous) and Supervisor modes
 * - Keyboard shortcut (Shift+Tab) for mode toggling
 */

import { useState, useCallback, useEffect } from "react";
import { Box, useInput } from "ink";
import type { Message } from "../types/message.ts";
import { createMessage } from "../types/message.ts";
import { parseCommand, isCommand } from "../lib/commands/command-parser.ts";
import { executeCommand } from "../lib/commands/command-handler.ts";
import type { RpcClient, InitResult } from "../types/rpc.ts";
import { ConfigSetup } from "./ConfigSetup.tsx";
import { START_RUN } from "../lib/commands/handlers/run.ts";
import {
  setLlmRpcClient,
  INFO_MESSAGE_PREFIX,
  OPEN_LLM_SELECTOR,
} from "../lib/commands/handlers/llm.ts";
import { LlmSelector } from "./LlmSelector.tsx";
import { getCurrentTarget, setTarget } from "../lib/commands/handlers/target.ts";
import type { CliArgs } from "../lib/cli-args.ts";
import type { DeadEndRpcClient } from "../lib/deadend-rpc-client.ts";
import { StatusArea, type StatusNotification } from "./StatusArea.tsx";
import { ChatHistory } from "./ChatHistory.tsx";
import { InputArea } from "./InputArea.tsx";
import { useTaskRunner } from "../hooks/useTaskRunner.ts";
import { loadSettings, type CliSettings } from "../lib/settings.ts";

/**
 * Execution mode for security testing.
 * - yolo: Autonomous execution without human intervention
 * - supervisor: Step-by-step execution with approval workflow
 */
export type ExecutionMode = "yolo" | "supervisor";

interface ChatProps {
  rpcClient: RpcClient | DeadEndRpcClient;
  onExit?: () => void;
  cliArgs?: CliArgs;
  /** Component initialization results for status display */
  componentResults?: InitResult[];
}

export function Chat({ rpcClient, onExit, cliArgs, componentResults = [] }: ChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [showConfigSetup, setShowConfigSetup] = useState(false);
  const [showLlmSelector, setShowLlmSelector] = useState(false);
  const [currentLlm, setCurrentLlm] = useState<{
    provider: string;
    model: string | null;
  } | null>(null);
  const [notifications, setNotifications] = useState<StatusNotification[]>([]);
  const [showComponentStatus, setShowComponentStatus] = useState(false);
  const [settings, setSettings] = useState<CliSettings>({});
  const [settingsLoaded, setSettingsLoaded] = useState(false);

  /**
   * Current execution mode (persists across task executions).
   * - "yolo": Autonomous mode - runs exploitation without approval
   * - "supervisor": Supervised mode - runs with approval workflow
   */
  const [executionMode, setExecutionMode] = useState<ExecutionMode>("yolo");

  const addMessage = useCallback((message: Message) => {
    setMessages((prev) => [...prev, message]);
  }, []);

  // Task runner hook for streaming task execution
  const { taskState, runTask, cancel } = useTaskRunner(
    rpcClient as DeadEndRpcClient,
    {
      onMessage: addMessage,
      onComplete: () => {
        // Task completed, no special action needed
      },
      onCancel: () => {
        addMessage(createMessage("system", "Task cancelled.", "info"));
      },
      onError: (error) => {
        setNotifications((prev) => [
          ...prev,
          { id: crypto.randomUUID(), type: "error", message: error },
        ]);
      },
    }
  );

  /**
   * Toggle between execution modes.
   * Called by Shift+Tab keyboard shortcut.
   */
  const toggleMode = useCallback(() => {
    setExecutionMode((prev) => {
      const newMode = prev === "yolo" ? "supervisor" : "yolo";
      return newMode;
    });
  }, []);

  /**
   * Set up the RPC client for command handlers that need it.
   */
  useEffect(() => {
    if (rpcClient && "getLlmProvider" in rpcClient) {
      setLlmRpcClient(rpcClient as DeadEndRpcClient);
    }
  }, [rpcClient]);

  /**
   * Refresh LLM display from settings or server.
   * Settings take priority over server-reported provider.
   */
  const refreshLlm = useCallback(async () => {
    // First load settings
    const loaded = await loadSettings();
    console.log("[Task settings] Task settings :", loaded)
    setSettings(loaded);

    // If settings has provider, use it
    if (loaded.provider) {
      setCurrentLlm({
        provider: loaded.provider,
        model: loaded.model || null,
      });
    } else if (rpcClient && "listLlmProviders" in rpcClient) {
      // Otherwise, fetch from server as fallback
      try {
        const result = await (rpcClient as DeadEndRpcClient).listLlmProviders();
        const current = result.providers.find((p) => p.name === result.current);
        setCurrentLlm({
          provider: result.current,
          model: current?.model || null,
        });
      } catch {
        // Ignore errors
      }
    }
  }, [rpcClient]);

  /**
   * Load CLI settings on mount and set LLM display.
   * This runs first and sets settingsLoaded=true when complete.
   */
  useEffect(() => {
    const initSettings = async () => {
      const loaded = await loadSettings();
      console.log("[Settings] Loaded settings:", loaded);
      setSettings(loaded);

      // Apply execution mode from settings if set
      if (loaded.executionMode) {
        setExecutionMode(loaded.executionMode);
      }

      // Set LLM display from settings
      if (loaded.provider) {
        setCurrentLlm({
          provider: loaded.provider,
          model: loaded.model || null,
        });
      }

      // Mark settings as loaded - this gates CLI args execution
      setSettingsLoaded(true);
    };

    initSettings();
  }, []); // Run only once on mount

  /**
   * Handle CLI arguments on startup.
   * Sets target and executes initial prompt if provided.
   * Waits for both rpcClient and settings to be loaded.
   */
  useEffect(() => {
    // Wait for settings to be loaded before executing tasks
    if (!settingsLoaded) {
      return;
    }

    if (cliArgs?.target) {
      setTarget(cliArgs.target);
      const targetMessage = createMessage(
        "system",
        `Target set from CLI: ${cliArgs.target}`,
        "info"
      );
      addMessage(targetMessage);
    }

    // If prompt is provided, execute it after target is set and settings are loaded
    if (cliArgs?.prompt && cliArgs?.target) {
      if (rpcClient && "runTask" in rpcClient) {
        // Add user message for the task
        const userMessage = createMessage("user", cliArgs.prompt, "text");
        addMessage(userMessage);
        console.log("[Task Start] Model settings:", {
          provider: settings.provider,
          model: settings.model,
          mode: executionMode,
          target: cliArgs.target,
          task: cliArgs.prompt,
        });
        // Start the task with settings
        runTask({
          target: cliArgs.target,
          task: cliArgs.prompt,
          mode: executionMode,
          provider: settings.provider,
          model: settings.model,
        });
      } else {
        const errorMessage = createMessage(
          "system",
          "Cannot start task: RPC client not properly initialized.",
          "error"
        );
        addMessage(errorMessage);
      }
    }
  }, [rpcClient, settingsLoaded]); // Re-run when rpcClient is ready AND settings are loaded

  /**
   * Handle keyboard shortcuts.
   * Shift+Tab: Toggle between YOLO and Supervisor modes
   * Ctrl+C: Cancel running task
   */
  useInput(
    (inputChar, key) => {
      // Shift+Tab to toggle mode
      if (key.shift && key.tab) {
        toggleMode();
      }
      // Ctrl+C to cancel running task
      if (key.ctrl && inputChar === "c" && taskState.isRunning) {
        cancel();
      }
    },
    { isActive: !showConfigSetup && !showLlmSelector }
  );

  const handleSubmit = useCallback(async () => {
    if (!input.trim() || isLoading || taskState.isRunning) return;

    const trimmedInput = input.trim();
    setInput("");
    setIsLoading(true);

    // Check if it's a valid command
    const parsed = isCommand(trimmedInput) ? parseCommand(trimmedInput) : null;

    if (parsed) {
      // Valid command found - execute it
      const userMessage = createMessage("user", trimmedInput, "command");
      addMessage(userMessage);

      try {
        const result = await executeCommand(parsed.command, parsed.args);

        // Handle special command responses
        if (result === "CLEAR_CHAT") {
          setMessages([]);
          setIsLoading(false);
          return;
        }

        if (result === "EXIT_APP") {
          if (onExit) {
            onExit();
          }
          setIsLoading(false);
          return;
        }

        if (result === "START_CONFIG_SETUP") {
          setIsLoading(false);
          setShowConfigSetup(true);
          return;
        }

        // Handle /llm command - open interactive selector
        if (result === OPEN_LLM_SELECTOR) {
          setIsLoading(false);
          setShowLlmSelector(true);
          return;
        }

        // Handle /run command - start task with current mode
        if (result === START_RUN) {
          const target = getCurrentTarget();
          if (!target) {
            const errorMessage = createMessage(
              "system",
              "Error: No target set. Use /target <url> first.",
              "error"
            );
            addMessage(errorMessage);
            setIsLoading(false);
            return;
          }
          // Get the task from the parsed args
          const taskArg = parsed.args.join(" ").trim();
          if (!taskArg) {
            const errorMessage = createMessage(
              "system",
              "Error: Please provide a task. Usage: /run <task description>",
              "error"
            );
            addMessage(errorMessage);
            setIsLoading(false);
            return;
          }
          // Start the task (events will stream as messages)
          setIsLoading(false);
          runTask({
            target,
            task: taskArg,
            mode: executionMode,
            provider: settings.provider,
            model: settings.model,
          });
          return;
        }

        // Add command result message
        // Check for info message prefix (renders italic)
        if (result.startsWith(INFO_MESSAGE_PREFIX)) {
          const content = result.slice(INFO_MESSAGE_PREFIX.length);
          const resultMessage = createMessage("system", content, "info");
          addMessage(resultMessage);
        } else {
          const resultMessage = createMessage("system", result, "text");
          addMessage(resultMessage);
        }
      } catch (error) {
        const errorMessage = createMessage(
          "system",
          `Error: ${error instanceof Error ? error.message : "Unknown error"}`,
          "error"
        );
        addMessage(errorMessage);
      }
      setIsLoading(false);
      return;
    }

    // No valid command found - treat as task for agent
    const userMessage = createMessage("user", trimmedInput, "text");
    addMessage(userMessage);

    // Check if target is set
    const target = getCurrentTarget();
    if (!target) {
      const errorMessage = createMessage(
        "system",
        "No target set. Use /target <url> first.",
        "error"
      );
      addMessage(errorMessage);
      setIsLoading(false);
      return;
    }

    // Start agent execution with the message as the task
    setIsLoading(false);
    runTask({
      target,
      task: trimmedInput,
      mode: executionMode,
      provider: settings.provider,
      model: settings.model,
    });
  }, [
    input,
    isLoading,
    taskState.isRunning,
    addMessage,
    onExit,
    executionMode,
    runTask,
    settings,
  ]);

  // Config setup view
  if (showConfigSetup) {
    return (
      <Box flexDirection="column" flexGrow={1}>
        <ConfigSetup
          onComplete={() => {
            setShowConfigSetup(false);
            const successMessage = createMessage(
              "system",
              "Configuration saved successfully!",
              "text"
            );
            addMessage(successMessage);
          }}
        />
      </Box>
    );
  }

  // LLM Selector view
  if (showLlmSelector) {
    const streamingClient = rpcClient as unknown as DeadEndRpcClient;
    return (
      <Box flexDirection="column" flexGrow={1}>
        <LlmSelector
          rpcClient={streamingClient}
          onComplete={() => {
            setShowLlmSelector(false);
            refreshLlm();
            const successMessage = createMessage("system", "LLM provider updated.", "info");
            addMessage(successMessage);
          }}
          onCancel={() => {
            setShowLlmSelector(false);
          }}
        />
      </Box>
    );
  }

  return (
    <Box flexDirection="column" flexGrow={1}>
      {/* Status area - shows component health and task status */}
      <StatusArea
        componentResults={componentResults}
        taskPhase={taskState.phase}
        taskTarget={taskState.target}
        isRunning={taskState.isRunning}
        notifications={notifications}
        showComponents={showComponentStatus}
      />

      {/* Chat history - scrollable messages area */}
      <ChatHistory messages={messages} />

      {/* Input area - text input with mode indicator */}
      <InputArea
        value={input}
        onChange={setInput}
        onSubmit={handleSubmit}
        isLoading={taskState.isRunning}
        executionMode={executionMode}
        currentLlm={currentLlm}
      />
    </Box>
  );
}
