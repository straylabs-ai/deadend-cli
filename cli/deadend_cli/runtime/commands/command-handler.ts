import type { CommandRegistry } from "../../types/command.ts";
import { handleClear } from "./handlers/clear.ts";
import { handleExit } from "./handlers/exit.ts";
import { handleTarget } from "./handlers/target.ts";
import { handleReport } from "./handlers/report.ts";

export const commandRegistry: CommandRegistry = {
  clear: handleClear,
  exit: handleExit,
  quit: handleExit,
  q: handleExit,
  target: handleTarget,
  report: handleReport,
};

export async function executeCommand(
  command: string,
  args: string[]
): Promise<string> {
  const handler = commandRegistry[command.toLowerCase()];
  
  if (!handler) {
    return `Unknown command: /${command}. Type / to see available commands.`;
  }

  try {
    return await handler(args);
  } catch (error) {
    return `Error executing command: ${error instanceof Error ? error.message : "Unknown error"}`;
  }
}

