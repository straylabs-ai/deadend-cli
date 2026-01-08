import { useState, useCallback } from "react";
import { Box, Text } from "ink";
import TextInput from "ink-text-input";
import { createDefaultConfig } from "../lib/config.ts";

interface PresetupProps {
  onComplete: () => void;
}

export function Presetup({ onComplete }: PresetupProps) {
  const [step, setStep] = useState(0);
  const [apiKey, setApiKey] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = useCallback(async () => {
    if (step === 0) {
      // Move to next step or complete
      setStep(1);
    } else if (step === 1) {
      // Create config
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
    }
  }, [step, onComplete]);

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
          <Text color="cyan" bold >
            Setup Step 1/2: Initial Configuration
          </Text>
          <Text >
            We'll create a default configuration file at:
          </Text>
          <Text color="gray">
            .cache/deadend/config.toml
          </Text>
          <Text >
            Press Enter to continue, or type "skip" to use defaults.
          </Text>
          
          <Box
            borderStyle="round"
            borderColor="cyan"
            padding={1}
            marginTop={1}
          >
            <Box flexDirection="row">
              <Text color="cyan">{"> "}</Text>
              <TextInput
                value={apiKey}
                onChange={setApiKey}
                onSubmit={() => {
                  if (apiKey.toLowerCase() === "skip") {
                    handleSkip();
                  } else {
                    handleSubmit();
                  }
                }}
                placeholder="Press Enter to continue or type 'skip'..."
              />
            </Box>
          </Box>
        </Box>
      )}

      {step === 1 && (
        <Box flexDirection="column">
          <Text color="cyan" bold >
            Setup Step 2/2: Creating Configuration
          </Text>
          {isCreating ? (
            <Text color="yellow">Creating configuration file...</Text>
          ) : (
            <Text>Press Enter to create the configuration file.</Text>
          )}
          
          {error && (
            <Text color="red">
              Error: {error}
            </Text>
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

