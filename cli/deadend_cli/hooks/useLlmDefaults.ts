import { useState, useEffect } from "react";
import { configManager } from "../config/manager.ts";

export interface LlmDefaults {
  provider: string;
  model: string | null;
}

/**
 * Hook to get default LLM provider and model from client-side config.
 * 
 * Reads defaults from config manager (settings.json).
 * Returns null if no defaults are available.
 * 
 * @returns Object with provider and model, or null if not yet loaded or not configured
 */
export function useLlmDefaults(): {defaults: LlmDefaults | null, isLoading: boolean } {
  const [defaults, setDefaults] = useState<LlmDefaults | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const loadDefaults = async () => {
      setIsLoading(true)
      try {
        // Ensure config manager is loaded
        try {
          await configManager.load();
        } catch {
          // Config manager load failed, continue with fallbacks
        }

        // Get from client-side config manager
        const settings = configManager.getDefaultSettings();
        
        if (settings?.provider) {
          // Use client-side defaults
          setDefaults({
            provider: settings.provider,
            model: settings.model || null,
          });
        } else {
          // No defaults available
          setDefaults(null);
        }
      } catch (_error) {
        // Error loading defaults, return null
        setDefaults(null);
      } finally {
        setIsLoading(false)
      }
    };

    loadDefaults();
  }, []);

  return {defaults, isLoading};
}

