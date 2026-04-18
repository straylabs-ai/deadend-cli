import type {
  AgentEvent,
  AgentTaskSnapshotResult,
  AllInitResult,
  GetValidationConfigResult,
  InstantiateAgentResult,
  InterruptAgentResult,
  SetValidationConfigResult,
  TaskEvent,
} from "./rpc-types.ts";
import { StdioRpcClient } from "./stdio-rpc-client.ts";

export interface DeadendRpcClientOptions {
  pythonCommand: string;
  commandArgs: string[];
  cwd: string;
  env: Record<string, string>;
  logFile?: string;
}

export class DeadendRpcClient {
  private readonly client: StdioRpcClient;

  constructor(options: DeadendRpcClientOptions) {
    this.client = new StdioRpcClient(options);
  }

  async start(): Promise<void> {
    await this.client.start();
  }

  async ping(): Promise<boolean> {
    return await this.client.ping();
  }

  async initAll(timeout = 300_000): Promise<AllInitResult> {
    return await this.client.call<AllInitResult>("init_all", undefined, timeout);
  }

  subscribeEvents(): { generator: AsyncGenerator<AgentEvent>; abort: () => void } {
    return this.client.stream<AgentEvent>("subscribe_events", {});
  }

  async interrupt(sessionId: string, reason?: string): Promise<{ status: string }> {
    return await this.client.call("interrupt", {
      session_id: sessionId,
      reason: reason ?? "User requested interruption",
    });
  }

  async interruptAgent(agentId: string): Promise<InterruptAgentResult> {
    const stream = this.client.stream<InterruptAgentResult>("interrupt_agent", {
      agent_id: agentId,
    });

    for await (const result of stream.generator) {
      return result;
    }

    return { status: "unknown" };
  }

  async instantiateAgent(
    target: string,
    provider?: string,
    modelName?: string,
    workspaceRoot?: string,
    proxyUrl?: string,
  ): Promise<InstantiateAgentResult> {
    return await this.client.call("instantiate_agent", {
      target,
      ...(provider ? { provider } : {}),
      ...(modelName ? { model_name: modelName } : {}),
      ...(workspaceRoot ? { workspace_root: workspaceRoot } : {}),
      ...(proxyUrl ? { proxy_url: proxyUrl } : {}),
    });
  }

  async getAgentTasks(agentId: string): Promise<AgentTaskSnapshotResult> {
    return await this.client.call("get_agent_tasks", {
      agent_id: agentId,
    });
  }

  embedTarget(
    agentId: string,
    target: string,
  ): { generator: AsyncGenerator<TaskEvent>; abort: () => void } {
    const stream = this.client.stream<TaskEvent>("embed_target", {
      agent_id: agentId,
      target,
    });

    return {
      abort: stream.abort,
      generator: (async function* () {
        for await (const event of stream.generator) {
          if (event.phase === "error") {
            throw new Error(extractTaskEventError(event));
          }

          if ("status" in event && event.status === "failed") {
            throw new Error(event.reason || "Failed to embed target");
          }

          yield event;
        }
      })(),
    };
  }

  runAgentRecursive(
    agentId: string,
    prompt: string,
  ): { generator: AsyncGenerator<TaskEvent>; abort: () => void } {
    return this.client.stream<TaskEvent>("run_agent_recursive", {
      agent_id: agentId,
      prompt,
    });
  }

  runAgentSupervisor(
    agentId: string,
    prompt: string,
  ): { generator: AsyncGenerator<TaskEvent>; abort: () => void } {
    return this.client.stream<TaskEvent>("run_agent_supervisor", {
      agent_id: agentId,
      prompt,
    });
  }

  async getValidationConfig(): Promise<GetValidationConfigResult> {
    return await this.client.call<GetValidationConfigResult>("get_validation_config", {});
  }

  async setValidationConfig(params: {
    preset?: string;
    validation_format?: string | null;
    validation_type?: string | null;
    pattern?: string | null;
  }): Promise<SetValidationConfigResult> {
    return await this.client.call<SetValidationConfigResult>("set_validation_config", params);
  }

  async addModel(params: {
    provider: string;
    model_name: string;
    api_key: string | null;
    base_url: string | null;
    type_model: string | null;
    vec_dim: number | null;
  }): Promise<unknown> {
    return await this.client.call("add_model", params);
  }

  async shutdown(): Promise<unknown> {
    await this.client.shutdown();
    return { status: "ok" };
  }

  close(): void {
    this.client.close();
  }
}

function extractTaskEventError(event: TaskEvent): string {
  if (typeof event.data === "object" && event.data && "message" in event.data) {
    const message = (event.data as { message?: unknown }).message;
    if (typeof message === "string" && message.trim().length > 0) {
      return message;
    }
  }

  return event.reason || "Unknown task error";
}
