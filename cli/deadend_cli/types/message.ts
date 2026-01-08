export type MessageRole = "user" | "assistant" | "system";
export type MessageType = "text" | "code" | "error" | "command" | "info";

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: Date;
  type: MessageType;
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

