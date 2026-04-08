/**
 * @file LlmSelector.tsx
 * @description Interactive LLM provider selector component.
 *
 * This component provides:
 * - Radio-button style list of available providers
 * - Shows configured status and current model for each provider
 * - Allows switching between providers
 * - Option to edit API key and model name after selection
 */

import { useState, useEffect, useCallback } from "react";
import { Box, Text, useInput } from "ink";
import TextInput from "ink-text-input";
import type { DeadEndRpcClient } from "../runtime/deadend-rpc-client.ts";
import { getConfigFile } from "../runtime/config.ts";

interface LlmSelectorProps {
  rpcClient: DeadEndRpcClient;
  onComplete: () => void;
  onCancel: () => void;
}

interface ProviderInfo {
  name: string;
  configured: boolean;
  model: string | null;
}

type Step = "select" | "confirm_edit" | "edit_key" | "edit_model" | "saving";

export function LlmSelector({ rpcClient, onComplete, onCancel }: LlmSelectorProps) {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [currentProvider, setCurrentProvider] = useState<string>("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [step, setStep] = useState<Step>("select");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [editInput, setEditInput] = useState("");
  const [newApiKey, setNewApiKey] = useState("");
  const [newModel, setNewModel] = useState("");

  // Load providers on mount
  useEffect(() => {
    loadProviders();
  }, []);

  const loadProviders = async () => {
    setIsLoading(true);
    try {
      const result = await rpcClient.listLlmProviders();
      setProviders(result.providers);
      setCurrentProvider(result.current);
      // Set initial selection to current provider
      const currentIndex = result.providers.findIndex((p) => p.name === result.current);
      if (currentIndex >= 0) {
        setSelectedIndex(currentIndex);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load providers");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelect = useCallback(async () => {
    const selected = providers[selectedIndex];
    if (!selected) return;

    if (!selected.configured) {
      // Provider not configured - go to edit mode
      setStep("edit_key");
      setNewApiKey("");
      setNewModel("");
      setError(null);
      return;
    }

    // Provider is configured - ask if they want to edit
    if (selected.name === currentProvider) {
      // Already active, ask to edit
      setStep("confirm_edit");
    } else {
      // Switch to this provider
      try {
        await rpcClient.setLlmProvider(selected.name);
        setCurrentProvider(selected.name);
        onComplete();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to switch provider");
      }
    }
  }, [providers, selectedIndex, currentProvider, rpcClient, onComplete]);

  const handleConfirmEdit = useCallback((edit: boolean) => {
    if (edit) {
      const selected = providers[selectedIndex];
      setNewApiKey("");
      setNewModel("");
      setEditInput("");
      setStep("edit_key");
    } else {
      onComplete();
    }
  }, [providers, selectedIndex, onComplete]);

  const handleSaveConfig = useCallback(async () => {
    const selected = providers[selectedIndex];
    if (!selected) return;

    setStep("saving");
    setError(null);

    try {
      // Read current config
      const configPath = getConfigFile();
      let configContent = "";
      try {
        configContent = await Deno.readTextFile(configPath);
      } catch {
        configContent = "";
      }

      // Build the key names based on provider
      const keyMap: Record<string, { apiKey: string; model: string; baseUrl?: string }> = {
        openai: { apiKey: "OPENAI_API_KEY", model: "OPENAI_MODEL" },
        anthropic: { apiKey: "ANTHROPIC_API_KEY", model: "ANTHROPIC_MODEL" },
        gemini: { apiKey: "GEMINI_API_KEY", model: "GEMINI_MODEL" },
        bedrock: { apiKey: "AWS_BEARER_TOKEN_BEDROCK", model: "BEDROCK_MODEL" },
        openrouter: { apiKey: "OPEN_ROUTER_API_KEY", model: "OPEN_ROUTER_MODEL" },
        local: { apiKey: "LOCAL_API_KEY", model: "LOCAL_MODEL", baseUrl: "LOCAL_BASE_URL" },
      };

      const keys = keyMap[selected.name];
      if (!keys) throw new Error(`Unknown provider: ${selected.name}`);

      // Update or add the config values
      const lines = configContent.split("\n");
      const updates: Record<string, string> = {};

      if (newApiKey) updates[keys.apiKey] = newApiKey;
      if (newModel) updates[keys.model] = newModel;

      // Update existing lines or track what needs to be added
      const updatedKeys = new Set<string>();
      const newLines = lines.map((line) => {
        for (const [key, value] of Object.entries(updates)) {
          if (line.startsWith(`${key} =`) || line.startsWith(`${key}=`)) {
            updatedKeys.add(key);
            return `${key} = "${value}"`;
          }
        }
        return line;
      });

      // Add any missing keys at the end
      for (const [key, value] of Object.entries(updates)) {
        if (!updatedKeys.has(key)) {
          newLines.push(`${key} = "${value}"`);
        }
      }

      await Deno.writeTextFile(configPath, newLines.join("\n"));

      // Switch to the provider
      await rpcClient.setLlmProvider(selected.name);
      setCurrentProvider(selected.name);

      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save configuration");
      setStep("edit_key");
    }
  }, [providers, selectedIndex, newApiKey, newModel, rpcClient, onComplete]);

  // Handle keyboard input
  useInput((input, key) => {
    if (step === "select") {
      if (key.upArrow) {
        setSelectedIndex((prev) => (prev > 0 ? prev - 1 : providers.length - 1));
        setError(null);
      } else if (key.downArrow) {
        setSelectedIndex((prev) => (prev < providers.length - 1 ? prev + 1 : 0));
        setError(null);
      } else if (key.return) {
        handleSelect();
      } else if (key.escape) {
        onCancel();
      }
    } else if (step === "confirm_edit") {
      if (input.toLowerCase() === "y") {
        handleConfirmEdit(true);
      } else if (input.toLowerCase() === "n" || key.escape) {
        handleConfirmEdit(false);
      }
    } else if (step === "edit_key" || step === "edit_model") {
      if (key.escape) {
        setStep("select");
        setError(null);
      }
    }
  });

  const handleKeySubmit = useCallback(() => {
    if (!editInput.trim()) {
      setError("API key is required");
      return;
    }
    setNewApiKey(editInput.trim());
    // Pre-fill with current model if editing existing provider
    const selected = providers[selectedIndex];
    setEditInput(selected?.model || "");
    setStep("edit_model");
    setError(null);
  }, [editInput, providers, selectedIndex]);

  const handleModelSubmit = useCallback(() => {
    if (!editInput.trim()) {
      setError("Model name is required");
      return;
    }
    setNewModel(editInput.trim());
    setEditInput("");
    handleSaveConfig();
  }, [editInput, handleSaveConfig]);

  if (isLoading) {
    return (
      <Box flexDirection="column" padding={1}>
        <Text color="cyan">Loading providers...</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      <Box borderStyle="round" borderColor="cyan" paddingX={1}>
        <Box flexDirection="column">
          <Text color="cyan" bold>
            LLM Provider Selection
          </Text>

          {step === "select" && (
            <Box flexDirection="column" marginTop={1}>
              <Text dimColor>
                Select a provider (Enter to select, Esc to cancel):
              </Text>

              <Box flexDirection="column" marginTop={1}>
                {providers.map((provider, index) => {
                  const isSelected = index === selectedIndex;
                  const isCurrent = provider.name === currentProvider;
                  const radio = isSelected ? "(o)" : "( )";

                  return (
                    <Box key={provider.name} flexDirection="row">
                      <Text
                        color={isSelected ? "cyan" : undefined}
                        bold={isSelected}
                        backgroundColor={isSelected ? "blue" : undefined}
                      >
                        {radio} {provider.name.padEnd(12)}
                      </Text>
                      {provider.configured ? (
                        <Text color="green" italic>
                          {provider.model}{isCurrent ? " *" : ""}
                        </Text>
                      ) : (
                        <Text color="gray" dimColor>
                          (not configured)
                        </Text>
                      )}
                    </Box>
                  );
                })}
              </Box>

              <Box marginTop={1}>
                <Text color="gray" dimColor>
                  * = currently active
                </Text>
              </Box>
            </Box>
          )}

          {step === "confirm_edit" && (
            <Box flexDirection="column" marginTop={1}>
              <Text>
                This provider is already active. Edit API key and model? (y/n)
              </Text>
            </Box>
          )}

          {step === "edit_key" && (
            <Box flexDirection="column" marginTop={1}>
              <Text color="yellow">
                Configuring: {providers[selectedIndex]?.name}
              </Text>
              <Box marginTop={1}>
                <Text>Enter API key:</Text>
              </Box>
              <Box flexDirection="row">
                <Text color="cyan">{"> "}</Text>
                <TextInput
                  value={editInput}
                  onChange={setEditInput}
                  onSubmit={handleKeySubmit}
                  placeholder="sk-..."
                  mask="*"
                />
              </Box>
              <Text color="gray" dimColor>
                Press Esc to cancel
              </Text>
            </Box>
          )}

          {step === "edit_model" && (
            <Box flexDirection="column" marginTop={1}>
              <Text color="yellow">
                Configuring: {providers[selectedIndex]?.name}
              </Text>
              <Box marginTop={1}>
                <Text>Enter model name:</Text>
              </Box>
              <Box flexDirection="row">
                <Text color="cyan">{"> "}</Text>
                <TextInput
                  value={editInput}
                  onChange={setEditInput}
                  onSubmit={handleModelSubmit}
                  placeholder="e.g., gpt-4o, claude-3-opus..."
                />
              </Box>
              <Text color="gray" dimColor>
                Press Esc to cancel
              </Text>
            </Box>
          )}

          {step === "saving" && (
            <Box flexDirection="column" marginTop={1}>
              <Text color="yellow">
                Saving configuration...
              </Text>
            </Box>
          )}

          {error && (
            <Box marginTop={1}>
              <Text color="red">{error}</Text>
            </Box>
          )}
        </Box>
      </Box>
    </Box>
  );
}
