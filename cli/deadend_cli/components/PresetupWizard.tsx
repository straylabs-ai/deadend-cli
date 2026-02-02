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
  | "model"
  | "embedding";

interface ModelConfig {
  provider: string;
  model: string;
  api_key?: string;
  base_url?: string;
}

export function PresetupWizard({ rpcClient, onComplete }: PresetupWizardProps) {
  const [step, setStep] = useState<WizardStep>("model");
  const [currentInput, setCurrentInput] = useState("");
  const [currentField, setCurrentField] = useState<"provider" | "model" | "api_key" | "base_url">("provider");
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
  const [embeddingField, setEmbeddingField] = useState<"question" | "provider" | "model" | "api_key" | "base_url" | "vec_dim">("question");
  

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

  const handleModelStepInput = useCallback((input: string) => {
    const value = input.trim();
    
    if (currentField === "provider") {
      if (!value) {
        setError("Provider name is required");
        return;
      }
      setModelConfig(prev => ({ ...prev, provider: value.toLowerCase() }));
      setCurrentField("model");
    } else if (currentField === "model") {
      if (!value) {
        setError("Model name is required");
        return;
      }
      setModelConfig(prev => ({ ...prev, model: value }));
      setCurrentField("api_key");
    } else if (currentField === "api_key") {
      setModelConfig(prev => ({ ...prev, api_key: value || undefined }));
      setCurrentField("base_url");
    } else if (currentField === "base_url") {
      setModelConfig(prev => ({ ...prev, base_url: value || undefined }));
      setStep("embedding");
      setEmbeddingField("question");
    }
    
    setError(null);
    setCurrentInput("");
  }, [currentField]);

  const handleConfirm = useCallback(async (finalEmbeddingConfig?: EmbeddingConfig | null) => {
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
      
      // Use provided config or fallback to state
      const configToUse = finalEmbeddingConfig !== undefined ? finalEmbeddingConfig : embeddingConfig;
      
      // Add embedding model if configured
      if (configToUse && !skipEmbedding) {
        if (!configToUse.provider || !configToUse.model) {
          throw new Error("Embedding provider and model are required");
        }
        const result = await rpcClient.call("add_model", {
          provider: configToUse.provider,
          model_name: configToUse.model,
          api_key: configToUse.api_key || null,
          base_url: configToUse.base_url || null,
          type_model: "embeddings",
          vec_dim: configToUse.vec_dim || 1536,
        });
        console.log("Embedding model added successfully:", result);
      }
      
      // Create and save default settings with the entered model as default
      try {
        const newSettings = {
          provider: modelConfig.provider,
          model: modelConfig.model,
          agentMode: "supervisor" as const,
          showComponentStatus: true,
          autoCollapseStatus: false,
          lastTarget: "",
          commandHistory: [],
          ...(configToUse && !skipEmbedding ? {
            embedding: {
              provider: configToUse.provider,
              model: configToUse.model,
            }
          } : {}),
        };
        
        await configManager.saveDefaultSettings(newSettings);
      } catch (settingsErr) {
        // Log but don't fail the whole operation if settings save fails
        console.error("Failed to save default settings:", settingsErr);
      }
      
      setIsSaving(false);
      onComplete();
    } catch (err) {
      const errorMessage = err instanceof Error 
        ? err.message 
        : typeof err === "string" 
        ? err 
        : err?.toString() || "Unknown error";
      console.error("Error in handleConfirm:", err);
      setError(errorMessage);
      setIsSaving(false);
    }
  }, [modelConfig, embeddingConfig, skipEmbedding, onComplete, rpcClient]);

  const handleConfirmWithEmbedding = useCallback((finalEmbeddingConfig: EmbeddingConfig) => {
    handleConfirm(finalEmbeddingConfig);
  }, [handleConfirm]);

  const handleEmbeddingStepInput = useCallback((input: string) => {
    const value = input.trim();
    
    if (embeddingField === "question") {
      const lowerInput = value.toLowerCase();
      if (lowerInput === "skip" || lowerInput === "n" || lowerInput === "no" || lowerInput === "") {
        setSkipEmbedding(true);
        // Proceed to save
        handleConfirm();
        return;
      }
      if (lowerInput === "y" || lowerInput === "yes") {
        setEmbeddingConfig({
          provider: "",
          model: "",
          auto_embed: true,
        });
        setEmbeddingField("provider");
        setError(null);
        setCurrentInput("");
        return;
      }
      setError("Please enter 'yes' or 'skip'");
      return;
    }
    
    if (embeddingField === "provider") {
      if (!value) {
        setError("Embedding provider name is required");
        return;
      }
      setEmbeddingConfig(prev => prev ? { ...prev, provider: value.toLowerCase() } : {
        provider: value.toLowerCase(),
        model: "",
        auto_embed: true,
      });
      setEmbeddingField("model");
    } else if (embeddingField === "model") {
      if (!value) {
        setError("Embedding model name is required");
        return;
      }
      setEmbeddingConfig(prev => prev ? { ...prev, model: value } : {
        provider: "",
        model: value,
        auto_embed: true,
      });
      setEmbeddingField("api_key");
    } else if (embeddingField === "api_key") {
      setEmbeddingConfig(prev => prev ? { ...prev, api_key: value || undefined } : {
        provider: "",
        model: "",
        api_key: value || undefined,
        auto_embed: true,
      });
      setEmbeddingField("base_url");
    } else if (embeddingField === "base_url") {
      setEmbeddingConfig(prev => prev ? { ...prev, base_url: value || undefined } : {
        provider: "",
        model: "",
        base_url: value || undefined,
        auto_embed: true,
      });
      setEmbeddingField("vec_dim");
    } else if (embeddingField === "vec_dim") {
      const vecDim = value ? parseInt(value, 10) : 1536;
      if (isNaN(vecDim) || vecDim <= 0) {
        setError("Vector dimension must be a positive number");
        return;
      }
      const updatedConfig = {
        ...(embeddingConfig || { provider: "", model: "", auto_embed: true }),
        vec_dim: vecDim,
      };
      setEmbeddingConfig(updatedConfig);
      // Proceed to save with updated config
      handleConfirmWithEmbedding(updatedConfig);
      return;
    }
    
    setError(null);
    setCurrentInput("");
  }, [embeddingField, embeddingConfig, handleConfirmWithEmbedding]);

  const renderModelStep = () => {
    const getFieldLabel = () => {
      if (currentField === "provider") return "Provider";
      if (currentField === "model") return "Model";
      if (currentField === "api_key") return "API Key (optional)";
      if (currentField === "base_url") return "Base URL (optional)";
      return "";
    };

    const getPlaceholder = () => {
      if (currentField === "provider") return "e.g., ollama";
      if (currentField === "model") return "e.g., gpt-4o-mini";
      if (currentField === "api_key") return "Enter API key (optional)...";
      if (currentField === "base_url") return "Enter base URL (optional)...";
      return "";
    };

    return (
      <Box flexDirection="column">
        <Text color="grey" bold>
          Step 1/2: Model Configuration
        </Text>
        {modelConfig.provider && (
          <Text color="green">✓ Provider: {modelConfig.provider}</Text>
        )}
        {modelConfig.model && (
          <Text color="green">✓ Model: {modelConfig.model}</Text>
        )}
        {modelConfig.api_key && (
          <Text color="green">✓ API key: {"*".repeat(Math.min(modelConfig.api_key.length, 20))}</Text>
        )}
        {modelConfig.base_url && (
          <Text color="green">✓ Base URL: {modelConfig.base_url}</Text>
        )}
        <Text>
          Enter {getFieldLabel()}:
        </Text>
        <Box flexDirection="row">
          <Text color="grey">{"> "}{getFieldLabel()}: </Text>
          <TextInput
            value={currentInput}
            onChange={setCurrentInput}
            onSubmit={handleModelStepInput}
            placeholder={getPlaceholder()}
          />
        </Box>
      </Box>
    );
  };

  const renderEmbeddingStep = () => {
    const getFieldLabel = () => {
      if (embeddingField === "question") return "Configure embedding? (yes/skip)";
      if (embeddingField === "provider") return "Embedding Provider";
      if (embeddingField === "model") return "Embedding Model";
      if (embeddingField === "api_key") return "Embedding API Key (optional)";
      if (embeddingField === "base_url") return "Embedding Base URL (optional)";
      if (embeddingField === "vec_dim") return "Vector Dimension (default: 1536)";
      return "";
    };

    const getPlaceholder = () => {
      if (embeddingField === "question") return "yes/skip";
      if (embeddingField === "provider") return "e.g., openai";
      if (embeddingField === "model") return "e.g., text-embedding-3-small";
      if (embeddingField === "api_key") return "Enter API key (optional)...";
      if (embeddingField === "base_url") return "Enter base URL (optional)...";
      if (embeddingField === "vec_dim") return "1536";
      return "";
    };

    return (
      <Box flexDirection="column">
        <Text color="grey" bold>
          Step 2/2: Embedding Configuration
        </Text>
        {embeddingField !== "question" && embeddingConfig && (
          <>
            {embeddingConfig.provider && (
              <Text color="green">✓ Embedding Provider: {embeddingConfig.provider}</Text>
            )}
            {embeddingConfig.model && (
              <Text color="green">✓ Embedding Model: {embeddingConfig.model}</Text>
            )}
            {embeddingConfig.api_key && (
              <Text color="green">✓ Embedding API key: {"*".repeat(Math.min(embeddingConfig.api_key.length, 20))}</Text>
            )}
            {embeddingConfig.base_url && (
              <Text color="green">✓ Embedding Base URL: {embeddingConfig.base_url}</Text>
            )}
            {embeddingConfig.vec_dim && (
              <Text color="green">✓ Vector dimension: {embeddingConfig.vec_dim}</Text>
            )}
          </>
        )}
        <Text>
          {embeddingField === "question" 
            ? "Would you like to configure an embedding model for RAG features?"
            : `Enter ${getFieldLabel()}:`}
        </Text>
        {isSaving ? (
          <Text color="yellow">Saving configuration...</Text>
        ) : (
          <Box flexDirection="row">
            <Text color="grey">{"> "}{getFieldLabel()}: </Text>
            <TextInput
              value={currentInput}
              onChange={setCurrentInput}
              onSubmit={handleEmbeddingStepInput}
              placeholder={getPlaceholder()}
            />
          </Box>
        )}
      </Box>
    );
  };

  return (
    <Box flexDirection="column">
      <Box
        borderStyle="round"
        borderColor="grey"
        padding={1}
        marginBottom={1}
        flexDirection="column"
      >
        <Box flexDirection="column">
          <Text>
            It looks like this is your first time running the CLI (config.json not found).
          </Text>
          <Text>
            Follow these steps to setup your first LLM.
          </Text>
        </Box>
        <Box flexDirection="column">
        {step === "model" && renderModelStep()}
        {step === "embedding" && renderEmbeddingStep()}
        </Box>
      </Box>


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

