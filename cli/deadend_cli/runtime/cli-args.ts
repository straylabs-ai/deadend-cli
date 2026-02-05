import { Command } from "commander";

export type Mode = "hacker" | "yolo";

export interface CliArgs {
  mode?: Mode;
  codebase?: string;
  target?: string;
  prompt?: string;
  help: boolean;
}

const program = new Command();

program
  .name("deadend")
  .description("Deadend CLI - Agentic pentest tooling")
  .version("0.1.0")
  .option("-m, --mode <mode>", "Set the mode (hacker | yolo)", "hacker")
  .option("-c, --codebase <path>", "Specify the codebase destination folder")
  .option("-t, --target <url>", "Set the target URL for pentesting")
  .option("-p, --prompt <text>", "Initial prompt to run on startup")
  .allowUnknownOption(false)
  .configureOutput({
    writeErr: (str: string) => console.error(str),
    writeOut: (str: string) => console.log(str),
  });

export function parseArgs(): CliArgs {
  program.parse(Deno.args, { from: "user" });
  const opts = program.opts();

  // Validate mode
  if (opts.mode && opts.mode !== "hacker" && opts.mode !== "yolo") {
    console.error(`Error: --mode must be either "hacker" or "yolo"`);
    Deno.exit(1);
  }

  return {
    mode: opts.mode as Mode | undefined,
    codebase: opts.codebase,
    target: opts.target,
    prompt: opts.prompt,
    help: false,
  };
}

export function showHelp(): void {
  program.outputHelp();
}

