/**
 * @file mode.ts
 * @description Command handler for the /mode command.
 *
 * This handler manages two types of modes:
 * 1. Execution mode: Controls how the agent runs (yolo vs supervisor)
 *    - yolo: Autonomous execution without human approval
 *    - supervisor: Step-by-step execution with approval workflow
 *
 * 2. Assessment mode: Controls the level of knowledge available (legacy)
 *    - blackbox: External testing only, no internal knowledge
 *    - greybox: Partial knowledge with docs/OpenAPI specs
 *    - whitebox: Full knowledge with codebase access
 *
 * The command returns special tokens that the Chat component interprets
 * to switch execution modes or display confirmation messages.
 */

/** Execution modes for agent behavior */
type ExecutionMode = "yolo" | "supervisor";

/** Assessment modes for knowledge level (legacy) */
type AssessmentMode = "greybox" | "blackbox" | "whitebox";

/** Token returned to toggle between yolo and supervisor modes */
export const TOGGLE_MODE = "TOGGLE_MODE";

/** Token returned to set mode to yolo */
export const SET_MODE_YOLO = "SET_MODE_YOLO";

/** Token returned to set mode to supervisor */
export const SET_MODE_SUPERVISOR = "SET_MODE_SUPERVISOR";

/**
 * Handle the /mode command.
 *
 * Usage:
 * - /mode           - Toggle between yolo and supervisor
 * - /mode yolo      - Set to autonomous (yolo) mode
 * - /mode supervisor - Set to supervised mode
 * - /mode plan      - Alias for supervisor mode
 * - /mode blackbox  - Set assessment mode (legacy)
 * - /mode greybox   - Set assessment mode with docs (legacy)
 * - /mode whitebox  - Set assessment mode with codebase (legacy)
 *
 * @param args - Command arguments
 * @returns Special token for Chat component or status message
 */
export async function handleMode(args: string[]): Promise<string> {
  // No args: toggle mode
  if (args.length === 0) {
    return TOGGLE_MODE;
  }

  const modeArg = args[0].toLowerCase();

  // Handle execution mode settings
  if (modeArg === "yolo") {
    return SET_MODE_YOLO;
  }

  if (modeArg === "supervisor" || modeArg === "plan") {
    return SET_MODE_SUPERVISOR;
  }

  // Handle legacy assessment modes
  if (["greybox", "blackbox", "whitebox"].includes(modeArg)) {
    return handleAssessmentMode(modeArg as AssessmentMode, args.slice(1));
  }

  // Unknown mode - show help
  return (
    `Usage: /mode [yolo|supervisor|blackbox|greybox|whitebox]\n\n` +
    `Execution Modes:\n` +
    `  yolo       - Autonomous execution without approval (Shift+Tab to toggle)\n` +
    `  supervisor - Step-by-step execution with approval workflow\n\n` +
    `Assessment Modes (legacy):\n` +
    `  blackbox   - No internal knowledge, external testing only\n` +
    `  greybox    - Partial knowledge, requires docs or OpenAPI spec\n` +
    `  whitebox   - Full knowledge, requires codebase path\n\n` +
    `Examples:\n` +
    `  /mode             - Toggle between yolo and supervisor\n` +
    `  /mode yolo        - Set to autonomous mode\n` +
    `  /mode supervisor  - Set to supervised mode`
  );
}

/**
 * Handle legacy assessment mode settings.
 *
 * @param mode - The assessment mode to set
 * @param args - Additional arguments (--codebase, --docs, --openapi)
 * @returns Status message about the mode change
 */
function handleAssessmentMode(mode: AssessmentMode, args: string[]): string {
  // Parse additional arguments
  const options: { codebase?: string; docs?: string; openapi?: string } = {};

  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--codebase" && args[i + 1]) {
      options.codebase = args[i + 1];
      i++;
    } else if ((args[i] === "--docs" || args[i] === "--openapi") && args[i + 1]) {
      options.docs = args[i + 1];
      options.openapi = args[i + 1];
      i++;
    }
  }

  // Validate mode requirements
  if (mode === "whitebox") {
    if (!options.codebase) {
      return (
        `Error: whitebox mode requires --codebase <path>\n` +
        `Example: /mode whitebox --codebase ./src`
      );
    }
    return (
      `Assessment mode set to: ${mode}\n` +
      `Codebase: ${options.codebase}\n\n` +
      `[Note: Whitebox mode enables source code analysis.]`
    );
  }

  if (mode === "greybox") {
    if (!options.docs && !options.openapi) {
      return (
        `Error: greybox mode requires --docs or --openapi <path>\n` +
        `Example: /mode greybox --docs ./api-docs.json\n` +
        `         /mode greybox --openapi ./openapi.yaml`
      );
    }
    return (
      `Assessment mode set to: ${mode}\n` +
      `Documentation: ${options.docs || options.openapi}\n\n` +
      `[Note: Greybox mode enables API documentation analysis.]`
    );
  }

  // blackbox mode
  return (
    `Assessment mode set to: ${mode}\n\n` +
    `[Note: Blackbox mode uses external testing only.]`
  );
}
