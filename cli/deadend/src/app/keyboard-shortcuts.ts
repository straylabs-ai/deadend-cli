import type { KeyEvent } from "@opentui/core";

export function isCtrlCKey(key: KeyEvent): boolean {
  return key.ctrl && normalizeKeyName(key.name) === "c";
}

export function isPlainCtrlCQuit(key: KeyEvent): boolean {
  return isCtrlCKey(key) && key.raw === "\u0003" && !key.shift;
}

export function isCopyShortcut(key: KeyEvent): boolean {
  return isCtrlCKey(key) && key.shift;
}

export function isPasteShortcut(key: KeyEvent): boolean {
  return key.ctrl && key.shift && normalizeKeyName(key.name) === "v";
}

export function isCopyShortcutSequence(sequence: string): boolean {
  return COPY_SHORTCUT_SEQUENCES.has(sequence);
}

export function isPasteShortcutSequence(sequence: string): boolean {
  return PASTE_SHORTCUT_SEQUENCES.has(sequence);
}

export function isToggleModeShortcut(key: KeyEvent): boolean {
  return key.shift && key.name === "tab";
}

export function isInterruptShortcut(key: KeyEvent): boolean {
  return key.name === "escape";
}

export function isToggleToolOutputShortcut(key: KeyEvent): boolean {
  return key.ctrl && normalizeKeyName(key.name) === "o";
}

export function isToggleTaskPopupShortcut(key: KeyEvent): boolean {
  return key.ctrl && normalizeKeyName(key.name) === "t";
}

export function formatKeyEventDebug(key: KeyEvent): string {
  return [
    `name=${key.name}`,
    `sequence=${JSON.stringify(key.sequence)}`,
    `raw=${JSON.stringify(key.raw)}`,
    `ctrl=${key.ctrl}`,
    `shift=${key.shift}`,
    `meta=${key.meta}`,
    `option=${key.option}`,
  ].join(" ");
}

export async function readClipboardText(): Promise<string> {
  const backend = resolveClipboardBackend();
  if (!backend?.readCmd) {
    return "";
  }

  try {
    const proc = Bun.spawn({
      cmd: backend.readCmd,
      stdout: "pipe",
      stderr: "ignore",
    });
    const exitCode = await proc.exited;
    if (exitCode !== 0) {
      return "";
    }

    return await new Response(proc.stdout).text();
  } catch {
    return "";
  }
}

export async function writeClipboardText(text: string): Promise<boolean> {
  const backend = resolveClipboardBackend();
  if (!backend?.writeCmd) {
    return false;
  }

  try {
    const proc = Bun.spawn({
      cmd: backend.writeCmd,
      stdin: "pipe",
      stdout: "ignore",
      stderr: "ignore",
    });

    if (!proc.stdin) {
      return false;
    }

    proc.stdin.write(text);
    proc.stdin.end();

    const exitCode = await proc.exited;
    return exitCode === 0;
  } catch {
    return false;
  }
}

interface ClipboardBackend {
  name: string;
  readCmd?: string[];
  writeCmd?: string[];
}

let cachedClipboardBackend: ClipboardBackend | null | undefined;

function resolveClipboardBackend(): ClipboardBackend | null {
  if (cachedClipboardBackend !== undefined) {
    return cachedClipboardBackend;
  }

  switch (process.platform) {
    case "darwin":
      cachedClipboardBackend = {
        name: "pbcopy/pbpaste",
        readCmd: ["pbpaste"],
        writeCmd: ["pbcopy"],
      };
      return cachedClipboardBackend;
    case "win32":
      cachedClipboardBackend = {
        name: "powershell",
        readCmd: ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
        writeCmd: ["powershell.exe", "-NoProfile", "-Command", "Set-Clipboard"],
      };
      return cachedClipboardBackend;
    default:
      if (process.env["WAYLAND_DISPLAY"] && commandExists("wl-copy") && commandExists("wl-paste")) {
        cachedClipboardBackend = {
          name: "wl-copy/wl-paste",
          readCmd: ["wl-paste", "--no-newline"],
          writeCmd: ["wl-copy"],
        };
        return cachedClipboardBackend;
      }

      if (commandExists("xclip")) {
        cachedClipboardBackend = {
          name: "xclip",
          readCmd: ["xclip", "-selection", "clipboard", "-out"],
          writeCmd: ["xclip", "-selection", "clipboard"],
        };
        return cachedClipboardBackend;
      }

      if (commandExists("xsel")) {
        cachedClipboardBackend = {
          name: "xsel",
          readCmd: ["xsel", "--clipboard", "--output"],
          writeCmd: ["xsel", "--clipboard", "--input"],
        };
        return cachedClipboardBackend;
      }

      cachedClipboardBackend = null;
      return cachedClipboardBackend;
  }
}

function commandExists(command: string): boolean {
  try {
    const proc = Bun.spawnSync({
      cmd: ["sh", "-lc", `command -v ${shellEscape(command)}`],
      stdout: "ignore",
      stderr: "ignore",
    });
    return proc.exitCode === 0;
  } catch {
    return false;
  }
}

function shellEscape(value: string): string {
  return `'${value.replaceAll("'", `'\\''`)}'`;
}

function normalizeKeyName(name: string): string {
  return name.length === 1 ? name.toLowerCase() : name;
}

const COPY_SHORTCUT_SEQUENCES = new Set([
  "\u001b[99;6u",
  "\u001b[67;6u",
  "\u001b[67;5u",
  "\u001b[27;6;99~",
  "\u001b[27;6;67~",
  "\u001b[27;5;67~",
]);

const PASTE_SHORTCUT_SEQUENCES = new Set([
  "\u001b[118;6u",
  "\u001b[86;6u",
  "\u001b[86;5u",
  "\u001b[27;6;118~",
  "\u001b[27;6;86~",
  "\u001b[27;5;86~",
]);
