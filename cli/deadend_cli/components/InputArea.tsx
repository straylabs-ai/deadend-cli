import { Box, Text } from "ink";
import TextInput from "ink-text-input";
import { useMemo } from "react";
import { COMMANDS } from "../types/command.ts";
import { colors } from "./colors.ts";
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
    if (!value.startsWith("/")) return [];
    const commandPart = value.slice(1).trim().toLowerCase();
    if (commandPart === "") return COMMANDS;
    return COMMANDS.filter((cmd) => {
      const nameMatch = cmd.name.toLowerCase().startsWith(commandPart);
      const aliasMatch = cmd.aliases?.some((alias) =>
        alias.toLowerCase().startsWith(commandPart)
      );
      return nameMatch || aliasMatch;
    });
  }, [value]);

  const modeColor =
    executionMode === "yolo" ? colors.input.modeYolo : colors.input.modeSupervisor;

  return (
    <Box flexDirection="column">
      {/* Input row */}
      <Box borderStyle="round" borderColor={colors.input.border}>
        <Box flexDirection="row">
          <Text color={colors.input.prompt} bold>
            {"\u276F "}
          </Text>
          <TextInput
            value={value}
            onChange={onChange}
            onSubmit={onSubmit}
            placeholder={placeholder}
          />
        </Box>
      </Box>

      {/* Status bar */}
      <Box flexDirection="row" justifyContent="space-between">
        <Box flexDirection="row">
          {/* Mode badge */}
          <Text color={modeColor} bold>
            {executionMode.toUpperCase()}
          </Text>
          <Text dimColor> (shift+tab)</Text>

          {/* Running / interrupt hint */}
          {isLoading && (
            <Text color={colors.accent} dimColor>
              {"  \u25CF Running "}
            </Text>
          )}
          {isLoading && (
            <Text dimColor italic>
              (Esc to interrupt)
            </Text>
          )}
        </Box>

        {/* LLM info */}
        {currentLlm && (
          <Box flexDirection="row">
            <Text dimColor>
              {currentLlm.provider}
              {currentLlm.model ? `: ${currentLlm.model}` : ""}
            </Text>
          </Box>
        )}
      </Box>

      {/* Command suggestions */}
      {value.startsWith("/") && filteredCommands.length > 0 && (
        <Box
          flexDirection="column"
          marginTop={1}
          borderStyle="round"
          borderColor={colors.input.border}
          paddingX={1}
        >
          {filteredCommands.map((cmd) => {
            const isSpecial = ["run", "target", "llm", "report"].includes(
              cmd.name
            );
            return (
              <Box key={cmd.name} flexDirection="row">
                <Text color={isSpecial ? colors.accent : "cyan"} bold>
                  /{cmd.name.padEnd(12)}
                </Text>
                <Text dimColor>{cmd.description}</Text>
              </Box>
            );
          })}
        </Box>
      )}
    </Box>
  );
}
