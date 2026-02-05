import type { ProviderConfigEntry, ConfigJson } from "../config/types.ts";

function getConfigDir(): string {
  const homeDir = Deno.env.get("HOME") || Deno.env.get("USERPROFILE") || "~";
  return `${homeDir}/.cache/deadend`;
}

export function getConfigFile(): string {
  return `${getConfigDir()}/config.json`;
}

export async function configExists(): Promise<boolean> {
  try {
    // Check if the file exists in the file system
    const filePath = getConfigFile();
    const stat = await Deno.stat(filePath);
    // Verify it's actually a file (not a directory)
    return stat.isFile;
  } catch (error) {
    // If the file doesn't exist, Deno.stat throws NotFound error
    if (error instanceof Deno.errors.NotFound) {
      return false;
    }
    // For other errors (permissions, etc.), assume file doesn't exist
    return false;
  }
}

export function getConfigPath(): string {
  return getConfigFile();
}

export function getConfigDirPath(): string {
  return getConfigDir();
}


export async function createConfigDir(): Promise<void> {
  try {
    const dir = getConfigDir();
    await Deno.mkdir(dir, { recursive: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Failed to create config directory: ${message}`);
  }
}

interface ConfigOptions {
  providerType?: "proprietary" | "local";
  providerName?: string;
  modelName?: string;
  apiKey?: string;
  baseUrl?: string;
}

export async function createDefaultConfig(options?: ConfigOptions): Promise<void> {
  await createConfigDir();
  
  const configObject: ConfigJson = {};

  if (options?.providerName && options?.modelName) {
    const providerName = options.providerName.toLowerCase();
    const key = `${providerName}:${options.modelName}`;
    
    const providerEntry: ProviderConfigEntry = {
      provider: providerName,
      model_name: options.modelName,
      api_key: options.apiKey || null,
      base_url: options.baseUrl || null,
      type_model: null,
      vec_dim: null,
    };

    configObject.provider = {
      [key]: providerEntry,
    };
  }

  try {
    const filePath = getConfigFile();
    // Write as JSON format
    const configContent = JSON.stringify(configObject, null, 2);
    await Deno.writeTextFile(filePath, configContent);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Failed to create config file: ${message}`);
  }
}

