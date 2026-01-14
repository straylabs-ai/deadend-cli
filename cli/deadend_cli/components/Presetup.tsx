import { useState, useCallback } from "react";
import { Box, Text } from "ink";
import TextInput from "ink-text-input";
import { createDefaultConfig } from "../lib/config.ts";

interface PresetupProps {
  onComplete: () => void;
}

type ProviderType = "proprietary" | "local" | null;

type ProviderSettings = "provider" | "model" | "apiKey" | "baseUrl" | null;

export function Presetup({ onComplete }: PresetupProps) {
  const [step, setStep] = useState(0);
  const [providerType, setProviderType] = useState<ProviderType>(null);
  const [providerName, setProviderName] = useState("");
  const [modelName, setModelName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [currentInput, setCurrentInput] = useState("");
  const [currentField, setCurrentField] = useState<ProviderSettings>("provider");
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSkip = useCallback(async () => {
    setIsCreating(true);
    setError(null);
    
    try {
      await createDefaultConfig();
      setIsCreating(false);
      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setIsCreating(false);
    }
  }, [onComplete]);

  const handleProviderTypeSelect = useCallback((input: string) => {
    const lowerInput = input.toLowerCase().trim();
    if (lowerInput === "proprietary" || lowerInput === "1") {
      setProviderType("proprietary");
      setStep(1);
      setCurrentField("provider");
      setCurrentInput("");
    } else if (lowerInput === "local" || lowerInput === "2") {
      setProviderType("local");
      setStep(1);
      setCurrentField("provider");
      setCurrentInput("");
    } else if (lowerInput === "skip") {
      handleSkip();
    }
  }, [handleSkip]);

  const handleFieldInput = useCallback((input: string) => {
    if (input.toLowerCase().trim() === "skip") {
      handleSkip();
      return;
    }

    if (currentField === "provider") {
      setProviderName(input.trim());
      setCurrentField("model");
      setCurrentInput("");
    } else if (currentField === "model") {
      setModelName(input.trim());
      if (providerType === "local") {
        setCurrentField("baseUrl");
      } else {
        setCurrentField("apiKey");
      }
      setCurrentInput("");
    } else if (currentField === "baseUrl") {
      setBaseUrl(input.trim());
      setCurrentField("apiKey");
      setCurrentInput("");
    } else if (currentField === "apiKey") {
      setApiKey(input.trim());
      // All fields collected, move to confirmation step
      setStep(2);
      setCurrentInput("");
    }
  }, [currentField, providerType, handleSkip]);

  const handleSubmit = useCallback(async () => {
    if (step === 2) {
      // Validate required fields
      if (!providerName || !modelName || !apiKey) {
        setError("Provider name, model name, and API key are required");
        return;
      }
      if (providerType === "local" && !baseUrl) {
        setError("Base URL is required for local provider");
        return;
      }

      // Create config
      setIsCreating(true);
      setError(null);
      
      try {
        await createDefaultConfig({
          providerType: providerType || undefined,
          providerName,
          modelName,
          apiKey,
          baseUrl: providerType === "local" ? baseUrl : undefined,
        });
        setIsCreating(false);
        onComplete();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unknown error");
        setIsCreating(false);
      }
    }
  }, [step, providerType, providerName, modelName, apiKey, baseUrl, onComplete]);

  return (
    <Box flexDirection="column" padding={2}>
      <Box
        borderStyle="round"
        borderColor="yellow"
        padding={2}
        marginBottom={2}
      >
        <Box flexDirection="column">
          <Text color="yellow" bold>
            Welcome to Deadend CLI!
          </Text>
          <Text>
            It looks like this is your first time running the application.
          </Text>
          <Text>
            Let's set up your configuration.
          </Text>
        </Box>
      </Box>

      {step === 0 && (
        <Box flexDirection="column">
          <Text color="cyan" bold>
            Setup Step 1/3: Choose Provider Type
          </Text>
          <Text>
            We'll create a configuration file at:
          </Text>
          <Text color="gray">
            ~/.cache/deadend/config.toml
          </Text>
          <Box marginTop={1}>
            <Text>
              Choose your provider type:
            </Text>
          </Box>
          <Text color="gray">
            1. Proprietary provider (OpenAI, Anthropic, Gemini, OpenRouter)
          </Text>
          <Text color="gray">
            2. Local (self-hosted, requires base URL)
          </Text>
          <Box marginTop={1}>
            <Text>
              Type "1" or "proprietary" for proprietary provider, "2" or "local" for local, or "skip" to use defaults.
            </Text>
          </Box>
          
          <Box
            borderStyle="round"
            borderColor="cyan"
            padding={1}
            marginTop={1}
          >
            <Box flexDirection="row">
              <Text color="cyan">{"> "}</Text>
              <TextInput
                value={currentInput}
                onChange={setCurrentInput}
                onSubmit={handleProviderTypeSelect}
                placeholder="Enter choice (1/proprietary/2/local/skip)..."
              />
            </Box>
          </Box>
        </Box>
      )}

      {step === 1 && (
        <Box flexDirection="column">
          <Text color="cyan" bold>
            Setup Step 2/3: Provider Configuration
          </Text>
          {currentField === "provider" && (
            <>
              <Text>
                Enter your provider name (e.g., openai, anthropic, gemini, openrouter):
              </Text>
              <Box
                borderStyle="round"
                borderColor="cyan"
                padding={1}
                marginTop={1}
              >
                <Box flexDirection="row">
                  <Text color="cyan">{"> Provider name: "}</Text>
                  <TextInput
                    value={currentInput}
                    onChange={setCurrentInput}
                    onSubmit={handleFieldInput}
                    placeholder="e.g., openai"
                  />
                </Box>
              </Box>
            </>
          )}
          {currentField === "model" && (
            <>
              <Text color="green">✓ Provider: {providerName}</Text>
              <Text>
                Enter your model name:
              </Text>
              <Box
                borderStyle="round"
                borderColor="cyan"
                padding={1}
                marginTop={1}
              >
                <Box flexDirection="row">
                  <Text color="cyan">{"> Model name: "}</Text>
                  <TextInput
                    value={currentInput}
                    onChange={setCurrentInput}
                    onSubmit={handleFieldInput}
                    placeholder="e.g., gpt-4o-mini"
                  />
                </Box>
              </Box>
            </>
          )}
          {currentField === "baseUrl" && (
            <>
              <Text color="green">✓ Provider: {providerName}</Text>
              <Text color="green">✓ Model: {modelName}</Text>
              <Text>
                Enter your base API URL:
              </Text>
              <Box
                borderStyle="round"
                borderColor="cyan"
                padding={1}
                marginTop={1}
              >
                <Box flexDirection="row">
                  <Text color="cyan">{"> Base URL: "}</Text>
                  <TextInput
                    value={currentInput}
                    onChange={setCurrentInput}
                    onSubmit={handleFieldInput}
                    placeholder="e.g., http://localhost:1234/v1"
                  />
                </Box>
              </Box>
            </>
          )}
          {currentField === "apiKey" && (
            <>
              <Text color="green">✓ Provider: {providerName}</Text>
              <Text color="green">✓ Model: {modelName}</Text>
              {providerType === "local" && <Text color="green">✓ Base URL: {baseUrl}</Text>}
              <Text>
                Enter your API key:
              </Text>
              <Box
                borderStyle="round"
                borderColor="cyan"
                padding={1}
                marginTop={1}
              >
                <Box flexDirection="row">
                  <Text color="cyan">{"> API key: "}</Text>
                  <TextInput
                    value={currentInput}
                    onChange={setCurrentInput}
                    onSubmit={handleFieldInput}
                    placeholder="Enter your API key..."
                  />
                </Box>
              </Box>
            </>
          )}
          {error && (
            <Box marginTop={1}>
              <Text color="red">
                Error: {error}
              </Text>
            </Box>
          )}
        </Box>
      )}

      {step === 2 && (
        <Box flexDirection="column">
          <Text color="grey" bold>
            Setup Step 3/3: Creating Configuration
          </Text>
          <Text color="green">✓ Provider: {providerName}</Text>
          <Text color="green">✓ Model: {modelName}</Text>
          {providerType === "local" && <Text color="green">✓ Base URL: {baseUrl}</Text>}
          <Text color="green">✓ API key: {"*".repeat(Math.min(apiKey.length, 20))}</Text>
          {isCreating ? (
            <Box marginTop={1}>
              <Text color="yellow">Creating configuration file...</Text>
            </Box>
          ) : (
            <Box marginTop={1}>
              <Text>Press Enter to create the configuration file.</Text>
            </Box>
          )}
          
          {error && (
            <Box marginTop={1}>
              <Text color="red">
                Error: {error}
              </Text>
            </Box>
          )}

          <Box
            borderStyle="round"
            borderColor="cyan"
            padding={1}
            marginTop={1}
          >
            <Box flexDirection="row">
              <Text color="cyan">{"> "}</Text>
              <TextInput
                value=""
                onChange={() => {}}
                onSubmit={handleSubmit}
                placeholder="Press Enter to create config..."
              />
            </Box>
          </Box>
        </Box>
      )}
    </Box>
  );
}

