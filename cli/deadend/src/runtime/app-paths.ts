import { mkdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

let appDirPromise: Promise<string> | null = null;

export function getDefaultAppDirPath(): string {
  if (process.env.DEADEND_HOME) {
    return process.env.DEADEND_HOME;
  }

  if (process.env.XDG_CACHE_HOME) {
    return join(process.env.XDG_CACHE_HOME, "deadend");
  }

  const homeDir = process.env.HOME ?? process.env.USERPROFILE;
  if (homeDir) {
    return join(homeDir, ".cache", "deadend");
  }

  return join(tmpdir(), "deadend");
}

export async function getAppDirPath(): Promise<string> {
  appDirPromise ??= resolveWritableAppDir();
  return appDirPromise;
}

export async function getLogsDirPath(): Promise<string> {
  const logsDirPath = join(await getAppDirPath(), "logs");
  await mkdir(logsDirPath, { recursive: true });
  return logsDirPath;
}

async function resolveWritableAppDir(): Promise<string> {
  const candidates = uniquePaths([
    process.env.DEADEND_HOME,
    process.env.XDG_CACHE_HOME ? join(process.env.XDG_CACHE_HOME, "deadend") : undefined,
    getDefaultAppDirPath(),
    join(tmpdir(), "deadend"),
  ]);

  for (const candidate of candidates) {
    if (await isWritableDirectory(candidate)) {
      return candidate;
    }
  }

  throw new Error(
    `Unable to find a writable deadend state directory. Tried: ${candidates.join(", ")}`,
  );
}

async function isWritableDirectory(dirPath: string): Promise<boolean> {
  try {
    await mkdir(dirPath, { recursive: true });
    const probePath = join(dirPath, `.write-test-${process.pid}-${Date.now()}`);
    await writeFile(probePath, "ok");
    await rm(probePath, { force: true });
    return true;
  } catch {
    return false;
  }
}

function uniquePaths(paths: Array<string | undefined>): string[] {
  return [...new Set(paths.filter((value): value is string => Boolean(value)))];
}

export function isNotFoundError(error: unknown): boolean {
  return (
    error instanceof Error &&
    "code" in error &&
    (error as NodeJS.ErrnoException).code === "ENOENT"
  );
}
