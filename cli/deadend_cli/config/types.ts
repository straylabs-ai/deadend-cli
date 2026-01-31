export interface ProviderSpec {
    provider: string,
    model: string,
    api_url?: string,
    base_url?: string,
    type_model?: "embeddings" | null
    vec_dim?: number | null
}

export interface ProviderConfigEntry {
    provider: string;
    model_name: string;
    api_key: string | null;
    base_url: string | null;
    type_model: string | null;
    vec_dim: number | null;
}

export interface ConfigJson {
    [key: string]: unknown;
    provider?: Record<string, ProviderConfigEntry>;
}

export interface AppConfig {
    configured_models: ProviderSpec[]
}

export interface EmbeddingConfig {
    provider: string;
    model: string;
    api_key?: string;
    base_url?: string;
    vec_dim?: number;
    auto_embed: boolean;
}

export interface EmbeddingDefaultSpec {
    provider: string;
    model: string;
}

export interface DefaultSettings {
    provider?: string
    model?: string

    agentMode: "yolo" | "supervisor" | "plan" | "ask";
    showComponentStatus: boolean;
    autoCollapseStatus: boolean;

    lastTarget: string;
    commandHistory: string[];
    
    embedding?: EmbeddingDefaultSpec;
}