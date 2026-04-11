import { chmod, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { getConfigDirPath } from "./config-store.ts";
import { isNotFoundError } from "./app-paths.ts";

export interface EmbeddingDefaults {
  provider: string;
  model: string;
}

export interface CliSettings {
  provider?: string;
  model?: string;
  executionMode?: "yolo" | "supervisor";
  defaultTarget?: string;
  embedding?: EmbeddingDefaults;
}

const DEFAULT_SETTINGS: Required<Pick<CliSettings, "executionMode">> = {
  executionMode: "yolo",
};

export async function getSettingsFilePath(): Promise<string> {
  return join(await getConfigDirPath(), "settings.json");
}

export async function loadSettings(): Promise<CliSettings> {
  try {
    const content = await readFile(await getSettingsFilePath(), "utf8");
    const parsed = JSON.parse(content) as CliSettings;
    return {
      ...DEFAULT_SETTINGS,
      ...parsed,
    };
  } catch (error) {
    if (isNotFoundError(error)) {
      return { ...DEFAULT_SETTINGS };
    }

    throw error;
  }
}

export async function saveSettings(settings: CliSettings): Promise<void> {
  await getConfigDirPath();
  const filePath = await getSettingsFilePath();
  await writeFile(filePath, JSON.stringify(settings, null, 2));
  await chmod(filePath, 0o600);
}

export async function updateSettings(
  updates: Partial<CliSettings>,
): Promise<CliSettings> {
  const current = await loadSettings();
  const next = {
    ...current,
    ...updates,
  };

  await saveSettings(next);
  return next;
}

