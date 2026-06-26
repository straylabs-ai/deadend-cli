import {
  BoxRenderable,
  InputRenderable,
  InputRenderableEvents,
  ScrollBoxRenderable,
  TextRenderable,
  type CliRenderer,
} from "@opentui/core";
import type { KeyEvent } from "@opentui/core";
import { COMMANDS, findCommandSuggestions, formatHelpText, parseCommand } from "./commands.ts";
import {
  isCopyShortcut,
  isCopyShortcutSequence,
  isCtrlCKey,
  isInterruptShortcut,
  isPasteShortcut,
  isPasteShortcutSequence,
  isPlainCtrlCQuit,
  isToggleModeShortcut,
  isToggleTaskPopupShortcut,
  isToggleToolOutputShortcut,
  readClipboardText,
  writeClipboardText,
} from "./keyboard-shortcuts.ts";
import { agentEventToMessage, createMessage, type Message } from "./messages.ts";
import type { CliArgs } from "../cli/args.ts";
import {
  getDefaultChatModel,
  hasEmbeddingModel,
  hasRegularModel,
  loadAppConfig,
  type AppConfig,
} from "../runtime/config-store.ts";
import { DeadendRpcClient } from "../runtime/deadend-rpc-client.ts";
import type {
  AgentEvent,
  AgentTaskSnapshotResult,
  AllInitResult,
  InitResult,
  TaskEvent,
} from "../runtime/rpc-types.ts";
import {
  loadSettings,
  saveSettings,
  type CliSettings,
} from "../runtime/settings-store.ts";
import { resolve } from "node:path";
import { createBanner } from "../ui/banner.ts";
import { theme } from "../ui/theme.ts";

const INIT_STATUS_PHRASES = [
  "Unfolding the map...",
  "Descending into the black archive...",
  "Unsealing the hollow gate...",
  "Entering the long night...",
  "Walking the ash roads...",
  "Reading from the bone ledger...",
  "Stirring the buried sigils...",
  "Tracing the aether lattice...",
  "Consulting the star vellum...",
  "Unbinding the sealed geometry...",
  "Opening the seventh fold...",
  "Threading the moonlit ward...",
  "Speaking to the hidden current...",
  "Stepping where the light forgets...",
  "Following the silence between names...",
  "Opening the road behind the stars...",
  "Listening for what the dark remembers...",
  "Walking the edge of the unseen...",
  "Entering the place beneath maps...",
  "Spelunking the old circuits...",
  "Reading the ghost in the wire...",
  "Opening the hidden portcullis...",
  "Tracing the forbidden pathways...",
  "Entering the machine catacombs...",
  "Following the signal through the veil...",
] as const;

type ExecutionMode = "yolo" | "supervisor";
type ScreenMode = "init" | "setup" | "chat" | "fatal";
type TaskPhase = "init" | "recon" | "exploit" | "supervising" | "done" | "error" | null;
type SetupStep =
  | "provider"
  | "model"
  | "api_key"
  | "base_url"
  | "embedding_question"
  | "embedding_provider"
  | "embedding_model"
  | "embedding_api_key"
  | "embedding_base_url"
  | "embedding_vec_dim"
  | "saving";

interface PrimaryModelDraft {
  provider: string;
  model: string;
  apiKey?: string;
  baseUrl?: string;
}

interface EmbeddingDraft {
  provider: string;
  model: string;
  apiKey?: string;
  baseUrl?: string;
  vecDim?: number;
}

interface TaskState {
  isRunning: boolean;
  phase: TaskPhase;
  target: string | null;
  agentId: string | null;
  isTargetEmbedded: boolean;
  task: string | null;
}

interface ChatRenderables {
  transcript: ScrollBoxRenderable;
  statusLine: TextRenderable;
  notificationBox: BoxRenderable;
  input: InputRenderable;
  modeText: TextRenderable;
  taskPopupHintText: TextRenderable;
  toolOutputText: TextRenderable;
  modelText: TextRenderable;
  runningText: TextRenderable;
  suggestionsBox: BoxRenderable;
  taskPopup: BoxRenderable;
  taskPopupContent: BoxRenderable;
}

interface SetupRenderables {
  promptText: TextRenderable;
  hintText: TextRenderable;
  summaryBox: BoxRenderable;
  errorText: TextRenderable;
  input: InputRenderable;
}

interface InitRenderables {
  statusText: TextRenderable;
  resultsBox: BoxRenderable;
  errorText: TextRenderable;
}

export class DeadendApp {
  private readonly root: BoxRenderable;
  private currentScreen: ScreenMode = "init";
  private rpcClient: DeadendRpcClient | null = null;
  private config: AppConfig = { configuredModels: [] };
  private settings: CliSettings = {};
  private executionMode: ExecutionMode = "yolo";
  private currentModel: { provider: string; model: string | null } | null = null;
  private taskState: TaskState = {
    isRunning: false,
    phase: null,
    target: null,
    agentId: null,
    isTargetEmbedded: false,
    task: null,
  };
  private componentResults: InitResult[] = [];
  private initView: InitRenderables | null = null;
  private setupView: SetupRenderables | null = null;
  private chatView: ChatRenderables | null = null;
  private currentInput = "";
  private readonly transcriptMessages: Message[] = [];
  private expandToolOutput = false;
  private showTaskPopup = false;
  private taskSnapshot: AgentTaskSnapshotResult | null = null;
  private taskSnapshotTimer: Timer | null = null;
  private taskSnapshotRefreshInFlight = false;
  private shutdownPromise: Promise<void> | null = null;
  private statusTimer: Timer | null = null;
  private statusFrame = 0;
  private currentStatusText = "";
  private setupStep: SetupStep = "provider";
  private primaryDraft: PrimaryModelDraft = { provider: "", model: "" };
  private embeddingDraft: EmbeddingDraft | null = null;
  private skipEmbedding = false;
  private notifications: Array<{ type: "info" | "warning" | "error"; message: string }> = [];
  private eventSubscriptionAbort: (() => void) | null = null;
  private runStreamAbort: (() => void) | null = null;
  private readonly rawInputHandler = (sequence: string): boolean => {
    if (sequence === "\u0003") {
      void this.shutdown().finally(() => {
        this.destroyAndExit();
      });
      return true;
    }

    if (isCopyShortcutSequence(sequence)) {
      void this.handleCopyShortcut();
      return true;
    }

    if (isPasteShortcutSequence(sequence)) {
      void this.handlePasteShortcut();
      return true;
    }

    return false;
  };

  constructor(
    private readonly renderer: CliRenderer,
    private readonly args: CliArgs,
    private readonly rpcLaunchConfig: {
      pythonCommand: string;
      commandArgs: string[];
      cwd: string;
      env: Record<string, string>;
      logFile: string;
      modeLabel: string;
      detail: string;
    },
  ) {
    this.root = new BoxRenderable(renderer, {
      width: "100%",
      height: "100%",
      flexDirection: "column",
      padding: 1,
    });
    this.renderer.root.add(this.root);
    this.renderer.prependInputHandler(this.rawInputHandler);
    this.renderer.keyInput.on("keypress", this.handleGlobalKeyPress);
    process.stdout.on("resize", this.handleTerminalResize);
  }

  async start(): Promise<void> {
    this.renderInitScreen();
    await this.bootstrap();
  }

  async shutdown(): Promise<void> {
    if (this.shutdownPromise) {
      await this.shutdownPromise;
      return;
    }

    this.shutdownPromise = this.performShutdown();
    await this.shutdownPromise;
  }

  destroyAndExit(): void {
    if (!this.renderer.isDestroyed) {
      this.renderer.destroy();
    }
    console.log("\n  Leaving the deadend. Stay sharp out there.\n");
  }

  private async performShutdown(): Promise<void> {
    this.stopStatusAnimation();
    this.stopTaskSnapshotPolling();

    if (this.taskState.isRunning) {
      await this.cancelRunningTask(true);
    }

    try {
      await this.rpcClient?.shutdown();
    } catch {
      // Ignore graceful shutdown errors during exit.
    }

    this.rpcClient?.close();
    this.renderer.removeInputHandler(this.rawInputHandler);
    this.renderer.keyInput.off("keypress", this.handleGlobalKeyPress);
    process.stdout.off("resize", this.handleTerminalResize);
  }

  private bootstrap = async (): Promise<void> => {
    try {
      this.setInitStatus(pickRandomInitStatus());
      this.rpcClient = new DeadendRpcClient(this.rpcLaunchConfig);
      await this.rpcClient.start();

      this.setInitStatus(pickRandomInitStatus());
      const isAlive = await this.rpcClient.ping();
      if (!isAlive) {
        throw new Error("RPC server not responding");
      }

      this.setInitStatus(pickRandomInitStatus());
      const initResult = await this.rpcClient.initAll(300_000);
      this.componentResults = initResult.components;
      this.renderInitResults(initResult.components);
      this.assertCriticalComponents(initResult);

      await this.loadConfigurationState();

      if (this.shouldShowSetup()) {
        this.renderSetupScreen();
        return;
      }

      this.renderChatScreen();
      await this.processStartupArgs();
    } catch (error) {
      this.renderFatalScreen(error instanceof Error ? error.message : String(error));
    }
  };

  private async loadConfigurationState(): Promise<void> {
    this.config = await loadAppConfig();
    this.settings = await loadSettings();

    this.executionMode = this.settings.executionMode ?? "yolo";

    const defaultModel = getDefaultChatModel(this.config);
    this.currentModel = this.settings.provider
      ? {
          provider: this.settings.provider,
          model: this.settings.model ?? null,
        }
      : defaultModel
        ? {
            provider: defaultModel.provider,
            model: defaultModel.model,
          }
        : null;
  }

  private shouldShowSetup(): boolean {
    return this.config.configuredModels.length === 0 || !hasRegularModel(this.config);
  }

  private renderInitScreen(): void {
    this.currentScreen = "init";
    this.clearRoot();

    const statusText = new TextRenderable(this.renderer, {
      content: "Connecting to RPC server...",
      fg: theme.textSecondary,
      wrapMode: "word",
    });

    const resultsBox = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "column",
      marginTop: 1,
      gap: 0,
    });

    const errorText = new TextRenderable(this.renderer, {
      content: "",
      fg: theme.statusError,
      wrapMode: "word",
    });

    this.root.add(createBanner(this.renderer));
    this.root.add(statusText);
    this.root.add(resultsBox);
    this.root.add(errorText);

    this.initView = { statusText, resultsBox, errorText };
    this.startStatusAnimation(statusText, "CLI initializing...");
  }

  private renderSetupScreen(): void {
    this.currentScreen = "setup";
    this.stopStatusAnimation();
    this.clearRoot();
    this.setupStep = "provider";
    this.primaryDraft = { provider: "", model: "" };
    this.embeddingDraft = null;
    this.skipEmbedding = false;
    this.currentInput = "";

    const panel = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "column",
      border: true,
      borderStyle: "rounded",
      borderColor: theme.inputBorder,
      padding: 1,
      gap: 1,
    });

    const promptText = new TextRenderable(this.renderer, {
      content: "",
      fg: theme.textPrimary,
      wrapMode: "word",
    });

    const hintText = new TextRenderable(this.renderer, {
      content: "",
      fg: theme.textSecondary,
      wrapMode: "word",
    });

    const summaryBox = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "column",
    });

    const errorText = new TextRenderable(this.renderer, {
      content: "",
      fg: theme.statusError,
      wrapMode: "word",
    });

    const input = new InputRenderable(this.renderer, {
      width: "100%",
      placeholder: "Enter value...",
      textColor: theme.textPrimary,
      placeholderColor: theme.textSecondary,
    });

    const inputRow = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "row",
      gap: 1,
      alignItems: "center",
    });
    inputRow.add(
      new TextRenderable(this.renderer, {
        width: 2,
        content: ">",
        fg: theme.inputPrompt,
      }),
    );
    inputRow.add(input);

    this.root.add(createBanner(this.renderer));
    panel.add(
      new TextRenderable(this.renderer, {
        content: "Initial setup",
        fg: theme.accent,
      }),
    );
    panel.add(promptText);
    panel.add(summaryBox);
    panel.add(inputRow);
    panel.add(hintText);
    panel.add(errorText);
    this.root.add(panel);

    this.setupView = {
      promptText,
      hintText,
      summaryBox,
      errorText,
      input,
    };

    input.on(InputRenderableEvents.INPUT, (value: string) => {
      this.currentInput = value;
    });
    input.on(InputRenderableEvents.ENTER, async (value: string) => {
      await this.handleSetupSubmit(value);
    });

    this.renderer.focusRenderable(input);
    this.refreshSetupView();
  }

  private renderChatScreen(): void {
    this.currentScreen = "chat";
    this.stopStatusAnimation();
    this.clearRoot();
    this.notifications = [];

    const transcript = new ScrollBoxRenderable(this.renderer, {
      width: "100%",
      flexGrow: 1,
      stickyScroll: true,
      stickyStart: "bottom",
      paddingBottom: 1,
    });

    const statusLine = new TextRenderable(this.renderer, {
      content: "",
      fg: theme.textSecondary,
      wrapMode: "word",
    });

    const notificationBox = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "column",
    });

    const chatColumn = new BoxRenderable(this.renderer, {
      flexGrow: 1,
      width: "100%",
      flexDirection: "column",
    });
    chatColumn.add(transcript);
    chatColumn.add(statusLine);
    chatColumn.add(notificationBox);

    const suggestionsBox = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "column",
      flexShrink: 0,
      visible: false,
      border: true,
      borderStyle: "rounded",
      borderColor: theme.inputBorder,
      backgroundColor: theme.notificationBackground,
      padding: 1,
    });

    const composer = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "column",
      flexShrink: 0,
      border: true,
      borderStyle: "rounded",
      borderColor: theme.inputBorder,
      padding: 1,
      gap: 1,
    });

    const input = new InputRenderable(this.renderer, {
      width: "100%",
      placeholder: "Type / to see commands...",
      textColor: theme.textPrimary,
      placeholderColor: theme.textSecondary,
    });

    const inputRow = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "row",
      gap: 1,
      alignItems: "center",
    });

    inputRow.add(
      new TextRenderable(this.renderer, {
        width: 2,
        content: "❯",
        fg: theme.inputPrompt,
      }),
    );
    inputRow.add(input);

    const footerRow = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "row",
      alignItems: "center",
    });

    const leftFooter = new BoxRenderable(this.renderer, {
      flexDirection: "row",
      gap: 1,
      alignItems: "center",
    });
    const spacer = new BoxRenderable(this.renderer, { flexGrow: 1 });
    const modeText = new TextRenderable(this.renderer, { content: "", fg: theme.inputModeYolo });
    const taskPopupHintText = new TextRenderable(this.renderer, { content: "", fg: theme.statusInfo });
    const toolOutputText = new TextRenderable(this.renderer, { content: "", fg: theme.statusInfo });
    const runningText = new TextRenderable(this.renderer, { content: "", fg: theme.textSecondary });
    const modelText = new TextRenderable(this.renderer, {
      content: "",
      fg: theme.textSecondary,
      wrapMode: "word",
    });

    leftFooter.add(modeText);
    leftFooter.add(
      new TextRenderable(this.renderer, {
        content: "(Shift+Tab)",
        fg: theme.textSecondary,
      }),
    );
    leftFooter.add(taskPopupHintText);
    leftFooter.add(toolOutputText);
    leftFooter.add(runningText);
    footerRow.add(leftFooter);
    footerRow.add(spacer);
    footerRow.add(modelText);

    composer.add(inputRow);
    composer.add(footerRow);

    const contentRow = new BoxRenderable(this.renderer, {
      width: "100%",
      flexGrow: 1,
      flexDirection: "row",
      gap: 1,
      marginBottom: 1,
    });
    const taskPopup = new BoxRenderable(this.renderer, {
      width: "30%",
      flexDirection: "column",
      border: true,
      borderStyle: "rounded",
      borderColor: theme.inputBorder,
      padding: 1,
      visible: false,
    });
    const taskPopupContent = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "column",
    });
    taskPopup.add(taskPopupContent);
    contentRow.add(chatColumn);
    contentRow.add(taskPopup);

    this.root.add(contentRow);
    this.root.add(composer);
    this.root.add(suggestionsBox);

    this.chatView = {
      transcript,
      statusLine,
      notificationBox,
      input,
      modeText,
      taskPopupHintText,
      toolOutputText,
      modelText,
      runningText,
      suggestionsBox,
      taskPopup,
      taskPopupContent,
    };

    input.on(InputRenderableEvents.INPUT, (value: string) => {
      this.currentInput = value;
      this.refreshComposer();
    });
    input.on(InputRenderableEvents.ENTER, async (value: string) => {
      await this.handleChatSubmit(value);
    });

    this.renderer.focusRenderable(input);
    this.seedTranscript();
    this.refreshComposer();
    this.refreshNotifications();
    this.refreshTaskPopup();
  }

  private renderFatalScreen(message: string): void {
    this.currentScreen = "fatal";
    this.stopStatusAnimation();
    this.clearRoot();

    this.root.add(createBanner(this.renderer));
    this.root.add(
      new TextRenderable(this.renderer, {
        content: `Failed to initialize: ${message}`,
        fg: theme.statusError,
        wrapMode: "word",
      }),
    );
  }

  private setInitStatus(text: string): void {
    if (!this.initView) {
      return;
    }

    this.startStatusAnimation(this.initView.statusText, text);
  }

  private renderInitResults(results: InitResult[]): void {
    if (!this.initView) {
      return;
    }

    clearChildren(this.initView.resultsBox);

    for (const result of results) {
      this.initView.resultsBox.add(this.createStatusResultRow(result));
    }
  }

  private createStatusResultRow(result: InitResult): BoxRenderable {
    const row = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "row",
      gap: 1,
    });

    row.add(
      new TextRenderable(this.renderer, {
        width: 2,
        content: "●",
        fg: result.success ? theme.statusSuccess : theme.statusError,
      }),
    );
    row.add(
      new TextRenderable(this.renderer, {
        content: result.component,
        fg: theme.textPrimary,
      }),
    );
    row.add(
      new TextRenderable(this.renderer, {
        content: result.message,
        fg: theme.textSecondary,
        wrapMode: "word",
      }),
    );

    return row;
  }

  private assertCriticalComponents(initResult: AllInitResult): void {
    const criticalComponents = new Set([
      "docker",
      "config",
      "model_registry",
      "rag",
      "shell_sandbox",
    ]);

    const failedCritical = initResult.failed_components.filter((component) =>
      criticalComponents.has(component),
    );

    if (failedCritical.length > 0) {
      throw new Error(`Critical components failed: ${failedCritical.join(", ")}`);
    }
  }

  private refreshSetupView(): void {
    if (!this.setupView) {
      return;
    }

    this.setupView.promptText.content = this.getSetupPrompt();
    this.setupView.hintText.content = this.getSetupHint();
    this.setupView.input.placeholder = this.getSetupPlaceholder();
    this.setupView.errorText.content = "";
    this.renderSetupSummary();
  }

  private renderSetupSummary(): void {
    if (!this.setupView) {
      return;
    }

    clearChildren(this.setupView.summaryBox);

    const lines = [
      this.primaryDraft.provider ? `provider: ${this.primaryDraft.provider}` : "",
      this.primaryDraft.model ? `model: ${this.primaryDraft.model}` : "",
      this.primaryDraft.baseUrl ? `base URL: ${this.primaryDraft.baseUrl}` : "",
      this.embeddingDraft?.provider ? `embedding provider: ${this.embeddingDraft.provider}` : "",
      this.embeddingDraft?.model ? `embedding model: ${this.embeddingDraft.model}` : "",
      this.skipEmbedding ? "embedding: skipped" : "",
    ].filter(Boolean);

    for (const line of lines) {
      this.setupView.summaryBox.add(
        new TextRenderable(this.renderer, {
          content: line,
          fg: theme.textSecondary,
        }),
      );
    }
  }

  private async handleSetupSubmit(value: string): Promise<void> {
    const trimmed = value.trim();
    if (!this.setupView) {
      return;
    }

    this.currentInput = "";
    this.setupView.input.value = "";
    this.setupView.errorText.content = "";

    switch (this.setupStep) {
      case "provider":
        if (!trimmed) {
          this.setupView.errorText.content = "Provider name is required.";
          return;
        }
        this.primaryDraft.provider = trimmed.toLowerCase();
        this.setupStep = "model";
        break;
      case "model":
        if (!trimmed) {
          this.setupView.errorText.content = "Model name is required.";
          return;
        }
        this.primaryDraft.model = trimmed;
        this.setupStep = "api_key";
        break;
      case "api_key":
        this.primaryDraft.apiKey = trimmed || undefined;
        this.setupStep = "base_url";
        break;
      case "base_url":
        this.primaryDraft.baseUrl = trimmed || undefined;
        this.setupStep = "embedding_question";
        break;
      case "embedding_question": {
        const normalized = trimmed.toLowerCase();
        if (normalized === "" || normalized === "skip" || normalized === "n" || normalized === "no") {
          this.skipEmbedding = true;
          await this.saveSetup();
          return;
        }
        if (normalized !== "y" && normalized !== "yes") {
          this.setupView.errorText.content = "Please answer yes or skip.";
          return;
        }
        this.skipEmbedding = false;
        this.embeddingDraft = { provider: "", model: "" };
        this.setupStep = "embedding_provider";
        break;
      }
      case "embedding_provider":
        if (!trimmed) {
          this.setupView.errorText.content = "Embedding provider is required.";
          return;
        }
        this.embeddingDraft = { ...(this.embeddingDraft ?? { model: "" }), provider: trimmed.toLowerCase() };
        this.setupStep = "embedding_model";
        break;
      case "embedding_model":
        if (!trimmed) {
          this.setupView.errorText.content = "Embedding model is required.";
          return;
        }
        this.embeddingDraft = { ...(this.embeddingDraft ?? { provider: "" }), model: trimmed };
        this.setupStep = "embedding_api_key";
        break;
      case "embedding_api_key":
        this.embeddingDraft = {
          ...(this.embeddingDraft ?? { provider: "", model: "" }),
          apiKey: trimmed || undefined,
        };
        this.setupStep = "embedding_base_url";
        break;
      case "embedding_base_url":
        this.embeddingDraft = {
          ...(this.embeddingDraft ?? { provider: "", model: "" }),
          baseUrl: trimmed || undefined,
        };
        this.setupStep = "embedding_vec_dim";
        break;
      case "embedding_vec_dim": {
        const vecDim = trimmed ? Number.parseInt(trimmed, 10) : 1536;
        if (!Number.isInteger(vecDim) || vecDim <= 0) {
          this.setupView.errorText.content = "Vector dimension must be a positive integer.";
          return;
        }
        this.embeddingDraft = {
          ...(this.embeddingDraft ?? { provider: "", model: "" }),
          vecDim,
        };
        await this.saveSetup();
        return;
      }
      case "saving":
        return;
    }

    this.refreshSetupView();
  }

  private async saveSetup(): Promise<void> {
    if (!this.rpcClient || !this.setupView) {
      return;
    }

    this.setupStep = "saving";
    this.refreshSetupView();

    try {
      await this.rpcClient.addModel({
        provider: this.primaryDraft.provider,
        model_name: this.primaryDraft.model,
        api_key: this.primaryDraft.apiKey ?? null,
        base_url: this.primaryDraft.baseUrl ?? null,
        type_model: null,
        vec_dim: null,
      });

      if (!this.skipEmbedding && this.embeddingDraft) {
        await this.rpcClient.addModel({
          provider: this.embeddingDraft.provider,
          model_name: this.embeddingDraft.model,
          api_key: this.embeddingDraft.apiKey ?? null,
          base_url: this.embeddingDraft.baseUrl ?? null,
          type_model: "embeddings",
          vec_dim: this.embeddingDraft.vecDim ?? 1536,
        });
      }

      await saveSettings({
        provider: this.primaryDraft.provider,
        model: this.primaryDraft.model,
        executionMode: this.executionMode,
        ...(this.embeddingDraft && !this.skipEmbedding
          ? {
              embedding: {
                provider: this.embeddingDraft.provider,
                model: this.embeddingDraft.model,
              },
            }
          : {}),
      });

      await this.loadConfigurationState();
      this.renderChatScreen();
      await this.processStartupArgs();
    } catch (error) {
      this.setupStep = this.skipEmbedding ? "embedding_question" : "embedding_vec_dim";
      this.setupView.errorText.content =
        error instanceof Error ? error.message : String(error);
      this.refreshSetupView();
    }
  }

  private getSetupPrompt(): string {
    switch (this.setupStep) {
      case "provider":
        return "Step 1/2: enter the primary model provider.";
      case "model":
        return "Enter the primary model name.";
      case "api_key":
        return "Enter the API key for the primary model, or leave blank.";
      case "base_url":
        return "Enter the base URL for the primary model, or leave blank.";
      case "embedding_question":
        return "Configure an embedding model as well? Answer yes or skip.";
      case "embedding_provider":
        return "Enter the embedding provider.";
      case "embedding_model":
        return "Enter the embedding model name.";
      case "embedding_api_key":
        return "Enter the embedding API key, or leave blank.";
      case "embedding_base_url":
        return "Enter the embedding base URL, or leave blank.";
      case "embedding_vec_dim":
        return "Enter the embedding vector dimension, or leave blank for 1536.";
      case "saving":
        return "Saving model configuration...";
    }
  }

  private getSetupHint(): string {
    switch (this.setupStep) {
      case "provider":
        return "Examples: openai, anthropic, gemini, openrouter, requesty, ollama.";
      case "model":
        return "Examples: gpt-4o-mini, claude-3-7-sonnet, gemini-2.5-pro.";
      case "embedding_question":
        return "Embedding setup is optional, but recommended for target indexing.";
      case "saving":
        return "This writes the same config and settings files used by the legacy CLI.";
      default:
        return "";
    }
  }

  private getSetupPlaceholder(): string {
    switch (this.setupStep) {
      case "provider":
        return "e.g. openai";
      case "model":
        return "e.g. gpt-4o-mini";
      case "api_key":
        return "Enter API key (optional)";
      case "base_url":
        return "Enter base URL (optional)";
      case "embedding_question":
        return "yes or skip";
      case "embedding_provider":
        return "e.g. openai";
      case "embedding_model":
        return "e.g. text-embedding-3-large";
      case "embedding_api_key":
        return "Enter API key (optional)";
      case "embedding_base_url":
        return "Enter base URL (optional)";
      case "embedding_vec_dim":
        return "1536";
      case "saving":
        return "";
    }
  }

  private seedTranscript(): void {
    this.transcriptMessages.length = 0;
    this.renderTranscript();

    if (this.rpcLaunchConfig.detail.trim().length > 0) {
      this.appendMessage(createMessage("system", this.rpcLaunchConfig.detail, "info"));
    }
    this.appendMessage(
      createMessage(
        "assistant",
        "Start by typing a message or use /help to inspect the available commands.",
      ),
    );
  }

  private renderTranscript(): void {
    if (!this.chatView) {
      return;
    }

    clearChildren(this.chatView.transcript);

    this.chatView.transcript.add(createBanner(this.renderer));
    this.chatView.transcript.add(
      new TextRenderable(this.renderer, {
        content: "deadend CLI v0.1.5 · straylabs.ai",
        fg: theme.textSecondary,
      }),
    );

    const metadata = [
      this.args.mode ? `[${this.args.mode}]` : "",
      this.args.target ?? "",
      this.args.codebase ? `codebase=${this.args.codebase}` : "",
      this.args.prompt ? `→ ${this.args.prompt}` : "",
    ].filter(Boolean).join(" ");

    if (metadata) {
      this.chatView.transcript.add(
        new TextRenderable(this.renderer, {
          content: metadata,
          fg: theme.textSecondary,
          wrapMode: "word",
        }),
      );
    }

    for (const message of this.transcriptMessages) {
      this.chatView.transcript.add(this.createMessageRenderable(message));
    }
  }

  private refreshComposer(): void {
    if (!this.chatView) {
      return;
    }

    this.chatView.modeText.content = this.executionMode.toUpperCase();
    this.chatView.modeText.fg =
      this.executionMode === "yolo"
        ? theme.inputModeYolo
        : theme.inputModeSupervisor;
    this.chatView.taskPopupHintText.content = this.showTaskPopup
      ? "[Ctrl+T hide tasks]"
      : "[Ctrl+T tasks]";
    this.chatView.toolOutputText.content = this.expandToolOutput
      ? "[Ctrl+O full tools]"
      : "[Ctrl+O compact tools]";

    this.chatView.runningText.content = this.taskState.isRunning
      ? "● Running (Esc to interrupt)"
      : "";
    this.chatView.runningText.fg = this.taskState.isRunning
      ? theme.accent
      : theme.textSecondary;

    this.chatView.modelText.content = this.currentModel
      ? `${this.currentModel.provider}${this.currentModel.model ? `: ${this.currentModel.model}` : ""}`
      : "No model configured";

    clearChildren(this.chatView.suggestionsBox);
    const suggestions = findCommandSuggestions(this.currentInput);
    if (!this.currentInput.startsWith("/") || suggestions.length === 0) {
      this.chatView.suggestionsBox.visible = false;
      return;
    }

    this.chatView.suggestionsBox.visible = true;
    this.chatView.suggestionsBox.add(
      new TextRenderable(this.renderer, {
        content: "Commands",
        fg: theme.accent,
      }),
    );

    for (const suggestion of suggestions) {
      this.chatView.suggestionsBox.add(
        new TextRenderable(this.renderer, {
          content: `/${suggestion.name.padEnd(14)} ${suggestion.description}`,
          fg: theme.statusInfo,
          wrapMode: "word",
        }),
      );
    }

  }

  private refreshNotifications(): void {
    if (!this.chatView) {
      return;
    }

    clearChildren(this.chatView.notificationBox);
    for (const notification of this.notifications) {
      const row = new BoxRenderable(this.renderer, {
        width: "100%",
        flexDirection: "row",
        gap: 1,
      });

      row.add(
        new TextRenderable(this.renderer, {
          width: 2,
          content: notification.type === "error" ? "✗" : notification.type === "warning" ? "⚠" : "●",
          fg: notification.type === "error"
            ? theme.statusError
            : notification.type === "warning"
              ? theme.statusWarning
              : theme.statusInfo,
        }),
      );
      row.add(
        new TextRenderable(this.renderer, {
          content: notification.message,
          fg: notification.type === "error"
            ? theme.statusError
            : notification.type === "warning"
              ? theme.statusWarning
              : theme.statusInfo,
          wrapMode: "word",
        }),
      );

      this.chatView.notificationBox.add(row);
    }
  }

  private refreshTaskPopup(): void {
    if (!this.chatView) {
      return;
    }

    this.chatView.taskPopup.visible = this.showTaskPopup;
    clearChildren(this.chatView.taskPopupContent);

    if (!this.showTaskPopup) {
      return;
    }

    this.chatView.taskPopupContent.add(
      new TextRenderable(this.renderer, {
        content: " Tasks ",
        fg: theme.textPrimary,
        bg: theme.userBackground,
      }),
    );

    const tasks = this.taskSnapshot?.tasks ?? [];

    if (tasks.length === 0) {
      this.chatView.taskPopupContent.add(
        new TextRenderable(this.renderer, {
          content: " No tasks available yet. ",
          fg: theme.textSecondary,
          bg: theme.userBackground,
          wrapMode: "word",
        }),
      );
      return;
    }

    for (const task of tasks) {
      const prefix = task.is_current ? "▶" : "•";
      const indent = "  ".repeat(Math.max(0, task.depth));
      this.chatView.taskPopupContent.add(
        new TextRenderable(this.renderer, {
          content: ` ${indent}${prefix} ${task.task} [${task.status}] `,
          fg: task.is_current
            ? theme.accent
            : task.status === "completed"
              ? theme.statusSuccess
              : task.status.startsWith("failed")
                ? theme.statusError
                : theme.textPrimary,
          bg: theme.userBackground,
          wrapMode: "word",
        }),
      );
    }
  }

  private async toggleTaskPopup(): Promise<void> {
    if (!this.chatView) {
      return;
    }

    if (this.showTaskPopup) {
      this.showTaskPopup = false;
      this.stopTaskSnapshotPolling();
      this.refreshTaskPopup();
      this.refreshComposer();
      return;
    }

    if (!this.rpcClient || !this.taskState.agentId) {
      this.pushNotification("warning", "No active agent task list available.");
      return;
    }

    const snapshot = await this.rpcClient.getAgentTasks(this.taskState.agentId);
    if (snapshot.status !== "ok") {
      this.pushNotification("warning", snapshot.reason ?? "Unable to load task list.");
      return;
    }

    this.taskSnapshot = snapshot;
    this.showTaskPopup = true;
    this.startTaskSnapshotPolling();
    this.refreshTaskPopup();
    this.refreshComposer();
  }

  private async refreshTaskSnapshot(): Promise<void> {
    if (
      !this.showTaskPopup ||
      !this.rpcClient ||
      !this.taskState.agentId ||
      this.taskSnapshotRefreshInFlight
    ) {
      return;
    }

    this.taskSnapshotRefreshInFlight = true;

    try {
      const snapshot = await this.rpcClient.getAgentTasks(this.taskState.agentId);
      if (snapshot.status !== "ok") {
        return;
      }

      this.taskSnapshot = snapshot;
      this.refreshTaskPopup();
    } finally {
      this.taskSnapshotRefreshInFlight = false;
    }
  }

  private async handleChatSubmit(value: string): Promise<void> {
    const trimmed = value.trim();
    if (!this.chatView || trimmed.length === 0 || this.taskState.isRunning) {
      this.chatView?.input.blur();
      this.chatView?.input.focus();
      return;
    }

    this.currentInput = "";
    this.chatView.input.value = "";
    this.refreshComposer();

    const parsedCommand = parseCommand(trimmed);
    if (parsedCommand) {
      this.appendMessage(createMessage("user", trimmed, "command"));
      await this.handleCommand(parsedCommand.command, parsedCommand.args);
      return;
    }

    this.appendMessage(createMessage("user", trimmed, "text"));

    if (!this.taskState.isTargetEmbedded || !this.taskState.agentId) {
      this.appendMessage(
        createMessage(
          "system",
          "No target set or target not ready. Use /target <url>",
          "error",
        ),
      );
      return;
    }

    await this.runTask(trimmed);
  }

  private async handleCommand(command: string, args: string[]): Promise<void> {
    switch (command) {
      case "help":
        this.appendMessage(createMessage("system", formatHelpText(), "info"));
        return;
      case "clear":
        this.seedTranscript();
        return;
      case "exit":
      case "quit":
      case "q":
        await this.shutdown();
        this.destroyAndExit();
        return;
      case "target":
        await this.handleTargetCommand(args);
        return;
      case "report":
        this.appendMessage(
          createMessage(
            "system",
            "Report generation is not wired yet in the Bun rewrite. Preserve the command surface, then attach the backend report workflow.",
            "info",
          ),
        );
        return;
      case "validation":
      case "val":
        await this.handleValidationCommand(args);
        return;
      default:
        this.appendMessage(
          createMessage(
            "system",
            `Unknown command: /${command}. Type /help to see available commands.`,
            "error",
          ),
        );
    }
  }

  private async handleTargetCommand(args: string[]): Promise<void> {
    if (args.length === 0) {
      if (this.taskState.target) {
        this.appendMessage(createMessage("system", `Current target: ${this.taskState.target}`, "info"));
      } else {
        this.appendMessage(createMessage("system", "No target set. Usage: /target <url|hostname>", "error"));
      }
      return;
    }

    const target = (args[0] ?? "").trim();
    if (!isValidTarget(target)) {
      this.appendMessage(
        createMessage(
          "system",
          "Error: invalid target format. Provide a valid URL or hostname.",
          "error",
        ),
      );
      return;
    }

    this.pushNotification("info", `Checking reachability for ${target}...`);
    const reachable = await checkReachability(target);
    this.notifications = [];
    this.refreshNotifications();

    if (!reachable) {
      this.appendMessage(
        createMessage(
          "system",
          `Error: target ${target} is not reachable. Check the URL and try again.`,
          "error",
        ),
      );
      return;
    }

    await this.prepareTarget(target);
  }

  private async handleValidationCommand(args: string[]): Promise<void> {
    if (!this.rpcClient) {
      this.appendMessage(createMessage("system", "RPC client not available.", "error"));
      return;
    }

    // No args: show current config.
    if (args.length === 0) {
      try {
        const config = await this.rpcClient.getValidationConfig();
        if (config.status !== "ok") {
          this.appendMessage(createMessage("system", config.reason ?? "Failed to read validation config.", "error"));
          return;
        }
        const strategies = (config.strategies ?? []).map((s) => {
          const parts = [s.name];
          if (s.pattern) parts.push(`pattern=${s.pattern}`);
          if (s.validation_format) parts.push(`format=${s.validation_format}`);
          return parts.join(" ");
        });
        const lines = [
          `Preset: ${config.preset ?? "custom"}`,
          `Format: ${config.validation_format ?? "(none)"}`,
          `Type: ${config.validation_type ?? "(none)"}`,
          `Strategies: ${strategies.join(" → ")}`,
          "",
          `Available presets: ${(config.available_presets ?? []).join(", ")}`,
          "Usage: /validation <preset> [--format FORMAT] [--pattern REGEX]",
        ];
        this.appendMessage(createMessage("system", lines.join("\n"), "info"));
      } catch (error) {
        this.appendMessage(createMessage("system", error instanceof Error ? error.message : String(error), "error"));
      }
      return;
    }

    // Parse args: /validation <preset> [--format X] [--pattern X]
    const preset = args[0];
    let format: string | undefined;
    let pattern: string | undefined;
    let validationType: string | undefined;

    for (let i = 1; i < args.length; i += 1) {
      const flag = args[i];
      const value = args[i + 1];
      if ((flag === "--format" || flag === "-f") && value) {
        format = value;
        i += 1;
      } else if ((flag === "--pattern" || flag === "--pat") && value) {
        pattern = value;
        i += 1;
      } else if ((flag === "--type") && value) {
        validationType = value;
        i += 1;
      }
    }

    try {
      const result = await this.rpcClient.setValidationConfig({
        preset,
        ...(format ? { validation_format: format } : {}),
        ...(pattern ? { pattern } : {}),
        ...(validationType ? { validation_type: validationType } : {}),
      });

      if (result.status !== "ok") {
        this.appendMessage(createMessage("system", result.reason ?? "Failed to set validation config.", "error"));
        return;
      }

      const strategyNames = (result.strategies ?? []).map((s) => s.name).join(" → ");
      this.appendMessage(
        createMessage(
          "system",
          `Validation updated: ${preset} [${strategyNames}]${result.validation_format ? ` format=${result.validation_format}` : ""}`,
          "info",
        ),
      );
    } catch (error) {
      this.appendMessage(createMessage("system", error instanceof Error ? error.message : String(error), "error"));
    }
  }

  private async prepareTarget(target: string): Promise<void> {
    if (!this.rpcClient) {
      this.appendMessage(createMessage("system", "RPC client not available.", "error"));
      return;
    }

    if (!this.currentModel?.provider) {
      this.appendMessage(createMessage("system", "No model configured. Complete setup first.", "error"));
      return;
    }

    if (this.taskState.target === target && this.taskState.isTargetEmbedded && this.taskState.agentId) {
      this.appendMessage(createMessage("system", `Target already set and ready: ${target}`, "info"));
      return;
    }

    this.taskState = {
      ...this.taskState,
      isRunning: true,
      phase: "init",
      target,
      isTargetEmbedded: false,
    };
    this.startStatusAnimation(this.chatView!.statusLine, `Initializing ${target}`);

    try {
      const result = await this.rpcClient.instantiateAgent(
        target,
        this.currentModel.provider,
        this.currentModel.model ?? undefined,
        this.resolveWorkspaceRoot(),
        this.args.proxy,
      );
      if (result.status !== "ok" || !result.agent_id) {
        throw new Error(`Failed to instantiate agent: ${result.reason ?? "Unknown error"}`);
      }

      this.taskState.agentId = result.agent_id;
      this.appendMessage(createMessage("system", `Agent created: ${result.agent_id}`, "event_log"));

      const stream = this.rpcClient.embedTarget(result.agent_id, target);
      for await (const event of stream.generator) {
        const message = extractTaskEventMessage(event);
        if (message) {
          this.appendMessage(createMessage("system", message, "event_log"));
        }
      }

      this.taskState = {
        ...this.taskState,
        isRunning: false,
        phase: null,
        target,
        isTargetEmbedded: true,
      };
      this.chatView!.statusLine.content = "";
      this.stopStatusAnimation();
      this.appendMessage(createMessage("system", `Target ready: ${target}`, "info"));
      this.settings = await saveAndReloadSettings({
        ...this.settings,
        defaultTarget: target,
      });
    } catch (error) {
      this.taskState = {
        ...this.taskState,
        isRunning: false,
        phase: "error",
      };
      this.stopStatusAnimation();
      this.chatView!.statusLine.content = "";
      this.appendMessage(
        createMessage(
          "system",
          error instanceof Error ? error.message : String(error),
          "error",
        ),
      );
    }
  }

  private async runTask(task: string): Promise<void> {
    if (!this.rpcClient || !this.taskState.agentId) {
      return;
    }
    const agentId = this.taskState.agentId;
    this.ensureEventSubscription();

    this.taskState = {
      ...this.taskState,
      isRunning: true,
      phase: this.executionMode === "supervisor" ? "supervising" : "recon",
      task,
    };
    this.refreshComposer();
    this.startStatusAnimation(
      this.chatView!.statusLine,
      this.phaseLabel(this.taskState.phase, this.taskState.target),
    );

    const runStream =
      this.executionMode === "supervisor"
        ? this.rpcClient.runAgentSupervisor(agentId, task)
        : this.rpcClient.runAgentRecursive(agentId, task);
    this.runStreamAbort = runStream.abort;
    let runFinished = false;

    try {
      for await (const event of runStream.generator) {
        if (event.phase === "recon" || event.phase === "exploit" || event.phase === "supervising") {
          this.taskState.phase = event.phase;
          this.startStatusAnimation(
            this.chatView!.statusLine,
            this.phaseLabel(this.taskState.phase, this.taskState.target),
          );
        } else if (event.phase === "error") {
          throw new Error(extractTaskEventError(event));
        }
      }

      this.appendMessage(
        createMessage(
          "system",
          `Task completed. Target: ${this.taskState.target ?? "unknown"}`,
          "info",
        ),
      );
      runFinished = true;
    } catch (error) {
      this.appendMessage(
        createMessage(
          "system",
          error instanceof Error ? error.message : String(error),
          "error",
        ),
      );
    } finally {
      if (!runFinished && this.runStreamAbort === runStream.abort) {
        runStream.abort();
      }
      this.runStreamAbort = null;
      this.taskState = {
        ...this.taskState,
        isRunning: false,
        phase: null,
        task: null,
      };
      this.stopStatusAnimation();
      try {
        this.chatView!.statusLine.content = "";
        this.refreshComposer();
      } catch {
        // UI may already be destroyed during shutdown.
      }
    }
  }

  private async cancelRunningTask(skipInterrupt = false): Promise<void> {
    if (!this.rpcClient || !this.taskState.isRunning) {
      return;
    }

    this.runStreamAbort?.();
    this.runStreamAbort = null;

    if (!skipInterrupt) {
      try {
        await this.rpcClient.interrupt("current", "User cancelled");
      } catch {
        // Ignore interrupt failures when canceling.
      }
    }

    this.taskState = {
      ...this.taskState,
      isRunning: false,
      phase: null,
      task: null,
    };
    this.stopStatusAnimation();
    if (this.chatView) {
      this.chatView.statusLine.content = "";
    }
    this.refreshComposer();
    this.appendMessage(createMessage("system", "Task cancelled.", "info"));
  }

  private consumeEvents = async (generator: AsyncGenerator<AgentEvent>): Promise<void> => {
    try {
      for await (const event of generator) {
        if (isHiddenTaskEvent(event)) {
          if (this.showTaskPopup) {
            await this.refreshTaskSnapshot();
          }
          continue;
        }
        this.appendMessage(agentEventToMessage(event));
      }
    } catch {
      // Ignore subscription teardown errors.
    }
  };

  private ensureEventSubscription(): void {
    if (!this.rpcClient || this.eventSubscriptionAbort) {
      return;
    }

    const events = this.rpcClient.subscribeEvents();
    this.eventSubscriptionAbort = events.abort;
    void this.consumeEvents(events.generator).finally(() => {
      if (this.eventSubscriptionAbort === events.abort) {
        this.eventSubscriptionAbort = null;
      }
    });
  }

  private appendMessage(message: Message): void {
    if (!this.chatView) {
      return;
    }

    this.transcriptMessages.push(message);
    this.chatView.transcript.add(this.createMessageRenderable(message));
  }

  private createMessageRenderable(message: Message): BoxRenderable {
    if (message.role === "user") {
      return this.createUserRow(message.content);
    }

    switch (message.type) {
      case "event_tool_call":
        return this.createToolCallRow(message);
      case "event_agent_thought":
        return this.createThoughtRow(message);
      case "event_agent_start":
        return this.createSimpleIndicatorRow("●", message.eventData?.agent_name ?? "agent", theme.routing);
      case "event_agent_end":
        return this.createAgentEndRow(message);
      case "event_agent_error":
        return this.createNestedMessageRow("✗", extractAgentError(message), theme.statusError);
      case "event_agent_routed":
        return this.createNestedMessageRow("○", extractAgentRoute(message), theme.routing);
      case "event_log":
        return this.createSimpleIndicatorRow("⋯", extractLogMessage(message), theme.textSecondary);
      case "command":
        return this.createSimpleIndicatorRow("❯", message.content, theme.statusInfo);
      case "error":
        return this.createNestedMessageRow("⚠", message.content, theme.statusError);
      case "info":
        return this.createNestedMessageRow("●", message.content, theme.statusInfo);
      default:
        return this.createAssistantRow(message);
    }
  }

  private createUserRow(content: string): BoxRenderable {
    const row = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "row",
      marginBottom: 1,
    });

    row.add(
      new TextRenderable(this.renderer, {
        content: "❯",
        fg: theme.userForeground,
        bg: theme.userBackground,
      }),
    );
    row.add(
      new TextRenderable(this.renderer, {
        content: ` ${content} `,
        fg: theme.userForeground,
        bg: theme.userBackground,
        wrapMode: "word",
      }),
    );

    return row;
  }

  private createAssistantRow(message: Message): BoxRenderable {
    const row = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "column",
      marginBottom: 1,
    });

    row.add(this.createIndicatorLine("●", message.role === "assistant" ? " Hint" : "", message.role === "assistant" ? theme.textPrimary : theme.textSecondary));
    row.add(this.createResultLine(message.content, theme.textPrimary));
    return row;
  }

  private createToolCallRow(message: Message): BoxRenderable {
    const event = message.eventData;
    if (!event) {
      return this.createSimpleIndicatorRow("●", message.content, theme.textSecondary);
    }

    if (event.type === "tool_call_start") {
      const data = event.data as { tool_name?: string; args?: string };
      const displayArgs = formatToolCallArgs(data.tool_name, data.args);
      if (!this.expandToolOutput) {
        return this.createSimpleIndicatorRow(
          "●",
          formatCompactToolLine(data.tool_name ?? "tool", displayArgs),
          theme.textPrimary,
        );
      }

      const row = new BoxRenderable(this.renderer, {
        width: "100%",
        flexDirection: "column",
        marginBottom: 1,
      });
      row.add(this.createIndicatorLine("●", ` ${data.tool_name ?? "tool"}`, theme.textPrimary));
      if (displayArgs) {
        row.add(
          this.createResultLine(
            formatToolDisplayText(displayArgs, this.expandToolOutput, 100, 12),
            theme.textSecondary,
          ),
        );
      }
      return row;
    }

    const data = event.data as {
      tool_name?: string;
      success?: boolean;
      duration_ms?: number;
      result?: string;
      error?: string;
    };
    const color = data.success ? theme.statusSuccess : theme.statusError;
    const duration = data.duration_ms ? ` (${Math.round(data.duration_ms)}ms)` : "";
    const resultText = formatToolCallResult(data.tool_name, data.success === true, data.result, data.error);
    if (!this.expandToolOutput) {
      return this.createSimpleIndicatorRow(
        "●",
        formatCompactToolLine(`${data.success ? "✓" : "✗"} ${data.tool_name ?? "tool"}${duration}`, resultText),
        color,
      );
    }

    const row = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "column",
      marginBottom: 1,
    });
    row.add(this.createIndicatorLine("●", ` ${data.success ? "✓" : "✗"} ${data.tool_name ?? "tool"}${duration}`, color));
    if (resultText) {
      row.add(
        this.createResultLine(
          formatToolDisplayText(resultText, this.expandToolOutput, 100, 15),
          data.error ? theme.statusError : theme.textSecondary,
        ),
      );
    }
    return row;
  }

  private createThoughtRow(message: Message): BoxRenderable {
    const data = message.eventData?.data as { thought?: string; summary?: string } | undefined;
    const displayText = data?.thought || data?.summary || message.content;
    const row = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "column",
      marginBottom: 1,
    });
    row.add(this.createIndicatorLine("✻", " Thoughts...", theme.textSecondary));
    row.add(this.createResultLine(displayText, theme.textSecondary));
    return row;
  }

  private createAgentEndRow(message: Message): BoxRenderable {
    const data = message.eventData?.data as { confidence_score?: number; notes?: string } | undefined;
    const confidence = data?.confidence_score ? `${Math.round(data.confidence_score * 100)}%` : "";
    const color = data?.confidence_score && data.confidence_score >= 0.8
      ? theme.statusSuccess
      : theme.statusWarning;
    const summary = `${message.eventData?.agent_name ?? "agent"}${confidence ? ` — ${confidence}` : ""}`;
    const row = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "column",
      marginBottom: 1,
    });
    row.add(this.createIndicatorLine("●", ` ${summary}`, color));
    if (data?.notes) {
      row.add(this.createResultLine(wrapText(data.notes, 80, 5), theme.textPrimary));
    }
    return row;
  }

  private createNestedMessageRow(
    indicator: string,
    content: string,
    color: string,
  ): BoxRenderable {
    const row = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "column",
      marginBottom: 1,
    });
    row.add(this.createIndicatorLine(indicator, " ", color));
    row.add(this.createResultLine(content, color));
    return row;
  }

  private createSimpleIndicatorRow(
    indicator: string,
    content: string,
    color: string,
  ): BoxRenderable {
    const row = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "column",
      marginBottom: 1,
    });
    row.add(this.createIndicatorLine(indicator, ` ${truncate(content, 120)}`, color));
    return row;
  }

  private createIndicatorLine(
    indicator: string,
    content: string,
    color: string,
  ): BoxRenderable {
    const row = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "row",
    });
    row.add(
      new TextRenderable(this.renderer, {
        width: 2,
        content: indicator,
        fg: color,
      }),
    );
    row.add(
      new TextRenderable(this.renderer, {
        content,
        fg: color,
        wrapMode: "word",
      }),
    );
    return row;
  }

  private createResultLine(content: string, color: string): BoxRenderable {
    const row = new BoxRenderable(this.renderer, {
      width: "100%",
      flexDirection: "row",
    });
    row.add(
      new TextRenderable(this.renderer, {
        width: 3,
        content: "⎿ ",
        fg: theme.textSecondary,
      }),
    );
    row.add(
      new TextRenderable(this.renderer, {
        content,
        fg: color,
        wrapMode: "word",
      }),
    );
    return row;
  }

  private pushNotification(
    type: "info" | "warning" | "error",
    message: string,
  ): void {
    this.notifications = [{ type, message }];
    this.refreshNotifications();
  }

  private phaseLabel(phase: TaskPhase, target: string | null): string {
    const labels: Record<Exclude<TaskPhase, null>, string> = {
      init: "Initializing",
      recon: "Reconnaissance",
      exploit: "Exploitation",
      supervising: "Supervising",
      done: "Completed",
      error: "Error",
    };

    if (!phase) {
      return "";
    }

    return `${labels[phase]}${target ? ` — ${target}` : ""}`;
  }

  private startStatusAnimation(target: TextRenderable, text: string): void {
    this.stopStatusAnimation();
    this.currentStatusText = text;
    target.content = this.renderAnimatedStatus(text);
    this.statusFrame = 0;
    this.statusTimer = setInterval(() => {
      this.statusFrame += 1;
      target.content = this.renderAnimatedStatus(this.currentStatusText);
    }, 100);
  }

  private stopStatusAnimation(): void {
    if (this.statusTimer) {
      clearInterval(this.statusTimer);
      this.statusTimer = null;
    }
  }

  private startTaskSnapshotPolling(): void {
    if (this.taskSnapshotTimer || !this.showTaskPopup) {
      return;
    }

    this.taskSnapshotTimer = setInterval(() => {
      void this.refreshTaskSnapshot();
    }, 750);

    void this.refreshTaskSnapshot();
  }

  private stopTaskSnapshotPolling(): void {
    if (this.taskSnapshotTimer) {
      clearInterval(this.taskSnapshotTimer);
      this.taskSnapshotTimer = null;
    }
  }

  private renderAnimatedStatus(text: string): string {
    const triangles = ["◸", "◹", "◿", "◺"];
    const bars = [
      "▰▱▱▱▱▱▱",
      "▰▰▱▱▱▱▱",
      "▰▰▰▱▱▱▱",
      "▰▰▰▰▱▱▱",
      "▰▰▰▰▰▱▱",
      "▰▰▰▰▰▰▱",
      "▰▰▰▰▰▰▰",
      "▱▰▰▰▰▰▰",
      "▱▱▰▰▰▰▰",
      "▱▱▱▰▰▰▰",
      "▱▱▱▱▰▰▰",
      "▱▱▱▱▱▰▰",
      "▱▱▱▱▱▱▰",
      "▱▱▱▱▱▱▱",
    ];

    const triangle = triangles[this.statusFrame % triangles.length];
    const bar = bars[this.statusFrame % bars.length];
    return `${triangle} ${text} ${bar}`;
  }

  private handleGlobalKeyPress = async (key: KeyEvent): Promise<void> => {
    if (isCopyShortcut(key)) {
      key.preventDefault();
      await this.handleCopyShortcut();
      return;
    }

    if (isPasteShortcut(key)) {
      key.preventDefault();
      await this.handlePasteShortcut();
      return;
    }

    if (isCtrlCKey(key)) {
      key.preventDefault();

      if (isPlainCtrlCQuit(key)) {
        await this.shutdown();
        this.destroyAndExit();
      }

      return;
    }

    if (this.currentScreen === "chat") {
      if (isToggleTaskPopupShortcut(key)) {
        key.preventDefault();
        await this.toggleTaskPopup();
        return;
      }

      if (isToggleToolOutputShortcut(key)) {
        key.preventDefault();
        this.expandToolOutput = !this.expandToolOutput;
        this.renderTranscript();
        this.refreshComposer();
        this.pushNotification(
          "info",
          this.expandToolOutput ? "Expanded tool output enabled." : "Compact tool output enabled.",
        );
        return;
      }

      if (isToggleModeShortcut(key)) {
        key.preventDefault();
        this.executionMode = this.executionMode === "yolo" ? "supervisor" : "yolo";
        this.refreshComposer();
        await saveAndReloadSettings({
          ...this.settings,
          executionMode: this.executionMode,
        }).then((settings) => {
          this.settings = settings;
        });
        return;
      }

      if (isInterruptShortcut(key) && this.taskState.isRunning && this.taskState.agentId && this.rpcClient) {
        key.preventDefault();
        try {
          const result = await this.rpcClient.interruptAgent(this.taskState.agentId);
          if (result.status === "interrupted") {
            this.appendMessage(
              createMessage(
                "system",
                "Agent interrupted. You can run a different task now.",
                "info",
              ),
            );
          }
        } catch (error) {
          this.appendMessage(
            createMessage(
              "system",
              error instanceof Error ? error.message : String(error),
              "error",
            ),
          );
        } finally {
          await this.cancelRunningTask(true);
        }
      }
    }
  };

  private async handleCopyShortcut(): Promise<void> {
    const text = this.getClipboardCopyText();
    if (!text) {
      return;
    }

    const copied = this.renderer.copyToClipboardOSC52(text) || await writeClipboardText(text);
    if (this.currentScreen === "chat") {
      this.pushNotification(
        copied ? "info" : "warning",
        copied ? "Copied to clipboard." : "Unable to write to the clipboard.",
      );
    }
  }

  private async handlePasteShortcut(): Promise<void> {
    const text = await readClipboardText();
    if (!text) {
      if (this.currentScreen === "chat") {
        this.pushNotification("warning", "Unable to read clipboard contents.");
      }
      return;
    }

    const editor = this.renderer.currentFocusedEditor;
    if (!editor) {
      return;
    }

    editor.insertText(text);
    this.syncCurrentInputFromFocusedInput();
  }

  private getClipboardCopyText(): string {
    const editor = this.renderer.currentFocusedEditor;
    if (editor?.hasSelection()) {
      return editor.getSelectedText();
    }

    if (editor) {
      return editor.plainText;
    }

    if (this.currentScreen === "chat" && this.chatView) {
      return this.chatView.input.value;
    }

    if (this.currentScreen === "setup" && this.setupView) {
      return this.setupView.input.value;
    }

    return "";
  }

  private syncCurrentInputFromFocusedInput(): void {
    if (this.currentScreen === "chat" && this.chatView) {
      this.currentInput = this.chatView.input.value;
      this.refreshComposer();
      return;
    }

    if (this.currentScreen === "setup" && this.setupView) {
      this.currentInput = this.setupView.input.value;
    }
  }

  private handleTerminalResize = (): void => {
    switch (this.currentScreen) {
      case "chat":
        this.refreshComposer();
        this.refreshNotifications();
        return;
      case "setup":
        this.refreshSetupView();
        return;
      case "init":
        this.renderInitResults(this.componentResults);
        return;
      default:
        return;
    }
  };

  private resolveWorkspaceRoot(): string {
    return resolve(this.args.codebase ?? process.cwd());
  }

  private async processStartupArgs(): Promise<void> {
    if (this.args.target) {
      await this.prepareTarget(this.args.target);
    }

    if (this.args.prompt && this.args.target && this.taskState.isTargetEmbedded) {
      this.appendMessage(createMessage("user", this.args.prompt, "text"));
      await this.runTask(this.args.prompt);
    }
  }

  private clearRoot(): void {
    clearChildren(this.root);
    this.initView = null;
    this.setupView = null;
    this.chatView = null;
  }
}

async function saveAndReloadSettings(settings: CliSettings): Promise<CliSettings> {
  await saveSettings(settings);
  return await loadSettings();
}

function clearChildren(renderable: BoxRenderable | ScrollBoxRenderable): void {
  for (const child of renderable.getChildren()) {
    child.destroyRecursively();
  }
}

function wrapText(str: string, maxLineLen: number, maxLines = 10): string {
  const lines: string[] = [];
  let remaining = str;

  while (remaining.length > 0 && lines.length < maxLines) {
    if (remaining.length <= maxLineLen) {
      lines.push(remaining);
      break;
    }

    let breakPoint = remaining.lastIndexOf(" ", maxLineLen);
    if (breakPoint <= 0) {
      breakPoint = maxLineLen;
    }
    lines.push(remaining.slice(0, breakPoint));
    remaining = remaining.slice(breakPoint).trimStart();
  }

  if (remaining.length > 0 && lines.length >= maxLines) {
    lines[lines.length - 1] += "...";
  }

  return lines.join("\n");
}

function formatToolDisplayText(
  content: string,
  expanded: boolean,
  maxLineLen: number,
  compactMaxLines: number,
): string {
  return expanded
    ? wrapText(content, maxLineLen, Number.MAX_SAFE_INTEGER)
    : wrapText(content, maxLineLen, compactMaxLines);
}

function formatCompactToolLine(label: string, content: string): string {
  const compactContent = content.replace(/\s+/g, " ").trim();
  return compactContent.length > 0 ? `${label} · ${compactContent}` : label;
}

function formatToolCallArgs(toolName: string | undefined, rawArgs: string | undefined): string {
  if (!rawArgs) {
    return "";
  }

  switch (toolName) {
    case "run_python_file":
      return extractLooseField(rawArgs, "code") ?? rawArgs;
    case "sandboxed_shell":
      return extractLooseField(rawArgs, "command") ?? rawArgs;
    case "read_workspace_file":
    case "read_memory_file":
    case "avfs_read":
    case "list_workspace_files":
    case "list_memory_files":
      return extractLooseField(rawArgs, "path") ?? rawArgs;
    case "write_workspace_file":
    case "write_memory_file":
    case "avfs_write":
      return extractLooseField(rawArgs, "content") ?? rawArgs;
    case "pw_send_payload":
      return extractLooseField(rawArgs, "raw_request") ?? rawArgs;
    default:
      return rawArgs;
  }
}

function formatToolCallResult(
  toolName: string | undefined,
  success: boolean,
  rawResult: string | undefined,
  rawError: string | undefined,
): string {
  if (!success) {
    return rawError ?? rawResult ?? "";
  }

  switch (toolName) {
    case "run_python_file":
      return extractPythonToolOutput(rawResult) ?? "";
    case "sandboxed_shell":
      return extractShellToolOutput(rawResult) ?? "";
    case "read_workspace_file":
    case "read_memory_file":
    case "avfs_read":
    case "write_workspace_file":
    case "write_memory_file":
    case "avfs_write":
    case "pw_send_payload":
      return rawResult ?? "";
    case "list_workspace_files":
    case "list_memory_files":
      return extractAvfsListOutput(rawResult) ?? "";
    default:
      return rawResult ?? "";
  }
}

function extractPythonToolOutput(rawResult: string | undefined): string | null {
  if (!rawResult) {
    return null;
  }

  const stdout = extractLooseField(rawResult, "stdout");
  if (stdout) {
    return stdout;
  }

  const stderr = extractLooseField(rawResult, "stderr");
  if (stderr) {
    return stderr;
  }

  return extractLooseField(rawResult, "result") ?? rawResult;
}

function extractShellToolOutput(rawResult: string | undefined): string | null {
  if (!rawResult) {
    return null;
  }

  const parsed = safeParseJson(rawResult);
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    const directOutput = extractStringField(parsed, ["cmd_output", "stdout"]);
    if (directOutput) {
      return directOutput;
    }

    const directError = extractStringField(parsed, ["cmd_error", "stderr"]);
    if (directError) {
      return directError;
    }

    const entries = Object.values(parsed);
    for (const entry of entries) {
      if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
        continue;
      }
      const output = extractStringField(entry, ["cmd_output", "stdout"]);
      if (output) {
        return output;
      }
      const error = extractStringField(entry, ["cmd_error", "stderr"]);
      if (error) {
        return error;
      }
    }
  }

  return extractLooseField(rawResult, "stdout")
    ?? extractLooseField(rawResult, "cmd_output")
    ?? extractLooseField(rawResult, "stderr")
    ?? extractLooseField(rawResult, "cmd_error")
    ?? rawResult;
}

function extractAvfsListOutput(rawResult: string | undefined): string | null {
  if (!rawResult) {
    return null;
  }

  const parsed = safeParseJson(rawResult);
  if (!Array.isArray(parsed)) {
    return rawResult;
  }

  const paths = parsed
    .map((entry) => {
      if (typeof entry === "string") {
        return entry;
      }
      if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
        return null;
      }
      return extractStringField(entry, ["path"]);
    })
    .filter((path): path is string => Boolean(path));

  return paths.length > 0 ? paths.join("\n") : rawResult;
}

function safeParseJson(raw: string): unknown | null {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function extractStringField(value: unknown, keys: string[]): string | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }

  const record = value as Record<string, unknown>;
  for (const key of keys) {
    const fieldValue = record[key];
    if (typeof fieldValue === "string" && fieldValue.length > 0) {
      return fieldValue;
    }
  }

  return null;
}

function extractLooseField(raw: string, key: string): string | null {
  const keyPattern = new RegExp(`['"]${escapeRegExp(key)}['"]\\s*:`);
  const match = keyPattern.exec(raw);
  if (!match) {
    return null;
  }

  let index = match.index + match[0].length;
  while (index < raw.length && /\s/.test(raw[index]!)) {
    index += 1;
  }

  const parsed = parseLooseValue(raw, index);
  return parsed?.trim().length ? parsed.trim() : null;
}

function parseLooseValue(raw: string, start: number): string | null {
  const firstChar = raw[start];
  if (!firstChar) {
    return null;
  }

  if (firstChar === "'" || firstChar === "\"") {
    return decodeQuotedValue(raw, start);
  }

  if (firstChar === "[" || firstChar === "{") {
    return captureBalancedValue(raw, start);
  }

  let end = start;
  while (end < raw.length && raw[end] !== "," && raw[end] !== "}") {
    end += 1;
  }
  return raw.slice(start, end).trim();
}

function decodeQuotedValue(raw: string, start: number): string {
  const quote = raw[start]!;
  let result = "";

  for (let index = start + 1; index < raw.length; index += 1) {
    const char = raw[index]!;
    if (char === "\\") {
      index += 1;
      if (index >= raw.length) {
        break;
      }
      result += decodeEscapeSequence(raw[index]!);
      continue;
    }

    if (char === quote) {
      break;
    }

    result += char;
  }

  return result;
}

function decodeEscapeSequence(char: string): string {
  switch (char) {
    case "n":
      return "\n";
    case "r":
      return "\r";
    case "t":
      return "\t";
    case "\\":
      return "\\";
    case "'":
      return "'";
    case "\"":
      return "\"";
    default:
      return char;
  }
}

function captureBalancedValue(raw: string, start: number): string {
  const stack = [raw[start]!];
  let quote: string | null = null;

  for (let index = start + 1; index < raw.length; index += 1) {
    const char = raw[index]!;
    const prevChar = raw[index - 1];

    if (quote) {
      if (char === quote && prevChar !== "\\") {
        quote = null;
      }
      continue;
    }

    if ((char === "'" || char === "\"") && prevChar !== "\\") {
      quote = char;
      continue;
    }

    if (char === "{" || char === "[") {
      stack.push(char);
      continue;
    }

    if (char === "}" || char === "]") {
      const current = stack[stack.length - 1];
      if ((char === "}" && current === "{") || (char === "]" && current === "[")) {
        stack.pop();
        if (stack.length === 0) {
          return raw.slice(start, index + 1);
        }
      }
    }
  }

  return raw.slice(start).trim();
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) {
    return str;
  }

  return `${str.slice(0, maxLen - 3)}...`;
}

function isValidTarget(target: string): boolean {
  try {
    const url = new URL(target.startsWith("http") ? target : `https://${target}`);
    return url.hostname.length > 0;
  } catch {
    return /^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/.test(target);
  }
}

async function checkReachability(target: string): Promise<boolean> {
  const candidates = target.startsWith("http://") || target.startsWith("https://")
    ? [target]
    : [`https://${target}`, `http://${target}`];

  for (const candidate of candidates) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5_000);

    try {
      const response = await fetch(candidate, {
        method: "HEAD",
        signal: controller.signal,
        redirect: "follow",
      });
      clearTimeout(timeoutId);
      if (response.status < 500) {
        return true;
      }
    } catch {
      clearTimeout(timeoutId);
    }
  }

  return false;
}

function extractTaskEventMessage(event: TaskEvent): string | null {
  if (typeof event.data === "object" && event.data && "message" in event.data) {
    const message = (event.data as { message?: unknown }).message;
    return typeof message === "string" ? message : null;
  }

  return null;
}

function extractTaskEventError(event: TaskEvent): string {
  if (typeof event.data === "object" && event.data) {
    const data = event.data as { message?: unknown; error_type?: unknown };
    const message = typeof data.message === "string" ? data.message : "Unknown error";
    const errorType = typeof data.error_type === "string" ? data.error_type : "Error";
    return `${errorType}: ${message}`;
  }

  return event.reason ?? "Unknown error";
}

function extractAgentError(message: Message): string {
  const data = message.eventData?.data as { error_type?: string; error_message?: string } | undefined;
  return `${data?.error_type ?? "Error"}: ${data?.error_message ?? message.content}`;
}

function extractAgentRoute(message: Message): string {
  const data = message.eventData?.data as { selected_agent?: string; reasoning?: string } | undefined;
  return `Routing to ${data?.selected_agent ?? "agent"}${data?.reasoning ? `: ${data.reasoning}` : ""}`;
}

function extractLogMessage(message: Message): string {
  const data = message.eventData?.data as { message?: string } | undefined;
  return data?.message ?? message.content;
}

function isHiddenTaskEvent(event: AgentEvent): boolean {
  return event.type === "task_created"
    || event.type === "task_expanded"
    || event.type === "task_status_changed"
    || event.type === "confidence_update"
    || event.type === "validation_result";
}

function pickRandomInitStatus(): string {
  const index = Math.floor(Math.random() * INIT_STATUS_PHRASES.length);
  return INIT_STATUS_PHRASES[index] ?? "Starting...";
}
