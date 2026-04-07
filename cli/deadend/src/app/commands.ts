export interface Command {
  name: string;
  description: string;
  usage: string;
  aliases?: string[];
}

export interface ParsedCommand {
  command: string;
  args: string[];
}

export const COMMANDS: Command[] = [
  {
    name: "help",
    description: "Show available commands",
    usage: "/help",
  },
  {
    name: "clear",
    description: "Clear chat history",
    usage: "/clear",
  },
  {
    name: "exit",
    description: "Exit the application",
    usage: "/exit",
    aliases: ["quit", "q"],
  },
  {
    name: "target",
    description: "Set the target and verify it is reachable",
    usage: "/target <url|hostname>",
  },
  {
    name: "report",
    description: "Summarize and report",
    usage: "/report",
  },
  {
    name: "validation",
    description: "Show or change validation mode (flag, judge, ctf, recon)",
    usage: "/validation [preset] [--format <FORMAT>] [--pattern <REGEX>]",
    aliases: ["val"],
  },
];

export function parseCommand(input: string): ParsedCommand | null {
  const trimmed = input.trim();
  if (!trimmed.startsWith("/")) {
    return null;
  }

  const parts = trimmed.slice(1).split(/\s+/);
  const command = parts[0]?.toLowerCase() ?? "";
  return {
    command,
    args: parts.slice(1),
  };
}

export function findCommandSuggestions(input: string): Command[] {
  if (!input.startsWith("/")) {
    return [];
  }

  const partial = input.slice(1).trim().toLowerCase();
  if (partial.length === 0) {
    return COMMANDS;
  }

  return COMMANDS.filter((command) => {
    if (command.name.startsWith(partial)) {
      return true;
    }

    return command.aliases?.some((alias) => alias.startsWith(partial)) ?? false;
  });
}

export function formatHelpText(): string {
  return [
    "Available commands:",
    ...COMMANDS.map((command) => `\n${command.usage.padEnd(18)} \n${command.description}`),
  ].join("\n");
}
