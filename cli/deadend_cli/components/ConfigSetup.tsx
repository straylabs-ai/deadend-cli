import { useState, useCallback } from "react";
import { Box, Text, useInput } from "ink";
import TextInput from "ink-text-input";
import { getConfigFile, createConfigDir } from "../runtime/config.ts";

interface ConfigSetupProps {
  onComplete: () => void;
}

type ModelProvider = "openai" | "anthropic" | "gemini" | "openrouter" | "local";

interface ModelConfig {
  provider: ModelProvider;
  apiKey?: string;
  model?: string;
  baseUrl?: string;
}

export function ConfigSetup({ onComplete }: ConfigSetupProps) {
  const [step, setStep] = useState(0);
  const [selectedModels, setSelectedModels] = useState<Set<ModelProvider>>(new Set());
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const [currentModelIndex, setCurrentModelIndex] = useState(0);
  const [modelConfigs, setModelConfigs] = useState<ModelConfig[]>([]);
  const [currentInput, setCurrentInput] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const modelProviders: ModelProvider[] = ["openai", "anthropic", "gemini", "openrouter", "local"];

  const toggleModel = useCallback((provider: ModelProvider) => {
    setSelectedModels((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(provider)) {
        newSet.delete(provider);
      } else {
        newSet.add(provider);
      }
      return newSet;
    });
  }, []);

  const handleModelSelection = useCallback(() => {
    if (selectedModels.size === 0) {
      setError("Please select at least one model provider");
      return;
    }
    
    // Initialize model configs for selected models
    const configs: ModelConfig[] = Array.from(selectedModels).map((provider) => ({
      provider,
    }));
    setModelConfigs(configs);
    setCurrentModelIndex(0);
    setStep(1);
    setError(null);
  }, [selectedModels]);

  // Handle arrow key navigation for model selection
  useInput((input, key) => {
    if (step === 0) {
      if (key.upArrow) {
        setHighlightedIndex((prev) => (prev > 0 ? prev - 1 : modelProviders.length - 1));
        setError(null);
      } else if (key.downArrow) {
        setHighlightedIndex((prev) => (prev < modelProviders.length - 1 ? prev + 1 : 0));
        setError(null);
      } else if (input === " " || input === "\t") {
        // Toggle selection on Space
        toggleModel(modelProviders[highlightedIndex]);
        setError(null);
      } else if (key.return) {
        // Proceed to next step on Enter
        handleModelSelection();
      }
    }
  });

  const handleModelConfig = useCallback(async () => {
    if (!currentInput.trim()) {
      setError("This field is required");
      return;
    }

    const currentModel = modelConfigs[currentModelIndex];
    const updatedConfigs = [...modelConfigs];
    
    if (currentModel.provider === "local") {
      if (!currentModel.baseUrl) {
        // First input is base_url for local
        updatedConfigs[currentModelIndex] = {
          ...currentModel,
          baseUrl: currentInput.trim(),
        };
      } else if (!currentModel.model) {
        // Second input is model name
        updatedConfigs[currentModelIndex] = {
          ...currentModel,
          model: currentInput.trim(),
        };
      }
    } else {
      if (!currentModel.apiKey) {
        // First input is API key (for non-local models)
        updatedConfigs[currentModelIndex] = {
          ...currentModel,
          apiKey: currentInput.trim(),
        };
      } else if (!currentModel.model) {
        // Second input is model name
        updatedConfigs[currentModelIndex] = {
          ...currentModel,
          model: currentInput.trim(),
        };
      }
    }

    setModelConfigs(updatedConfigs);
    setCurrentInput("");

    // Check if we need to move to next model
    const currentConfig = updatedConfigs[currentModelIndex];
    const isComplete = currentConfig.provider === "local"
      ? currentConfig.baseUrl && currentConfig.model
      : currentConfig.apiKey && currentConfig.model;

    if (isComplete) {
      if (currentModelIndex < updatedConfigs.length - 1) {
        setCurrentModelIndex(currentModelIndex + 1);
        setError(null);
      } else {
        // All models configured, save config
        await saveConfig(updatedConfigs);
      }
    } else {
      setError(null);
    }
  }, [currentInput, currentModelIndex, modelConfigs]);

  const saveConfig = useCallback(async (configs: ModelConfig[]) => {
    setIsSaving(true);
    setError(null);

    try {
      await createConfigDir();
      
      // Build TOML config
      let tomlConfig = `# Deadend CLI Configuration

[general]
version = "1.0.0"

[rpc]
enabled = true
timeout = 5000

[chat]
history_enabled = true
max_history = 100

# Model Providers Configuration
`;

      configs.forEach((config) => {
        const providerName = config.provider;
        tomlConfig += `\n[models.${providerName}]\n`;
        if (config.apiKey) {
          tomlConfig += `api_key = "${config.apiKey}"\n`;
        }
        if (config.model) {
          tomlConfig += `model = "${config.model}"\n`;
        }
        if (config.baseUrl) {
          tomlConfig += `base_url = "${config.baseUrl}"\n`;
        }
        tomlConfig += `enabled = true\n`;
      });

      const filePath = getConfigFile();
      await Deno.writeTextFile(filePath, tomlConfig);
      
      setIsSaving(false);
      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setIsSaving(false);
    }
  }, [onComplete]);

  const getCurrentPrompt = (): string => {
    if (step === 0) {
      return "Select models (space to toggle, Enter to continue):";
    }

    const currentModel = modelConfigs[currentModelIndex];
    if (!currentModel) return "";

    if (currentModel.provider === "local") {
      if (!currentModel.baseUrl) {
        return `Enter base URL:`;
      }
      if (!currentModel.model) {
        return `Enter model name:`;
      }
    } else {
      if (!currentModel.apiKey) {
        return `Enter API key:`;
      }
      if (!currentModel.model) {
        return `Enter model name:`;
      }
    }

    return "Press Enter to continue...";
  };

  return (
    <Box flexDirection="column">
      <Box
        borderStyle="round"
        borderColor="grey"
      >
        <Box flexDirection="column">
          <Text color="grey" bold>
            Configuration Setup
          </Text>

          {step === 0 && (
            <Box flexDirection="column">
              <Box marginBottom={1}>
                <Text color="cyan" bold>
                  Step 1: Select Model Providers
                </Text>
              </Box>
              <Box marginBottom={1}>
                <Text>
                  Choose which model providers you want to configure:
                </Text>
              </Box>
              
              <Box flexDirection="column" marginTop={1}>
                {modelProviders.map((provider, index) => {
                  const isSelected = selectedModels.has(provider);
                  const isHighlighted = index === highlightedIndex;
                  return (
                    <Box 
                      key={provider} 
                      flexDirection="row" 
                      marginTop={0}
                      backgroundColor={isHighlighted ? "blue" : undefined}
                    >
                      <Text color={isSelected ? "green" : isHighlighted ? "white" : "gray"} bold={isHighlighted}>
                        {isSelected ? "[✓]" : "[ ]"} {provider}
                      </Text>
                    </Box>
                  );
                })}
              </Box>

              {error && (
                <Box marginTop={1}>
                  <Text color="red">
                    {error}
                  </Text>
                </Box>
              )}

              <Box marginTop={2} flexDirection="column">
                <Text color="gray" dimColor>
                  Use ↑/↓ to navigate, Space to toggle selection
                </Text>
                <Box marginTop={1}>
                  <Text color="cyan">
                    Press Enter when done selecting models
                  </Text>
                </Box>
              </Box>
            </Box>
          )}

          {step === 1 && (
            <Box flexDirection="column">
              <Box marginBottom={1}>
                <Text color="red" bold>
                  Step 2: Configure Models ({currentModelIndex + 1}/{modelConfigs.length})
                </Text>
              </Box>
              
              {modelConfigs[currentModelIndex] && (
                <Box flexDirection="column">
                  <Text color="grey">
                    Configuring: {modelConfigs[currentModelIndex].provider}
                  </Text>
                </Box>
              )}

              {error && (
                <Box>
                  <Text color="red">
                    {error}
                  </Text>
                </Box>
              )}

              {isSaving ? (
                <Box>
                  <Text color="yellow">
                    Saving configuration...
                  </Text>
                </Box>
              ) : (
                <>
                  <Box marginTop={1}>
                    <Text>
                      {getCurrentPrompt()}
                    </Text>
                  </Box>

                  <Box flexDirection="row">
                    <Text color="cyan">{"> "}</Text>
                    <TextInput
                      value={currentInput}
                      onChange={setCurrentInput}
                      onSubmit={handleModelConfig}
                      placeholder="Enter value..."
                    />
                  </Box>
                </>
              )}
            </Box>
          )}
        </Box>
      </Box>
    </Box>
  );
}

