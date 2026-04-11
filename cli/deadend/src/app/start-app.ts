import { createCliRenderer } from "@opentui/core";
import { formatHelp, parseArgs } from "../cli/args.ts";
import { DeadendApp } from "./deadend-app.ts";
import { resolveRpcLaunchConfig } from "../runtime/server-launcher.ts";

export async function startApp(): Promise<void> {
  const args = parseCliArgs();
  if (args.help) {
    console.log(formatHelp());
    return;
  }

  const rpcLaunchConfig = await resolveRpcLaunchConfig(args);
  const renderer = await createCliRenderer({
    exitOnCtrlC: false,
    screenMode: "alternate-screen",
  });

  const app = new DeadendApp(renderer, args, rpcLaunchConfig);
  registerShutdown(app);

  await app.start();
}

function parseCliArgs() {
  try {
    return parseArgs(Bun.argv.slice(2));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(message);
    console.error("");
    console.error(formatHelp());
    process.exit(1);
  }
}

function registerShutdown(app: DeadendApp): void {
  const shutdown = () => {
    void app.shutdown().finally(() => {
      app.destroyAndExit();
    });
  };

  process.once("SIGINT", shutdown);
  process.once("SIGTERM", shutdown);
}
