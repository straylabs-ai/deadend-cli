import type {
  JsonRpcRequest,
  JsonRpcError,
  RpcClient,
  RpcService,
} from "../types/rpc.ts";

// Re-export stdio and deadend clients for convenience
export {
  StdioRpcClient,
  createStdioRpcClient,
  type StdioRpcClientOptions,
} from "./stdio-rpc-client.ts";

export {
  DeadEndRpcClient,
  createDeadEndRpcClient,
  type DeadEndRpcClientOptions,
  type ReconEvent,
  type ExploitEvent,
  type DoneEvent,
  type DeadEndTaskEvent,
} from "./deadend-rpc-client.ts";

export class JsonRpcClient implements RpcClient {
  private requestId = 0;
  private service: RpcService;

  constructor(service: RpcService) {
    this.service = service;
  }

  async call(method: string, params?: unknown): Promise<unknown> {
    const id = ++this.requestId;
    const _request: JsonRpcRequest = {
      jsonrpc: "2.0",
      id,
      method,
      params,
    };

    try {
      const response = await this.service.handle(method, params);
      return response;
    } catch (error) {
      const rpcError: JsonRpcError = {
        code: -32000,
        message: error instanceof Error ? error.message : "Unknown error",
        data: error,
      };
      throw rpcError;
    }
  }

  notify(method: string, params?: unknown): void {
    // Notifications don't expect a response
    this.service.handle(method, params).catch(() => {
      // Ignore errors for notifications
    });
  }
}

