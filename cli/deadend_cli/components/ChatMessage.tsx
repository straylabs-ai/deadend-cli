import { Box, Text } from "ink";
import type { Message } from "../types/message.ts";
import type {
  ToolCallStartData,
  ToolCallEndData,
  AgentThoughtData,
  AgentEndData,
  AgentErrorData,
  LogMessageData,
} from "../types/rpc.ts";

// Helper to truncate long strings
function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 3) + "...";
}

// Helper to wrap long text into multiple lines
function wrapText(str: string, maxLineLen: number, maxLines: number = 10): string {
  const lines: string[] = [];
  let remaining = str;

  while (remaining.length > 0 && lines.length < maxLines) {
    if (remaining.length <= maxLineLen) {
      lines.push(remaining);
      break;
    }
    // Try to break at a space
    let breakPoint = remaining.lastIndexOf(' ', maxLineLen);
    if (breakPoint <= 0) breakPoint = maxLineLen;
    lines.push(remaining.slice(0, breakPoint));
    remaining = remaining.slice(breakPoint).trimStart();
  }

  if (remaining.length > 0 && lines.length >= maxLines) {
    lines[lines.length - 1] += "...";
  }

  return lines.join('\n');
}

// Format timestamp as HH:MM:SS
function formatTime(date: Date): string {
  return date.toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export interface ChatMessageProps {
  message: Message;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const time = formatTime(message.timestamp);

  // User messages
  if (message.role === "user") {
    return (
      <Box marginBottom={1}>
        <Text color="gray" dimColor>
          [{time}]{" "}
        </Text>
        <Text color="white" bold>
          {">"} {message.content}
        </Text>
      </Box>
    );
  }

  // Event-based messages
  switch (message.type) {
    case "event_tool_call":
      return <ToolCallMessage message={message} time={time} />;

    case "event_agent_thought":
      return <AgentThoughtMessage message={message} time={time} />;

    case "event_agent_start":
      return (
        <Box marginBottom={1}>
          <Text color="gray" dimColor>
            [{time}]{" "}
          </Text>
          <Text color="yellow">{"🤖 "}{message.content}</Text>
        </Box>
      );

    case "event_agent_end":
      return <AgentEndMessage message={message} time={time} />;

    case "event_agent_error":
      return <AgentErrorMessage message={message} time={time} />;

    case "event_agent_routed":
      return (
        <Box marginBottom={1}>
          <Text color="gray" dimColor>
            [{time}]{" "}
          </Text>
          <Text color="yellow">{"🔀 "}{message.content}</Text>
        </Box>
      );

    case "event_log":
      return <LogMessage message={message} time={time} />;

    case "error":
      return (
        <Box marginBottom={1}>
          <Text color="gray" dimColor>
            [{time}]{" "}
          </Text>
          <Text color="red">{"✗ "}{message.content}</Text>
        </Box>
      );

    case "info":
      return (
        <Box marginBottom={1}>
          <Text color="gray" dimColor>
            [{time}]{" "}
          </Text>
          <Text color="gray" italic>
            {message.content}
          </Text>
        </Box>
      );

    case "command":
      return (
        <Box marginBottom={1}>
          <Text color="gray" dimColor>
            [{time}]{" "}
          </Text>
          <Text color="cyan">{message.content}</Text>
        </Box>
      );

    // Default text messages (assistant, system)
    default: {
      const prefix = message.role === "assistant" ? "AI: " : "";
      const color = message.role === "assistant" ? "red" : "yellow";
      return (
        <Box marginBottom={1}>
          <Text color="gray" dimColor>
            [{time}]{" "}
          </Text>
          <Text color={color} bold={message.role === "assistant"}>
            {prefix}
          </Text>
          <Text color="white">{message.content}</Text>
        </Box>
      );
    }
  }
}

// Tool call message (combines start/end display)
function ToolCallMessage({ message, time }: { message: Message; time: string }) {
  const event = message.eventData;
  if (!event) {
    return (
      <Box marginBottom={1}>
        <Text color="gray" dimColor>
          [{time}]{" "}
        </Text>
        <Text color="cyan">{"⚡ "}{message.content}</Text>
      </Box>
    );
  }

  if (event.type === "tool_call_start") {
    const data = event.data as unknown as ToolCallStartData;
    // Show args (up to 12 lines of 100 chars)
    const argsDisplay = data.args ? wrapText(data.args, 100, 12) : "";
    return (
      <Box flexDirection="column" marginBottom={1}>
        <Box>
          <Text color="gray" dimColor>
            [{time}]{" "}
          </Text>
          <Text color="cyan" bold>
            {"⚡ "}{data.tool_name}
          </Text>
        </Box>
        {argsDisplay && (
          <Box marginLeft={10}>
            <Text color="gray">{argsDisplay}</Text>
          </Box>
        )}
      </Box>
    );
  }

  if (event.type === "tool_call_end") {
    const data = event.data as unknown as ToolCallEndData;
    const statusColor = data.success ? "green" : "red";
    const statusIcon = data.success ? "✓" : "✗";
    const duration = data.duration_ms ? ` (${data.duration_ms.toFixed(0)}ms)` : "";

    // Show result (up to 15 lines of 100 chars)
    let resultText = data.error || "";
    if (!resultText && data.result) {
      resultText = wrapText(data.result, 100, 15);
    }

    return (
      <Box flexDirection="column" marginBottom={1}>
        <Box>
          <Text color="gray" dimColor>
            [{time}]{" "}
          </Text>
          <Text color={statusColor}>
            {statusIcon} {data.tool_name}{duration}
          </Text>
        </Box>
        {resultText && (
          <Box marginLeft={10}>
            <Text color={data.error ? "red" : "gray"}>{resultText}</Text>
          </Box>
        )}
      </Box>
    );
  }

  return null;
}

// Agent thought message - shows LLM response content
function AgentThoughtMessage({ message, time }: { message: Message; time: string }) {
  const data = message.eventData?.data as unknown as AgentThoughtData | undefined;
  // Prefer the full thought over summary for better visibility
  const displayText = data?.thought || data?.summary || message.content;
  // Wrap across multiple lines (up to 25 lines of 100 chars)
  const wrappedText = wrapText(displayText, 100, 25);

  return (
    <Box flexDirection="column" marginBottom={1}>
      <Box>
        <Text color="gray" dimColor>
          [{time}]{" "}
        </Text>
        <Text color="magenta">{"💭 LLM Response:"}</Text>
      </Box>
      <Box marginLeft={10}>
        <Text color="white">{wrappedText}</Text>
      </Box>
    </Box>
  );
}

// Agent end message (with confidence)
function AgentEndMessage({ message, time }: { message: Message; time: string }) {
  const data = message.eventData?.data as unknown as AgentEndData | undefined;
  const confidence = data?.confidence_score
    ? Math.round(data.confidence_score * 100)
    : null;
  const isHighConfidence = confidence !== null && confidence >= 80;

  return (
    <Box flexDirection="column" marginY={1}>
      <Text color="yellow">{"─".repeat(50)}</Text>
      <Box paddingX={1} flexDirection="column">
        <Box>
          <Text color="gray" dimColor>
            [{time}]{" "}
          </Text>
          <Text color={isHighConfidence ? "green" : "yellow"} bold>
            Agent: {message.eventData?.agent_name || "agent"}
          </Text>
        </Box>
        {confidence !== null && (
          <Box marginLeft={10}>
            <Text color={isHighConfidence ? "green" : "yellow"}>
              Confidence: {confidence}%
            </Text>
          </Box>
        )}
        {data?.notes && (
          <Box marginLeft={10}>
            <Text color="white">{wrapText(data.notes, 80, 5)}</Text>
          </Box>
        )}
      </Box>
      <Text color="yellow">{"─".repeat(50)}</Text>
    </Box>
  );
}

// Agent error message
function AgentErrorMessage({ message, time }: { message: Message; time: string }) {
  const data = message.eventData?.data as unknown as AgentErrorData | undefined;

  return (
    <Box flexDirection="column" marginY={1}>
      <Text color="red">{"─".repeat(50)}</Text>
      <Box paddingX={1} flexDirection="column">
        <Box>
          <Text color="gray" dimColor>
            [{time}]{" "}
          </Text>
          <Text color="red" bold>
            {"✗ Error: "}{data?.error_type || "Unknown"}
          </Text>
        </Box>
        <Box marginLeft={10}>
          <Text color="red">{wrapText(data?.error_message || message.content, 80, 5)}</Text>
        </Box>
      </Box>
      <Text color="red">{"─".repeat(50)}</Text>
    </Box>
  );
}

// Log message
function LogMessage({ message, time }: { message: Message; time: string }) {
  const data = message.eventData?.data as unknown as LogMessageData | undefined;
  const level = data?.level || "info";

  const levelColors: Record<string, string> = {
    debug: "gray",
    info: "white",
    warning: "yellow",
    error: "red",
  };
  const color = levelColors[level] || "white";

  return (
    <Box marginBottom={0}>
      <Text color="gray" dimColor>
        [{time}]{" "}
      </Text>
      <Text color={color} dimColor={level === "debug"}>
        {"⋯ "}{truncate(data?.message || message.content, 70)}
      </Text>
    </Box>
  );
}
