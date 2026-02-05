import type { ParsedCommand } from "../../types/command.ts";

export function parseCommand(input: string): ParsedCommand | null {
  const trimmed = input.trim();
  
  // Check if input starts with /
  if (!trimmed.startsWith("/")) {
    return null;
  }

  // Remove leading / and split by spaces
  const parts = trimmed.slice(1).split(/\s+/);
  const command = parts[0]?.toLowerCase() || "";
  const args = parts.slice(1);

  return {
    command,
    args,
    raw: trimmed,
  };
}

export function isCommand(input: string): boolean {
  return input.trim().startsWith("/");
}

