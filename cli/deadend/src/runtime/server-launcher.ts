import { join } from "node:path";
import type { CliArgs } from "../cli/args.ts";
import { getCacheDirPath, getLogsDirPath } from "./app-paths.ts";

// Only forward env vars that the Python RPC server actually needs.
// Avoids leaking unrelated secrets (SSH keys, CI tokens, etc.) to the child process.
const FORWARDED_ENV_KEYS = [
  "PATH",
  "HOME",
  "USER",
  "LANG",
  "TERM",
  "SHELL",
  "TMPDIR",
  "XDG_CACHE_HOME",
  "XDG_CONFIG_HOME",
  "XDG_DATA_HOME",
  "VIRTUAL_ENV",
  "CONDA_PREFIX",
  "DEADEND_HOME",
  "DEADEND_RPC_BINARY",
  // Provider API keys the server needs
  "OPENAI_API_KEY",
  "ANTHROPIC_API_KEY",
  "GOOGLE_API_KEY",
  "GEMINI_API_KEY",
  // Docker
  "DOCKER_HOST",
  // Database
  "DATABASE_URL",
  "POSTGRES_HOST",
  "POSTGRES_PORT",
  "POSTGRES_USER",
  "POSTGRES_PASSWORD",
  "POSTGRES_DB",
];

function pickEnv(): Record<string, string> {
  const result: Record<string, string> = {};
  for (const key of FORWARDED_ENV_KEYS) {
    if (process.env[key]) {
      result[key] = process.env[key]!;
    }
  }
  return result;
}

export interface RpcLaunchConfig {
  pythonCommand: string;
  commandArgs: string[];
  cwd: string;
  env: Record<string, string>;
  logFile: string;
  modeLabel: string;
  detail: string;
}

export async function resolveRpcLaunchConfig(
  args: CliArgs,
): Promise<RpcLaunchConfig> {
  const logFile = await createLogFilePath();
  const cacheDir = await getCacheDirPath();
  const uvCacheDir = join(cacheDir, "uv-cache");

  if (args.dev || args.debug) {
    const pythonPackageDir = resolvePythonPackageDir();
    return {
      pythonCommand: "uv",
      commandArgs: [
        "run",
        "python",
        "-m",
        "deadend_cli.jsonrpc_server",
        "--log-file",
        logFile,
      ],
      cwd: pythonPackageDir,
      env: {
        ...pickEnv(),
        UV_CACHE_DIR: uvCacheDir,
        ...(args.debug ? { DEBUG: "true" } : {}),
      },
      logFile,
      modeLabel: args.debug ? "runtime=debug" : "runtime=dev",
      detail: "",
    };
  }

  const rpcBinary =
    process.env.DEADEND_RPC_BINARY ??
    join(await getCacheDirPath(), "bin", "deadend.sh");

  return {
    pythonCommand: rpcBinary,
    commandArgs: ["--log-file", logFile],
    cwd: process.cwd(),
    env: pickEnv(),
    logFile,
    modeLabel: "runtime=installed",
    detail: `${rpcBinary} --log-file ${logFile}`,
  };
}

async function createLogFilePath(): Promise<string> {
  const logDir = await getLogsDirPath();
  return join(logDir, `rpc-server-${Date.now()}.log`);
}

function resolvePythonPackageDir(): string {
  const repoRoot = new URL("../../../../", import.meta.url);
  return new URL("deadend_cli", repoRoot).pathname;
}
