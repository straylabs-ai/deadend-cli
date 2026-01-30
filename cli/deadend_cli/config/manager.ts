import { AppConfig, DefaultSettings, ProviderSpec, ConfigJson, ProviderConfigEntry } from "./types.ts";
import { getConfigFile, getConfigDirPath } from "../lib/config.ts";

class ConfigManager {
    private config: AppConfig | null = null;
    private cliSettings: DefaultSettings | null = null;

    async load(): Promise<void> {
        try {
            const configPath = getConfigFile();
            const content = await Deno.readTextFile(configPath);
            const parsed = JSON.parse(content) as ConfigJson;

            // Extract configured models from JSON
            const configuredModels: ProviderSpec[] = [];

            // Check for provider section in JSON
            if (parsed.provider && typeof parsed.provider === "object") {
                const providers = parsed.provider as Record<string, ProviderConfigEntry>;
                
                for (const [_key, config] of Object.entries(providers)) {
                    if (typeof config === "object" && config !== null) {
                        const spec: ProviderSpec = {
                            provider: config.provider,
                            model: config.model_name,
                        };

                        if (config.api_key) {
                            spec.api_url = config.api_key;
                        }
                        if (config.base_url) {
                            spec.base_url = config.base_url;
                        }
                        if (config.type_model === "embeddings") {
                            spec.type_model = "embeddings";
                        }
                        if (config.vec_dim !== null && config.vec_dim !== undefined) {
                            spec.vec_dim = config.vec_dim;
                        }

                        if (spec.model) {
                            configuredModels.push(spec);
                        }
                    }
                }
            }

            this.config = { configured_models: configuredModels };
        } catch (error) {
            if (error instanceof Deno.errors.NotFound) {
                this.config = { configured_models: [] };
            } else {
                throw error;
            }
        }
        
        this.cliSettings = await this.loadDefaultSettings();
    }

    async loadDefaultSettings(): Promise<DefaultSettings> {
        try {
            const settingsPath = `${getConfigDirPath()}/settings.json`;
            const content = await Deno.readTextFile(settingsPath);
            return JSON.parse(content) as DefaultSettings;
        } catch (error) {
            if (error instanceof Deno.errors.NotFound) {
                // Return default settings
                return {
                    agentMode: "supervisor",
                    showComponentStatus: true,
                    autoCollapseStatus: false,
                    lastTarget: "",
                    commandHistory: [],
                };
            }
            throw error;
        }
    }

    async saveConfig(config: AppConfig): Promise<void> {
        const configPath = getConfigFile();
        const configDir = getConfigDirPath();
        
        // Ensure directory exists
        await Deno.mkdir(configDir, { recursive: true });

        // Load existing config to preserve top-level keys
        let existingConfig: ConfigJson = {};
        try {
            const existingContent = await Deno.readTextFile(configPath);
            existingConfig = JSON.parse(existingContent) as ConfigJson;
        } catch {
            // File doesn't exist or is invalid, start fresh
            existingConfig = {};
        }

        // Build provider object with "provider:model_name" keys
        const providerConfig: Record<string, ProviderConfigEntry> = {};
        
        for (const model of config.configured_models) {
            const key = `${model.provider}:${model.model}`;
            providerConfig[key] = {
                provider: model.provider,
                model_name: model.model,
                api_key: model.api_url || null,
                base_url: model.base_url || null,
                type_model: model.type_model || null,
                vec_dim: model.vec_dim || null,
            };
        }

        // Merge with existing config, preserving top-level keys
        const configJson: ConfigJson = {
            ...existingConfig,
            provider: {
                ...(existingConfig.provider as Record<string, ProviderConfigEntry> || {}),
                ...providerConfig,
            },
        };

        await Deno.writeTextFile(configPath, JSON.stringify(configJson, null, 2));
    }

    async saveDefaultSettings(settings: DefaultSettings): Promise<void> {
        const settingsPath = `${getConfigDirPath()}/settings.json`;
        const configDir = getConfigDirPath();
        
        // Ensure directory exists
        await Deno.mkdir(configDir, { recursive: true });
        
        await Deno.writeTextFile(settingsPath, JSON.stringify(settings, null, 2));
    }

    getConfig(): AppConfig | null {
        return this.config;
    }

    getDefaultSettings(): DefaultSettings | null {
        return this.cliSettings;
    }
}

export const configManager = new ConfigManager();
