import type { AgentEvent } from "../runtime/rpc-types.ts";

export type MessageRole = "user" | "assistant" | "system";

export type MessageType =
  | "text"
  | "error"
  | "command"
  | "info"
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
  eventData?: AgentEvent;
}

export function createMessage(
  role: MessageRole,
  content: string,
  type: MessageType = "text",
): Message {
  return {
    id: crypto.randomUUID(),
    role,
    content,
    timestamp: new Date(),
    type,
  };
}

export function agentEventToMessage(event: AgentEvent): Message {
  const timestamp = event.timestamp ? new Date(event.timestamp) : new Date();
  const baseMessage = {
    id: crypto.randomUUID(),
    role: "system" as const,
    timestamp: Number.isNaN(timestamp.getTime()) ? new Date() : timestamp,
    eventData: event,
  };

  switch (event.type) {
    case "tool_call_start":
    case "tool_call_end":
      return { ...baseMessage, content: event.type, type: "event_tool_call" };
    case "agent_thought":
      return { ...baseMessage, content: "thought", type: "event_agent_thought" };
    case "agent_start":
      return { ...baseMessage, content: "agent-start", type: "event_agent_start" };
    case "agent_end":
      return { ...baseMessage, content: "agent-end", type: "event_agent_end" };
    case "agent_error":
      return { ...baseMessage, content: "agent-error", type: "event_agent_error" };
    case "agent_routed":
      return { ...baseMessage, content: "agent-routed", type: "event_agent_routed" };
    case "log_message":
      return { ...baseMessage, content: "log", type: "event_log" };
    default:
      return { ...baseMessage, content: JSON.stringify(event.data), type: "info" };
  }
}
