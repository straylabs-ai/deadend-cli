export type AppMode = "supervisor" | "yolo";

export interface CliArgs {
  help: boolean;
  mode: AppMode;
  dev: boolean;
  debug: boolean;
  codebase?: string;
  target?: string;
  prompt?: string;
  proxy?: string;
}

const DEFAULT_MODE: AppMode = "supervisor";

export function parseArgs(argv: string[]): CliArgs {
  const args: CliArgs = {
    help: false,
    mode: DEFAULT_MODE,
    dev: false,
    debug: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];

    switch (token) {
      case "--help":
      case "-h":
        args.help = true;
        break;
      case "--mode":
      case "-m":
        args.mode = parseMode(readValue(argv, index, token));
        index += 1;
        break;
      case "--dev":
        args.dev = true;
        break;
      case "--debug":
        args.dev = true;
        args.debug = true;
        break;
      case "--codebase":
      case "-c":
        args.codebase = readValue(argv, index, token);
        index += 1;
        break;
      case "--target":
      case "-t":
        args.target = readValue(argv, index, token);
        index += 1;
        break;
      case "--prompt":
      case "-p":
        args.prompt = readValue(argv, index, token);
        index += 1;
        break;
      case "--proxy":
        args.proxy = readValue(argv, index, token);
        index += 1;
        break;
      default:
        throw new Error(`Unknown argument: ${token}`);
    }
  }

  return args;
}

export function formatHelp(): string {
  return [
    "deadend",
    "",
    "OpenTUI rewrite of the deadend CLI.",
    "",
    "Usage:",
    "  bun run index.ts [options]",
    "",
    "Options:",
    "  -h, --help            Show this help message",
    "  -m, --mode <mode>     Set the execution mode: supervisor | yolo",
    "      --dev             Run the Python JSON-RPC server from uv",
    "      --debug           Same as --dev, with DEBUG=true",
    "  -c, --codebase <dir>  Attach codebase metadata to the session header",
    "  -t, --target <value>  Display the active target in the header",
    "  -p, --prompt <value>  Seed the session with an initial prompt",
    "      --proxy <url>     Route Playwright send_payload traffic through an HTTP proxy",
  ].join("\n");
}

function readValue(argv: string[], index: number, flag: string): string {
  const value = argv[index + 1];

  if (!value || value.startsWith("-")) {
    throw new Error(`Missing value for ${flag}`);
  }

  return value;
}

function parseMode(value: string): AppMode {
  if (value === "supervisor" || value === "yolo") {
    return value;
  }

  throw new Error(`Invalid mode: ${value}. Expected "supervisor" or "yolo".`);
}
