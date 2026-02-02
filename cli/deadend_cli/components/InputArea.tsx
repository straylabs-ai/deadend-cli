import { Box, Text } from "ink";
import TextInput from "ink-text-input";
import { useMemo } from "react";
import { COMMANDS } from "../types/command.ts";
import type { ExecutionMode } from "./chat.tsx";

export interface InputAreaProps {
  /** Current input value */
  value: string;
  /** Input change handler */
  onChange: (value: string) => void;
  /** Submit handler */
  onSubmit: () => void;
  /** Whether a task is currently running */
  isLoading?: boolean;
  /** Current execution mode */
  executionMode: ExecutionMode;
  /** Current LLM info */
  currentLlm?: { provider: string; model: string | null } | null;
  /** Placeholder text */
  placeholder?: string;
}

export function InputArea({
  value,
  onChange,
  onSubmit,
  isLoading = false,
  executionMode,
  currentLlm,
  placeholder = "Type / to see commands...",
}: InputAreaProps) {
  // Filter commands based on input
  const filteredCommands = useMemo(() => {
    if (!value.startsWith("/")) {
      return [];
    }

    const commandPart = value.slice(1).trim().toLowerCase();
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
  }, [value]);

  return (
    <Box flexDirection="column">
      {/* Text input */}
      <Box borderStyle="round" borderColor="grey">
        <Box flexDirection="row">
          <Text color="grey">{"> "}</Text>
          <TextInput
            value={value}
            onChange={onChange}
            onSubmit={onSubmit}
            placeholder={placeholder}
          />
        </Box>
      </Box>

      {/* Mode and LLM indicator */}
      <Box flexDirection="row" justifyContent="space-between" marginTop={0}>
        <Box flexDirection="row">
          <Text color="gray" dimColor>
            Running mode:{" "}
          </Text>
          <Text color={executionMode === "yolo" ? "red" : "yellow"} bold>
            {executionMode.toUpperCase()}
          </Text>
          <Text color="gray" dimColor>
            {" "}
            (shift+tab to switch)
          </Text>
          {isLoading && (
            <Text color="cyan" dimColor>
              {" "}
              | Running...
            </Text>
          )}
        </Box>
        {currentLlm && (
          <Box flexDirection="row">
            <Text color="gray" dimColor>
              LLM:{" "}
            </Text>
            <Text italic>
              {currentLlm.provider}
              {currentLlm.model ? `: ${currentLlm.model}` : ""}
            </Text>
          </Box>
        )}
      </Box>

      {/* Command suggestions */}
      {value.startsWith("/") && filteredCommands.length > 0 && (
        <Box flexDirection="column" marginTop={1}>
          <Text color="gray" dimColor>
            Available commands:
          </Text>
          {filteredCommands.map((cmd) => {
            const isSpecialCommand = ["run", "target", "llm", "report"].includes(
              cmd.name
            );
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
