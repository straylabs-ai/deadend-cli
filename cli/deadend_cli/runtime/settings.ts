/**
 * CLI Settings Management
 *
 * Manages settings.json which stores CLI-specific preferences like:
 * - Default LLM provider
 * - Default model name
 * - Execution mode preferences
 */

import { logger } from "./logger.ts";

export interface CliSettings {
  /** Default LLM provider (openai, anthropic, gemini, bedrock, openrouter, local) */
  provider?: string;
  /** Default model name */
  model?: string;
  /** Default execution mode (yolo, supervisor) */
  executionMode?: "yolo" | "supervisor";
  /** Default target URL */
  defaultTarget?: string;
}

const DEFAULT_SETTINGS: CliSettings = {
  provider: "openai",
  executionMode: "yolo",
};

function getSettingsDir(): string {
  const homeDir = Deno.env.get("HOME") || Deno.env.get("USERPROFILE") || "~";
  return `${homeDir}/.cache/deadend`;
}

function getSettingsFile(): string {
  return `${getSettingsDir()}/settings.json`;
}

/**
 * Load settings from settings.json
 * Returns default settings if file doesn't exist
 */
export async function loadSettings(): Promise<CliSettings> {
  try {
    const filePath = getSettingsFile();
    const content = await Deno.readTextFile(filePath);
    const parsed = JSON.parse(content) as CliSettings;
    return { ...DEFAULT_SETTINGS, ...parsed };
  } catch (error) {
    if (error instanceof Deno.errors.NotFound) {
      return { ...DEFAULT_SETTINGS };
    }
    logger.error("Failed to load settings:", error);
    return { ...DEFAULT_SETTINGS };
  }
}

/**
 * Save settings to settings.json
 */
export async function saveSettings(settings: CliSettings): Promise<void> {
  try {
    const dir = getSettingsDir();
    await Deno.mkdir(dir, { recursive: true });

    const filePath = getSettingsFile();
    const content = JSON.stringify(settings, null, 2);
    await Deno.writeTextFile(filePath, content);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Failed to save settings: ${message}`);
  }
}

/**
 * Update specific settings (merge with existing)
 */
export async function updateSettings(
  updates: Partial<CliSettings>
): Promise<CliSettings> {
  const current = await loadSettings();
  const updated = { ...current, ...updates };
  await saveSettings(updated);
  return updated;
}

/**
 * Get the settings file path
 */
export function getSettingsPath(): string {
  return getSettingsFile();
}

/**
 * Check if settings file exists
 */
export async function settingsExist(): Promise<boolean> {
  try {
    const filePath = getSettingsFile();
    const stat = await Deno.stat(filePath);
    return stat.isFile;
  } catch {
    return false;
  }
}
