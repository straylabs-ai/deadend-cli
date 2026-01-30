import type { InitResult } from "../types/rpc.ts";

type PresetupModelStep = 
    | "provider"
    | "model"
    | "api_key"
    | "base_url"
    | "confirm";

type PresetupEmbeddingModel =
    | "provider"
    | "embedding_model"
    | "api_key"
    | "base_url"
    | "confirm"

type ViewType = 
    | "chat"
    | "settings"
    | "llm_selector"

type AppState =
    | { type: "STARTING" }
    | { type: "INITIALIZING"; progress: string; components: InitResult[] }
    | { type: "CHECK_CONFIG" }
    | { type: "PRESETUP"; step: PresetupModelStep } 
    | { type: "READY"; view: ViewType }          
    | { type: "ERROR"; error: string; recoverable: boolean }
    | { type: "EXITING" };

