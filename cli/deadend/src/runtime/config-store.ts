import { chmod, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { getAppDirPath, isNotFoundError } from "./app-paths.ts";

export interface ProviderSpec {
  provider: string;
  model: string;
  apiKey?: string;
  baseUrl?: string;
  typeModel?: "embeddings" | null;
  vecDim?: number | null;
}

export interface AppConfig {
  configuredModels: ProviderSpec[];
}

interface ProviderConfigEntry {
  provider: string;
  model_name: string;
  api_key: string | null;
  base_url: string | null;
  type_model: string | null;
  vec_dim: number | null;
}

interface ConfigJson {
  provider?: Record<string, ProviderConfigEntry>;
  [key: string]: unknown;
}

export async function getConfigDirPath(): Promise<string> {
  return getAppDirPath();
}

export async function getConfigFilePath(): Promise<string> {
  return join(await getConfigDirPath(), "config.json");
}

export async function ensureConfigDir(): Promise<void> {
  await getConfigDirPath();
}

export async function loadAppConfig(): Promise<AppConfig> {
  try {
    const content = await readFile(await getConfigFilePath(), "utf8");
    return parseConfig(JSON.parse(content) as ConfigJson);
  } catch (error) {
    if (isNotFoundError(error)) {
      return { configuredModels: [] };
    }

    throw error;
  }
}

export async function saveModelConfig(models: ProviderSpec[]): Promise<void> {
  await ensureConfigDir();
  const configFilePath = await getConfigFilePath();

  let existing: ConfigJson = {};
  try {
    const content = await readFile(configFilePath, "utf8");
    existing = JSON.parse(content) as ConfigJson;
  } catch (error) {
    if (!isNotFoundError(error)) {
      throw error;
    }
  }

  const providerEntries: Record<string, ProviderConfigEntry> = {
    ...(existing.provider ?? {}),
  };

  for (const model of models) {
    const key = `${model.provider}:${model.model}`;
    providerEntries[key] = {
      provider: model.provider,
      model_name: model.model,
      api_key: model.apiKey ?? null,
      base_url: model.baseUrl ?? null,
      type_model: model.typeModel ?? null,
      vec_dim: model.vecDim ?? null,
    };
  }

  const payload: ConfigJson = {
    ...existing,
    provider: providerEntries,
  };

  await writeFile(configFilePath, JSON.stringify(payload, null, 2));
  await chmod(configFilePath, 0o600);
}

export function hasRegularModel(config: AppConfig): boolean {
  return config.configuredModels.some((model) => model.typeModel !== "embeddings");
}

export function hasEmbeddingModel(config: AppConfig): boolean {
  return config.configuredModels.some((model) => model.typeModel === "embeddings");
}

export function getDefaultChatModel(config: AppConfig): ProviderSpec | null {
  return config.configuredModels.find((model) => model.typeModel !== "embeddings") ?? null;
}

function parseConfig(config: ConfigJson): AppConfig {
  const configuredModels: ProviderSpec[] = [];

  for (const entry of Object.values(config.provider ?? {})) {
    configuredModels.push({
      provider: entry.provider,
      model: entry.model_name,
      apiKey: entry.api_key ?? undefined,
      baseUrl: entry.base_url ?? undefined,
      typeModel: entry.type_model === "embeddings" ? "embeddings" : null,
      vecDim: entry.vec_dim,
    });
  }

  return { configuredModels };
}

