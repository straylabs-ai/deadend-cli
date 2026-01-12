/**
 * @file chat.tsx
 * @description Main chat component for the DeadEnd CLI.
 *
 * This component provides:
 * - Command input and parsing
 * - Mode switching between YOLO (autonomous) and Supervisor modes
 * - Keyboard shortcut (Shift+Tab) for mode toggling
 * - View switching for task execution
 */

import { useState, useCallback, useMemo, useEffect } from "react";
import { Box, Text, useInput } from "ink";
import TextInput from "ink-text-input";
import type { Message } from "../types/message.ts";
import { createMessage } from "../types/message.ts";
import { parseCommand, isCommand } from "../lib/commands/command-parser.ts";
import { executeCommand } from "../lib/commands/command-handler.ts";
import type { RpcClient, StreamingRpcClient } from "../types/rpc.ts";
import { COMMANDS } from "../types/command.ts";
import { LoadingSpinner } from "./LoadingSpinner.tsx";
import { ConfigSetup } from "./ConfigSetup.tsx";
import { YoloView } from "./YoloView.tsx";
import { NormalView } from "./NormalView.tsx";
import { START_RUN } from "../lib/commands/handlers/run.ts";
import { setLlmRpcClient, INFO_MESSAGE_PREFIX, OPEN_LLM_SELECTOR } from "../lib/commands/handlers/llm.ts";
import { LlmSelector } from "./LlmSelector.tsx";
import { getCurrentTarget, setTarget } from "../lib/commands/handlers/target.ts";
import type { CliArgs } from "../lib/cli-args.ts";
import type { DeadEndRpcClient, DoneEvent } from "../lib/deadend-rpc-client.ts";

/**
 * Execution mode for security testing.
 * - yolo: Autonomous execution without human intervention
 * - supervisor: Step-by-step execution with approval workflow
 */
export type ExecutionMode = "yolo" | "supervisor";

/** Current view state - chat input or task execution views */
type ViewMode = "chat" | "yolo" | "normal";

interface ViewParams {
  target: string;
  task: string;
}

interface ChatProps {
  rpcClient: RpcClient | DeadEndRpcClient;
  onExit?: () => void;
  cliArgs?: CliArgs;
}

export function Chat({ rpcClient, onExit, cliArgs }: ChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [showConfigSetup, setShowConfigSetup] = useState(false);
  const [showLlmSelector, setShowLlmSelector] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("chat");
  const [viewParams, setViewParams] = useState<ViewParams | null>(null);
  const [currentLlm, setCurrentLlm] = useState<{ provider: string; model: string | null } | null>(null);

  /**
   * Current execution mode (persists across task executions).
   * - "yolo": Autonomous mode - runs exploitation without approval
   * - "supervisor": Supervised mode - runs with approval workflow
   */
  const [executionMode, setExecutionMode] = useState<ExecutionMode>("yolo");

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
   * Fetch current LLM provider and model info.
   */
  const fetchCurrentLlm = useCallback(async () => {
    if (rpcClient && "listLlmProviders" in rpcClient) {
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

  useEffect(() => {
    fetchCurrentLlm();
  }, [fetchCurrentLlm]);

  /**
   * Handle CLI arguments on startup.
   * Sets target and executes initial prompt if provided.
   */
  useEffect(() => {
    if (cliArgs?.target) {
      setTarget(cliArgs.target);
      const targetMessage = createMessage(
        "system",
        `Target set from CLI: ${cliArgs.target}`,
        "info"
      );
      addMessage(targetMessage);
    }

    // If prompt is provided, execute it after target is set
    if (cliArgs?.prompt && cliArgs?.target) {
      // Verify rpcClient has runTask method (is DeadEndRpcClient, not DummyRpcClient)
      if (rpcClient && "runTask" in rpcClient) {
        setViewParams({ target: cliArgs.target, task: cliArgs.prompt });
        setViewMode(executionMode === "yolo" ? "yolo" : "normal");
      } else {
        const errorMessage = createMessage(
          "system",
          "Cannot start task: RPC client not properly initialized. Please check the server connection.",
          "error"
        );
        addMessage(errorMessage);
      }
    }
  }, [rpcClient]); // Re-run when rpcClient changes

  /**
   * Handle keyboard shortcuts.
   * Shift+Tab: Toggle between YOLO and Supervisor modes
   */
  useInput((input, key) => {
    // Shift+Tab to toggle mode
    if (key.shift && key.tab) {
      toggleMode();
    }
  }, { isActive: viewMode === "chat" && !showConfigSetup });

  // Filter commands based on input
  const filteredCommands = useMemo(() => {
    if (!input.startsWith("/")) {
      return [];
    }
    
    const commandPart = input.slice(1).trim().toLowerCase();
    if (commandPart === "") {
      return COMMANDS;
    }
    
    return COMMANDS.filter((cmd) => {
      const nameMatch = cmd.name.toLowerCase().startsWith(commandPart);
      const aliasMatch = cmd.aliases?.some((alias) =>
        alias.toLowerCase().startsWith(commandPart)
      );
      return nameMatch || aliasMatch;
    });
  }, [input]);

  const addMessage = useCallback((message: Message) => {
    setMessages((prev) => [...prev, message]);
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!input.trim() || isLoading) return;

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
          setViewParams({ target, task: taskArg });
          setViewMode(executionMode === "yolo" ? "yolo" : "normal");
          setIsLoading(false);
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

    // No valid command found - call the agent with this task
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
    setViewParams({ target, task: trimmedInput });
    setViewMode(executionMode === "yolo" ? "yolo" : "normal");
    setIsLoading(false);
  }, [input, isLoading, rpcClient, addMessage, onExit, executionMode]);

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
            fetchCurrentLlm();
            const successMessage = createMessage(
              "system",
              "LLM provider updated.",
              "info"
            );
            addMessage(successMessage);
          }}
          onCancel={() => {
            setShowLlmSelector(false);
          }}
        />
      </Box>
    );
  }

  // YOLO mode view
  if (viewMode === "yolo" && viewParams) {
    // Check if rpcClient supports streaming (DeadEndRpcClient)
    const streamingClient = rpcClient as unknown as DeadEndRpcClient;
    return (
      <Box flexDirection="column" flexGrow={1}>
        <YoloView
          target={viewParams.target}
          task={viewParams.task}
          rpcClient={streamingClient}
          onComplete={(result: DoneEvent) => {
            // Add result as a message and return to chat
            const resultMessage = createMessage(
              "system",
              `YOLO mode completed.\nTarget: ${result.target}\nMode: ${result.mode}`,
              "text"
            );
            addMessage(resultMessage);
            setViewMode("chat");
            setViewParams(null);
          }}
          onCancel={() => {
            const cancelMessage = createMessage(
              "system",
              "YOLO mode cancelled.",
              "text"
            );
            addMessage(cancelMessage);
            setViewMode("chat");
            setViewParams(null);
          }}
        />
      </Box>
    );
  }

  // Normal/Supervisor mode view
  if (viewMode === "normal" && viewParams) {
    const streamingClient = rpcClient as unknown as DeadEndRpcClient;
    return (
      <Box flexDirection="column" flexGrow={1}>
        <NormalView
          target={viewParams.target}
          task={viewParams.task}
          rpcClient={streamingClient}
          onComplete={(result: DoneEvent) => {
            const resultMessage = createMessage(
              "system",
              `Supervisor mode completed.\nTarget: ${result.target}\nMode: ${result.mode}`,
              "text"
            );
            addMessage(resultMessage);
            setViewMode("chat");
            setViewParams(null);
          }}
          onCancel={() => {
            const cancelMessage = createMessage(
              "system",
              "Supervisor mode cancelled.",
              "text"
            );
            addMessage(cancelMessage);
            setViewMode("chat");
            setViewParams(null);
          }}
        />
      </Box>
    );
  }

  return (
    <Box flexDirection="column" flexGrow={1}>
      {/* Messages area */}
      <Box flexDirection="column" flexGrow={1} marginBottom={1}>
        {messages.length === 0 ? (
          <Text color="gray" dimColor>
            No messages yet. Type / to see available commands...
          </Text>
        ) : (
          messages.map((msg) => (
            <Box key={msg.id} marginBottom={1} flexDirection="column">
              {msg.role === "user" ? (
                // User messages: show content with grey background (like Claude Code)
                <Box flexDirection="column">
                  <Text backgroundColor="gray" color="white">
                    {" > "}{msg.content}{" "}
                  </Text>
                  <Text color="gray" dimColor>
                    {msg.timestamp.toLocaleTimeString()}
                  </Text>
                </Box>
              ) : (
                // Assistant/System messages: show with role prefix
                <Box flexDirection="column">
                  <Box flexDirection="row" marginBottom={0}>
                    <Text
                      color={msg.role === "assistant" ? "red" : "yellow"}
                      bold
                    >
                      {msg.role === "assistant" ? "AI: " : "System: "}
                    </Text>
                    <Text
                      color={msg.type === "error" ? "red" : undefined}
                      italic={msg.type === "info"}
                    >
                      {msg.content}
                    </Text>
                  </Box>
                  <Text color="gray" dimColor>
                    {msg.timestamp.toLocaleTimeString()}
                  </Text>
                </Box>
              )}
            </Box>
          ))
        )}
        {isLoading && (
          <LoadingSpinner text="Thinking" color="red" />
        )}
      </Box>

      {/* Input area */}
      <Box
        borderStyle="round"
        borderColor="grey"
      >
        <Box flexDirection="row">
          <Text color="grey">{"> "}</Text>
          <TextInput
            value={input}
            onChange={setInput}
            onSubmit={handleSubmit}
            placeholder="Type / to see commands..."
          />
        </Box>
      </Box>

      {/* Mode and LLM indicator */}
      <Box flexDirection="row" justifyContent="space-between" marginTop={0}>
        <Box flexDirection="row">
          <Text color="gray" dimColor>Running mode: </Text>
          <Text
            color={executionMode === "yolo" ? "red" : "yellow"}
            bold
          >
            {executionMode.toUpperCase()}
          </Text>
          <Text color="gray" dimColor> (shift+tab to switch)</Text>
        </Box>
        {currentLlm && (
          <Box flexDirection="row">
            <Text color="gray" dimColor>LLM: </Text>
            <Text italic>{currentLlm.provider}{currentLlm.model ? `: ${currentLlm.model}` : ""}</Text>
          </Box>
        )}
      </Box>

      {/* Command suggestions */}
      {input.startsWith("/") && filteredCommands.length > 0 && (
        <Box flexDirection="column" marginTop={1}>
          <Text color="gray" dimColor>
            Available commands:
          </Text>
          {filteredCommands.map((cmd) => {
            const isSpecialCommand = ["run", "target", "llm", "report"].includes(cmd.name);
            const specialColor = "#FFA500";
            return (
              <Box key={cmd.name} flexDirection="column" marginTop={0}>
                <Box flexDirection="row">
                  <Text color={isSpecialCommand ? specialColor : "cyan"} bold>
                    /{cmd.name.padEnd(10)}
                  </Text>
                  <Text italic> - {cmd.description}</Text>
                </Box>
                {cmd.usage && (
                  <Text color="gray" dimColor>
                    {"           "}Usage: {cmd.usage}
                  </Text>
                )}
              </Box>
            );
          })}
        </Box>
      )}
    </Box>
  );
}

