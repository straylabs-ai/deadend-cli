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

import { useState, useCallback, useEffect, useMemo, type ReactNode } from "react";
import { logger } from "../lib/logger.ts";
import { Box, useInput, Static } from "ink";
import type { Message } from "../types/message.ts";
import { ChatMessage } from "./ChatMessage.tsx";
import { createMessage } from "../types/message.ts";
import { parseCommand, isCommand } from "../lib/commands/command-parser.ts";
import { executeCommand } from "../lib/commands/command-handler.ts";
import type { RpcClient, InitResult } from "../types/rpc.ts";
import { setTarget as setTargetLocal, TARGET_SET_PREFIX } from "../lib/commands/handlers/target.ts";
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
  /** Banner element to render at the very top (inside Static) */
  banner?: ReactNode;
}

export function Chat({ rpcClient, onExit, cliArgs, componentResults = [], banner }: ChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [currentLlm, setCurrentLlm] = useState<{
    provider: string;
    model: string | null;
  } | null>(null);
  const [notifications, setNotifications] = useState<StatusNotification[]>([]);
  const [showComponentStatus, _setShowComponentStatus] = useState(false);
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

  // Split messages into static and dynamic for Static component usage
  // Keep last 5 messages dynamic (they might still be updating)
  const DYNAMIC_MESSAGES_COUNT = 5;
  
  const { staticMessages, dynamicMessages } = useMemo(() => {
    if (messages.length <= DYNAMIC_MESSAGES_COUNT) {
      return { staticMessages: [], dynamicMessages: messages };
    }
    return {
      staticMessages: messages.slice(0, messages.length - DYNAMIC_MESSAGES_COUNT),
      dynamicMessages: messages.slice(-DYNAMIC_MESSAGES_COUNT)
    };
  }, [
    messages.length,
    messages.length > DYNAMIC_MESSAGES_COUNT ? messages.length - DYNAMIC_MESSAGES_COUNT : 0,
    messages.length > DYNAMIC_MESSAGES_COUNT ? messages[messages.length - DYNAMIC_MESSAGES_COUNT - 1]?.id : null
  ]);

  // Task runner hook for streaming task execution
  const { taskState, setTarget, runTask, cancel } = useTaskRunner(
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
   * Load CLI settings on mount and set LLM display.
   * This runs first and sets settingsLoaded=true when complete.
   */
  useEffect(() => {
    const initSettings = async () => {
      const loaded = await loadSettings();
      logger.log("[Settings] Loaded settings:", loaded);
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

    const initFromCliArgs = async () => {
      if (cliArgs?.target) {
        // Store target locally for /target command checks
        setTargetLocal(cliArgs.target);

        // Initialize agent and embed target via RPC
        await setTarget({ target: cliArgs.target });
      }

      // If prompt is provided, execute it after target is set and settings are loaded
      if (cliArgs?.prompt && cliArgs?.target && taskState.isTargetEmbedded) {
        // Add user message for the task
        const userMessage = createMessage("user", cliArgs.prompt, "text");
        addMessage(userMessage);
        logger.log("[Task Start] Model settings:", {
          provider: settings.provider,
          model: settings.model,
          mode: executionMode,
          target: cliArgs.target,
          task: cliArgs.prompt,
        });
        // Start the task
        runTask({
          task: cliArgs.prompt,
          mode: executionMode,
        });
      }
    };

    initFromCliArgs();
  }, [rpcClient, settingsLoaded, taskState.isTargetEmbedded]); // Re-run when target is embedded

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
    { isActive: true }
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

        // Handle /target command - initialize agent for target
        if (result.startsWith(TARGET_SET_PREFIX)) {
          const targetUrl = result.slice(TARGET_SET_PREFIX.length);
          addMessage(createMessage("system", `Target set to: ${targetUrl}`, "info"));
          // Initialize agent and embed target via RPC
          setIsLoading(false);
          setTarget({ target: targetUrl });
          return;
        }

        // Add command result message
        const resultMessage = createMessage("system", result, "text");
        addMessage(resultMessage);
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

    // Check if target is set and embedded
    if (!taskState.isTargetEmbedded) {
      const errorMessage = createMessage(
        "system",
        "No target set or target not ready. Use /target <url> first and wait for initialization.",
        "error"
      );
      addMessage(errorMessage);
      setIsLoading(false);
      return;
    }

    // Start agent execution with the message as the task
    setIsLoading(false);
    runTask({
      task: trimmedInput,
      mode: executionMode,
    });
  }, [
    input,
    isLoading,
    taskState.isRunning,
    taskState.isTargetEmbedded,
    addMessage,
    onExit,
    executionMode,
    runTask,
    setTarget,
  ]);


  // Combine banner and static messages for Static component
  // Banner comes first, then old messages - all rendered once and never re-render
  const staticItems = useMemo(() => {
    const items: Array<{ type: 'banner'; id: string } | { type: 'message'; id: string; message: Message }> = [];

    // Add banner as first item (always)
    if (banner) {
      items.push({ type: 'banner', id: 'banner' });
    }

    // Add static messages
    for (const msg of staticMessages) {
      items.push({ type: 'message', id: msg.id, message: msg });
    }

    return items;
  }, [banner, staticMessages]);

  return (
    <Box flexDirection="column">
      {/* Static content - banner first, then old messages. Rendered once, never re-render */}
      {staticItems.length > 0 && (
        <Static items={staticItems}>
          {(item) => {
            if (item.type === 'banner') {
              // Banner is already a Box component, wrap in fragment with key
              return <Box key={item.id}>{banner}</Box>;
            }
            return <ChatMessage key={item.id} message={item.message} />;
          }}
        </Static>
      )}

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
      {/* No flexGrow constraint - allows terminal to scroll naturally */}
      <ChatHistory 
        messages={messages} 
        staticMessages={staticMessages}
        dynamicMessages={dynamicMessages}
      />

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
