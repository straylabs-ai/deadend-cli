import { useState, useCallback, useEffect } from "react";
import { Box, Text } from "ink";
import TextInput from "ink-text-input";
import type { EmbeddingConfig } from "../config/types.ts";
import type { DeadEndRpcClient } from "../lib/deadend-rpc-client.ts";
import { configManager } from "../config/manager.ts";

interface PresetupWizardProps {
  rpcClient: DeadEndRpcClient | null;
  onComplete: () => void;
}

type WizardStep = 
  | "provider"
  | "model"
  | "api_key"
  | "embedding"
  | "confirm";

interface ModelConfig {
  provider: string;
  model: string;
  api_key?: string;
  base_url?: string;
}

export function PresetupWizard({ rpcClient, onComplete }: PresetupWizardProps) {
  const [step, setStep] = useState<WizardStep>("provider");
  const [currentInput, setCurrentInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  
  // Model configuration
  const [modelConfig, setModelConfig] = useState<ModelConfig>({
    provider: "",
    model: "",
  });
  
  // Embedding configuration
  const [embeddingConfig, setEmbeddingConfig] = useState<EmbeddingConfig | null>(null);
  const [skipEmbedding, setSkipEmbedding] = useState(false);
  const [embeddingStep, setEmbeddingStep] = useState<"question" | "provider" | "model" | "api_key" | "vec_dim">("question");
  

  // Check if models are configured and skip presetup if both regular and embedding models exist
  useEffect(() => {
    const checkModels = async () => {
      if (!rpcClient) return;
      
      try {
        const result = await rpcClient.GetAllModels();
        const models = result.models;
        let hasRegularModel = false;
        let hasEmbeddingModel = false;
        
        // Check if we have any models (regular models)
        if (models && typeof models === "object") {
          for (const [_provider, modelList] of Object.entries(models)) {
            if (modelList && Array.isArray(modelList) && modelList.length > 0) {
              hasRegularModel = true;
              break;
            }
          }
        }
        
        // Check config.json directly for embedding models
        try {
          await configManager.load();
          const config = configManager.getConfig();
          
          if (config && config.configured_models) {
            // Check for embedding models
            hasEmbeddingModel = config.configured_models.some(
              m => m.type_model === "embeddings"
            );
            
            // Also check for regular models if not found in GetAllModels
            if (!hasRegularModel) {
              hasRegularModel = config.configured_models.some(
                m => !m.type_model || m.type_model !== "embeddings"
              );
            }
          }
        } catch {
          // Config might not exist yet, that's okay
        }
        
        // If both regular and embedding models exist, skip presetup
        if (hasRegularModel && hasEmbeddingModel) {
          onComplete();
          return;
        }
      } catch (err) {
        // If we can't load models, show presetup
        console.error("Failed to load models:", err);
      }
    };
    
    checkModels();
  }, [rpcClient, onComplete]);

  const handleProviderInput = useCallback((input: string) => {
    const provider = input.trim().toLowerCase();
    if (!provider) {
      setError("Provider name is required");
      return;
    }
    
    setModelConfig(prev => ({ ...prev, provider }));
    setError(null);
    setCurrentInput("");
    setStep("model");
  }, []);

  const handleModelInput = useCallback((input: string) => {
    const model = input.trim();
    if (!model) {
      setError("Model name is required");
      return;
    }
    
    setModelConfig(prev => ({ ...prev, model }));
    setError(null);
    setCurrentInput("");
    setStep("api_key");
  }, []);


  const handleApiKeyInput = useCallback((input: string) => {
    const apiKey = input.trim();
    
    setModelConfig(prev => ({ ...prev, api_key: apiKey || undefined }));
    setError(null);
    setCurrentInput("");
    setStep("embedding");
  }, []);

  const handleEmbeddingInput = useCallback((input: string) => {
    const lowerInput = input.trim().toLowerCase();
    
    if (lowerInput === "skip" || lowerInput === "n" || lowerInput === "no" || lowerInput === "") {
      setSkipEmbedding(true);
      setStep("confirm");
      return;
    }
    
    if (lowerInput === "y" || lowerInput === "yes") {
      // Start embedding configuration
      setEmbeddingConfig({
        provider: "",
        model: "",
        auto_embed: true,
      });
      setEmbeddingStep("provider");
      setCurrentInput("");
      return;
    }
    
    setError("Please enter 'yes' or 'skip'");
  }, []);

  const handleEmbeddingProviderInput = useCallback((input: string) => {
    const provider = input.trim().toLowerCase();
    if (!provider) {
      setError("Embedding provider name is required");
      return;
    }
    
    setEmbeddingConfig(prev => prev ? { ...prev, provider } : {
      provider,
      model: "",
      auto_embed: true,
    });
    setError(null);
    setCurrentInput("");
    setEmbeddingStep("model");
  }, []);

  const handleEmbeddingModelInput = useCallback((input: string) => {
    const model = input.trim();
    if (!model) {
      setError("Embedding model name is required");
      return;
    }
    
    setEmbeddingConfig(prev => {
      if (prev) {
        return { ...prev, model };
      }
      return {
        provider: "",
        model,
        auto_embed: true,
      };
    });
    setError(null);
    setCurrentInput("");
    setEmbeddingStep("api_key");
  }, []);

  const handleEmbeddingApiKeyInput = useCallback((input: string) => {
    const apiKey = input.trim();
    
    if (apiKey) {
      setEmbeddingConfig(prev => prev ? { ...prev, api_key: apiKey } : {
        provider: "",
        model: "",
        api_key: apiKey,
        auto_embed: true,
      });
    }
    
    setError(null);
    setCurrentInput("");
    setEmbeddingStep("vec_dim");
  }, []);

  const handleEmbeddingVecDimInput = useCallback((input: string) => {
    const vecDimInput = input.trim();
    const vecDim = vecDimInput ? parseInt(vecDimInput, 10) : 1536;
    
    if (isNaN(vecDim) || vecDim <= 0) {
      setError("Vector dimension must be a positive number");
      return;
    }
    
    setEmbeddingConfig(prev => prev ? { ...prev, vec_dim: vecDim } : {
      provider: "",
      model: "",
      vec_dim: vecDim,
      auto_embed: true,
    });
    
    setError(null);
    setCurrentInput("");
    setStep("confirm");
  }, []);

  const handleConfirm = useCallback(async () => {
    if (!rpcClient) {
      setError("RPC client not available");
      return;
    }
    
    setIsSaving(true);
    setError(null);
    
    try {
      // Validate model configuration
      if (!modelConfig.provider || !modelConfig.model) {
        throw new Error("Provider and model are required");
      }
      
      // Add regular model via RPC
      await rpcClient.call("add_model", {
        provider: modelConfig.provider,
        model_name: modelConfig.model,
        api_key: modelConfig.api_key || null,
        base_url: modelConfig.base_url || null,
        type_model: null,
        vec_dim: null,
      });
      
      // Add embedding model if configured
      if (embeddingConfig && !skipEmbedding) {
        if (!embeddingConfig.provider || !embeddingConfig.model) {
          throw new Error("Embedding provider and model are required");
        }
        
        await rpcClient.call("add_model", {
          provider: embeddingConfig.provider,
          model_name: embeddingConfig.model,
          api_key: embeddingConfig.api_key || null,
          base_url: embeddingConfig.base_url || null,
          type_model: "embeddings",
          vec_dim: embeddingConfig.vec_dim || 1536,
        });
      }
      
      setIsSaving(false);
      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setIsSaving(false);
    }
  }, [modelConfig, embeddingConfig, skipEmbedding, onComplete, rpcClient]);

  const renderProviderStep = () => (
    <Box flexDirection="column">
      <Text color="cyan" bold>
        Step 1/6: Select Provider
      </Text>
      <Text>
        Enter your provider:
      </Text>
      <Box
        borderStyle="round"
        borderColor="cyan"
        padding={1}
        marginTop={1}
      >
        <Box flexDirection="row">
          <Text color="cyan">{"> Provider: "}</Text>
          <TextInput
            value={currentInput}
            onChange={setCurrentInput}
            onSubmit={handleProviderInput}
            placeholder="e.g., openai"
          />
        </Box>
      </Box>
    </Box>
  );

  const renderModelStep = () => (
    <Box flexDirection="column">
      <Text color="cyan" bold>
        Step 2/6: Select Model
      </Text>
      <Text color="green">✓ Provider: {modelConfig.provider}</Text>
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
          <Text color="cyan">{"> Model: "}</Text>
          <TextInput
            value={currentInput}
            onChange={setCurrentInput}
            onSubmit={handleModelInput}
            placeholder="e.g., gpt-4o-mini"
          />
        </Box>
      </Box>
    </Box>
  );

  const renderApiKeyStep = () => {
    return (
      <Box flexDirection="column">
        <Text color="cyan" bold>
          Step 3/6: API Key
        </Text>
        <Text color="green">✓ Provider: {modelConfig.provider}</Text>
        <Text color="green">✓ Model: {modelConfig.model}</Text>
        <Text>
          Enter your API key (optional):
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
              onSubmit={handleApiKeyInput}
              placeholder="Enter API key (optional)..."
            />
          </Box>
        </Box>
      </Box>
    );
  };

  const renderEmbeddingStep = () => {
    if (embeddingStep === "provider") {
      return (
        <Box flexDirection="column">
          <Text color="cyan" bold>
            Step 4/6: Embedding Provider
          </Text>
          <Text>
            Enter embedding provider name:
          </Text>
          <Box
            borderStyle="round"
            borderColor="cyan"
            padding={1}
            marginTop={1}
          >
            <Box flexDirection="row">
              <Text color="cyan">{"> Embedding provider: "}</Text>
              <TextInput
                value={currentInput}
                onChange={setCurrentInput}
                onSubmit={handleEmbeddingProviderInput}
                placeholder="e.g., openai"
              />
            </Box>
          </Box>
        </Box>
      );
    }
    
    if (embeddingStep === "model") {
      return (
        <Box flexDirection="column">
          <Text color="cyan" bold>
            Step 4/6: Embedding Model
          </Text>
          <Text color="green">✓ Provider: {embeddingConfig?.provider}</Text>
          <Text>
            Enter embedding model name:
          </Text>
          <Box
            borderStyle="round"
            borderColor="cyan"
            padding={1}
            marginTop={1}
          >
            <Box flexDirection="row">
              <Text color="cyan">{"> Embedding model: "}</Text>
              <TextInput
                value={currentInput}
                onChange={setCurrentInput}
                onSubmit={handleEmbeddingModelInput}
                placeholder="e.g., text-embedding-3-small"
              />
            </Box>
          </Box>
        </Box>
      );
    }
    
    if (embeddingStep === "api_key") {
      return (
        <Box flexDirection="column">
          <Text color="cyan" bold>
            Step 4/6: Embedding API Key
          </Text>
          <Text color="green">✓ Provider: {embeddingConfig?.provider}</Text>
          <Text color="green">✓ Model: {embeddingConfig?.model}</Text>
          <Text>
            Enter embedding API key (optional):
          </Text>
          <Box
            borderStyle="round"
            borderColor="cyan"
            padding={1}
            marginTop={1}
          >
            <Box flexDirection="row">
              <Text color="cyan">{"> Embedding API key: "}</Text>
              <TextInput
                value={currentInput}
                onChange={setCurrentInput}
                onSubmit={handleEmbeddingApiKeyInput}
                placeholder="Enter API key (optional)..."
              />
            </Box>
          </Box>
        </Box>
      );
    }
    
    if (embeddingStep === "vec_dim") {
      return (
        <Box flexDirection="column">
          <Text color="cyan" bold>
            Step 5/6: Embedding Vector Dimension
          </Text>
          <Text color="green">✓ Provider: {embeddingConfig?.provider}</Text>
          <Text color="green">✓ Model: {embeddingConfig?.model}</Text>
          {embeddingConfig?.api_key && (
            <Text color="green">✓ API key: {"*".repeat(Math.min(embeddingConfig.api_key.length, 20))}</Text>
          )}
          <Text>
            Enter vector dimension (default: 1536):
          </Text>
          <Box
            borderStyle="round"
            borderColor="cyan"
            padding={1}
            marginTop={1}
          >
            <Box flexDirection="row">
              <Text color="cyan">{"> Vector dimension: "}</Text>
              <TextInput
                value={currentInput}
                onChange={setCurrentInput}
                onSubmit={handleEmbeddingVecDimInput}
                placeholder="1536"
              />
            </Box>
          </Box>
        </Box>
      );
    }
    
    // Initial embedding question
    return (
      <Box flexDirection="column">
        <Text color="cyan" bold>
          Step 4/6: Embedding Configuration
        </Text>
        <Text color="green">✓ Provider: {modelConfig.provider}</Text>
        <Text color="green">✓ Model: {modelConfig.model}</Text>
        <Text>
          Would you like to configure an embedding model for RAG features? (yes/skip):
        </Text>
        <Box
          borderStyle="round"
          borderColor="cyan"
          padding={1}
          marginTop={1}
        >
          <Box flexDirection="row">
            <Text color="cyan">{"> Configure embedding? "}</Text>
            <TextInput
              value={currentInput}
              onChange={setCurrentInput}
              onSubmit={handleEmbeddingInput}
              placeholder="yes/skip"
            />
          </Box>
        </Box>
      </Box>
    );
  };

  const renderConfirmStep = () => (
    <Box flexDirection="column">
      <Text color="cyan" bold>
        Step 6/6: Confirm Configuration
      </Text>
      <Text color="green">✓ Provider: {modelConfig.provider}</Text>
      <Text color="green">✓ Model: {modelConfig.model}</Text>
      {modelConfig.api_key && (
        <Text color="green">✓ API key: {"*".repeat(Math.min(modelConfig.api_key.length, 20))}</Text>
      )}
      {skipEmbedding ? (
        <Text color="yellow">⊘ Embedding: Skipped</Text>
      ) : embeddingConfig ? (
        <>
          <Text color="green">✓ Embedding Provider: {embeddingConfig.provider}</Text>
          <Text color="green">✓ Embedding Model: {embeddingConfig.model}</Text>
          {embeddingConfig.api_key && (
            <Text color="green">✓ Embedding API key: {"*".repeat(Math.min(embeddingConfig.api_key.length, 20))}</Text>
          )}
          <Text color="green">✓ Vector dimension: {embeddingConfig.vec_dim || 1536}</Text>
        </>
      ) : null}
      
      {isSaving ? (
        <Box marginTop={1}>
          <Text color="yellow">Saving configuration...</Text>
        </Box>
      ) : (
        <Box marginTop={1}>
          <Text>Press Enter to save the configuration.</Text>
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
            onSubmit={handleConfirm}
            placeholder="Press Enter to save..."
          />
        </Box>
      </Box>
    </Box>
  );

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

      {step === "provider" && renderProviderStep()}
      {step === "model" && renderModelStep()}
      {step === "api_key" && renderApiKeyStep()}
      {step === "embedding" && renderEmbeddingStep()}
      {step === "confirm" && renderConfirmStep()}

      {error && (
        <Box marginTop={1}>
          <Text color="red">
            Error: {error}
          </Text>
        </Box>
      )}
    </Box>
  );
}

