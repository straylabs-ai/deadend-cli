import type { AgentEvent } from "./rpc.ts";

export type MessageRole = "user" | "assistant" | "system";

export type MessageType =
  | "text"
  | "code"
  | "error"
  | "command"
  | "info"
  // Event-based message types
  | "event_tool_call"
  | "event_agent_thought"
  | "event_agent_start"
  | "event_agent_end"
  | "event_agent_error"
  | "event_agent_routed"
  | "event_log";

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: Date;
  type: MessageType;
  /** Raw event data for event-based messages */
  eventData?: AgentEvent;
}

export function createMessage(
  role: MessageRole,
  content: string,
  type: MessageType = "text"
): Message {
  return {
    id: crypto.randomUUID(),
    role,
    content,
    timestamp: new Date(),
    type,
  };
}

/**
 * Convert an AgentEvent to a Message for display in chat history.
 */
export function agentEventToMessage(event: AgentEvent): Message {
  const baseMessage = {
    id: crypto.randomUUID(),
    role: "system" as MessageRole,
    timestamp: new Date(event.timestamp),
    eventData: event,
  };

  switch (event.type) {
    case "tool_call_start":
    case "tool_call_end": {
      const data = event.data as { tool_name?: string; result?: string; error?: string };
      const content = event.type === "tool_call_start"
        ? `Tool: ${data.tool_name}`
        : `Tool ${data.tool_name}: ${data.error || data.result || "completed"}`;
      return { ...baseMessage, content, type: "event_tool_call" };
    }

    case "agent_thought": {
      const data = event.data as { thought?: string; summary?: string };
      return {
        ...baseMessage,
        content: data.summary || data.thought || "",
        type: "event_agent_thought",
      };
    }

    case "agent_start": {
      const data = event.data as { task?: string };
      return {
        ...baseMessage,
        content: `Agent started: ${event.agent_name || "agent"} - ${data.task || ""}`,
        type: "event_agent_start",
      };
    }

    case "agent_end": {
      const data = event.data as { confidence_score?: number; notes?: string };
      const confidence = data.confidence_score
        ? `${Math.round(data.confidence_score * 100)}%`
        : "";
      return {
        ...baseMessage,
        content: `Agent completed: ${event.agent_name || "agent"} (${confidence}) ${data.notes || ""}`,
        type: "event_agent_end",
      };
    }

    case "agent_error": {
      const data = event.data as { error_type?: string; error_message?: string };
      return {
        ...baseMessage,
        content: `Error: ${data.error_type} - ${data.error_message}`,
        type: "event_agent_error",
      };
    }

    case "agent_routed": {
      const data = event.data as { selected_agent?: string; reasoning?: string };
      return {
        ...baseMessage,
        content: `Routing to ${data.selected_agent}: ${data.reasoning || ""}`,
        type: "event_agent_routed",
      };
    }

    case "log_message": {
      const data = event.data as { message?: string; level?: string };
      return {
        ...baseMessage,
        content: data.message || "",
        type: "event_log",
      };
    }

    default:
      return {
        ...baseMessage,
        content: JSON.stringify(event.data),
        type: "info",
      };
  }
}
