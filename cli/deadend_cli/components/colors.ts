/**
 * @file colors.ts
 * @description Centralized color theme for the DeadEnd CLI.
 *
 * All UI color values live here so components stay consistent
 * and theme changes only require touching one file.
 */

export const colors = {
  // Primary accent used for branding / highlights
  accent: "#FF5533",

  // Text hierarchy
  text: {
    primary: "white",
    secondary: "gray",
    dimmed: "gray", // used with dimColor prop
  },

  // Status indicators (dots, icons)
  status: {
    success: "#64CF64",
    warning: "#FEE19C",
    error: "#F1689F",
    info: "#8C8CF9",
  },

  // Tool-call dot states
  dot: {
    pending: "gray",     // blinking - awaiting approval / queued
    running: "gray",     // blinking - currently executing
    completed: "#64CF64", // solid green
    error: "#F1689F",     // solid red
  },

  // Message-specific
  message: {
    user: "#2845d6",
    assistant: "white",
    thinking: "gray",
    command: "cyan",
    routing: "#DAA520",
    agentStart: "#DAA520",
    agentEnd: "#64CF64",
  },

  // Task phase colors
  phase: {
    init: "gray",
    recon: "#1a2ca3",
    exploit: "red",
    supervising: "#DAA520",
    done: "#64CF64",
    error: "#F1689F",
  },

  // Input area
  input: {
    prompt: "#FF5533",
    border: "gray",
    modeYolo: "red",
    modeSupervisor: "#DAA520",
  },

  // Approval
  approval: {
    header: "#FF5533",
    border: "gray",
    approve: "#64CF64",
    deny: "#F1689F",
  },

  // Log levels
  log: {
    debug: "gray",
    info: "white",
    warning: "#FEE19C",
    error: "#F1689F",
  },
} as const;
