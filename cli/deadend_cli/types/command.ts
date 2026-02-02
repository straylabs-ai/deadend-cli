export interface Command {
  name: string;
  description: string;
  usage?: string;
  aliases?: string[];
}

export interface ParsedCommand {
  command: string;
  args: string[];
  raw: string;
}

export interface CommandHandler {
  (args: string[]): Promise<string> | string;
}

export interface CommandRegistry {
  [key: string]: CommandHandler;
}

export const COMMANDS: Command[] = [
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
    description: "Generate security assessment report with templating",
    usage: "/report [generate|template|help] [--template <name>] [--format <format>] [--output <file>]",
  },
];

