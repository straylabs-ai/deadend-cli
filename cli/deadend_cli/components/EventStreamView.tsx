import { Box, Text } from "ink";
import type { AgentEvent, ToolCallStartData, ToolCallEndData, AgentThoughtData, AgentEndData, AgentErrorData, LogMessageData } from "../types/rpc.ts";

export interface EventStreamViewProps {
  /** List of events to display */
  events: AgentEvent[];
  /** Maximum number of ephemeral events to show (default 8) */
  maxVisible?: number;
  /** Whether to show permanent results (agent_end with high confidence) */
  showPermanent?: boolean;
}

// Helper to truncate long strings
function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 3) + "...";
}

// Parse tool args for display
function parseToolArgs(args: string): string {
  try {
    const parsed = JSON.parse(args);
    // Format common fields
    if (parsed.payload) {
      return `payload: ${truncate(parsed.payload, 60)}`;
    }
    if (parsed.command) {
      return `command: ${truncate(parsed.command, 60)}`;
    }
    if (parsed.url) {
      return `url: ${truncate(parsed.url, 60)}`;
    }
    // Generic display
    return truncate(args, 80);
  } catch {
    return truncate(args, 80);
  }
}

// Tool call start event
function ToolCallStart({ data }: { data: ToolCallStartData }) {
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text color="cyan" bold>
        {"⚡ "}{data.tool_name}
      </Text>
      <Box marginLeft={3}>
        <Text color="gray">{parseToolArgs(data.args)}</Text>
      </Box>
    </Box>
  );
}

// Tool call end event with boxed output
function ToolCallEnd({ data }: { data: ToolCallEndData }) {
  const statusColor = data.success ? "green" : "red";
  const statusIcon = data.success ? "✓" : "✗";
  const duration = data.duration_ms ? ` (${data.duration_ms.toFixed(1)}ms)` : "";

  // Parse result for display
  let resultLines: string[] = [];
  if (data.error) {
    resultLines = [data.error];
  } else if (data.result) {
    // Try to parse JSON for pretty display
    try {
      const parsed = JSON.parse(data.result);
      if (typeof parsed === "object") {
        resultLines = JSON.stringify(parsed, null, 2).split("\n").slice(0, 5);
        if (JSON.stringify(parsed, null, 2).split("\n").length > 5) {
          resultLines.push("...");
        }
      } else {
        resultLines = [truncate(String(parsed), 60)];
      }
    } catch {
      // Not JSON, display as-is
      resultLines = data.result.split("\n").slice(0, 5);
      if (data.result.split("\n").length > 5) {
        resultLines.push("...");
      }
    }
  }

  return (
    <Box flexDirection="column" marginLeft={3} marginBottom={1}>
      <Box
        borderStyle="round"
        borderColor={statusColor}
        paddingX={1}
        flexDirection="column"
      >
        <Text color={statusColor}>
          {statusIcon} {data.tool_name}{duration}
        </Text>
        {resultLines.map((line, i) => (
          <Text key={i} color="white">{truncate(line, 65)}</Text>
        ))}
      </Box>
    </Box>
  );
}

// Agent thought event
function AgentThought({ data }: { data: AgentThoughtData }) {
  const displayText = data.summary || truncate(data.thought, 70);
  return (
    <Box marginBottom={1}>
      <Text color="gray" dimColor>
        {"💭 "}{displayText}
      </Text>
    </Box>
  );
}

// Agent end event (final result - permanent)
function AgentEnd({ data, agentName }: { data: AgentEndData; agentName?: string }) {
  const isHighConfidence = data.confidence_score >= 0.8;
  const confidencePercent = Math.round(data.confidence_score * 100);

  return (
    <Box flexDirection="column" marginY={1}>
      <Text color="yellow">{"═".repeat(67)}</Text>
      <Box paddingX={1} flexDirection="column">
        {agentName && (
          <Text color={isHighConfidence ? "green" : "yellow"} bold>
            Agent: {agentName}
          </Text>
        )}
        <Text color={isHighConfidence ? "green" : "yellow"}>
          Confidence: {confidencePercent}%
        </Text>
        {data.notes && (
          <Text color="white">{truncate(data.notes, 60)}</Text>
        )}
        {data.thought_summary && (
          <Text color="gray" dimColor>{truncate(data.thought_summary, 60)}</Text>
        )}
      </Box>
      <Text color="yellow">{"═".repeat(67)}</Text>
    </Box>
  );
}

// Agent error event
function AgentError({ data }: { data: AgentErrorData }) {
  return (
    <Box flexDirection="column" marginY={1}>
      <Text color="red">{"═".repeat(67)}</Text>
      <Box paddingX={1} flexDirection="column">
        <Text color="red" bold>
          {"✗ Error: "}{data.error_type}
        </Text>
        <Text color="red">{truncate(data.error_message, 60)}</Text>
        {data.partial_reasoning && (
          <Text color="gray" dimColor>{truncate(data.partial_reasoning, 50)}</Text>
        )}
      </Box>
      <Text color="red">{"═".repeat(67)}</Text>
    </Box>
  );
}

// Log message event
function LogMessage({ data }: { data: LogMessageData }) {
  const levelColors: Record<string, string> = {
    debug: "gray",
    info: "white",
    warning: "yellow",
    error: "red",
  };
  const color = levelColors[data.level] || "white";

  return (
    <Box marginBottom={0}>
      <Text color={color} dimColor={data.level === "debug"}>
        {"⋯ "}{truncate(data.message, 70)}
      </Text>
    </Box>
  );
}

// Agent routed event
function AgentRouted({ event }: { event: AgentEvent }) {
  const data = event.data as { selected_agent?: string; reasoning?: string };
  return (
    <Box marginBottom={1}>
      <Text color="yellow">
        {"🔀 → "}{data.selected_agent || "unknown"}
      </Text>
      {data.reasoning && (
        <Text color="gray" dimColor> ({truncate(data.reasoning, 40)})</Text>
      )}
    </Box>
  );
}

// Render a single event
function EventItem({ event }: { event: AgentEvent }) {
  switch (event.type) {
    case "tool_call_start":
      return <ToolCallStart data={event.data as unknown as ToolCallStartData} />;
    case "tool_call_end":
      return <ToolCallEnd data={event.data as unknown as ToolCallEndData} />;
    case "agent_thought":
      return <AgentThought data={event.data as unknown as AgentThoughtData} />;
    case "agent_end":
      return <AgentEnd data={event.data as unknown as AgentEndData} agentName={event.agent_name} />;
    case "agent_error":
      return <AgentError data={event.data as unknown as AgentErrorData} />;
    case "agent_routed":
      return <AgentRouted event={event} />;
    case "log_message":
      return <LogMessage data={event.data as unknown as LogMessageData} />;
    case "agent_start":
      return (
        <Box marginBottom={1}>
          <Text color="yellow">
            {"🤖 "}{event.agent_name || "agent"}: Starting task...
          </Text>
        </Box>
      );
    case "approval_required":
      return (
        <Box marginBottom={1} flexDirection="column">
          <Text color="magenta" bold>
            {"⏸ Approval Required"}
          </Text>
          <Text color="magenta">
            Tool: {(event.data as { tool_name?: string }).tool_name}
          </Text>
        </Box>
      );
    case "workflow_interrupted":
      return (
        <Box marginY={1}>
          <Text color="red" bold>
            {"⏹ Workflow Interrupted: "}{(event.data as { reason?: string }).reason}
          </Text>
        </Box>
      );
    default:
      // Don't display unhandled event types
      return null;
  }
}

// Check if an event is permanent (should stay visible after completion)
function isPermanentEvent(event: AgentEvent): boolean {
  if (event.type === "agent_end") {
    const data = event.data as unknown as AgentEndData;
    return data.confidence_score >= 0.6; // Show any significant result
  }
  if (event.type === "agent_error") {
    return true;
  }
  if (event.type === "workflow_interrupted") {
    return true;
  }
  return false;
}

export function EventStreamView({
  events,
  maxVisible = 8,
  showPermanent = true,
}: EventStreamViewProps) {
  // Separate permanent and ephemeral events
  const permanentEvents = events.filter(isPermanentEvent);
  const ephemeralEvents = events.filter((e) => !isPermanentEvent(e));

  // Only show the last N ephemeral events
  const visibleEphemeral = ephemeralEvents.slice(-maxVisible);

  return (
    <Box flexDirection="column">
      {/* Ephemeral events (scroll away) */}
      {visibleEphemeral.map((event, index) => (
        <EventItem key={`${event.timestamp}-${index}`} event={event} />
      ))}

      {/* Permanent events (always visible) */}
      {showPermanent &&
        permanentEvents.map((event, index) => (
          <EventItem key={`perm-${event.timestamp}-${index}`} event={event} />
        ))}
    </Box>
  );
}
