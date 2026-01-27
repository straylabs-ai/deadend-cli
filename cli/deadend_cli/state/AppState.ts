import { Presetup } from "../components/Presetup.tsx";

type PresetupStep = 
    | "provider"
    | "model"
    | "api_key"
    | "base_url"
    | "embedding_provider"
    | "embedding_model"
    | "confirm";


type ViewType = 
    | "chat"
    | "settings"
    | "llm_selector"
export const ViewType = {
    chat : "chat",
    settings : "settings",
    llm_selector : "llm_selector"
} as const;

export const AppStates = {
    STARTING: "STARTING",
    INITIALIZING: "INITIALIZING",
    CHECK_CONFIG: "CHECK_CONFIG",
    PRESETUP: "PRESETUP",
    READY: "READY",
    
}
type AppState =
    | { type: "STARTING" }
    | { type: "INITIALIZING"; progress: string; components: InitResult[] }
    | { type: "CHECK_CONFIG" }
    | { type: "PRESETUP"; step: PresetupStep } 
    | { type: "READY"; view: ViewType }          
    | { type: "ERROR"; error: string; recoverable: boolean }
    | { type: "EXITING" };

