# deadend

Bun-based OpenTUI rewrite of the deadend CLI.

## Install

```bash
bun install
```

## Run

```bash
bun run index.ts
```

## Options

```bash
bun run index.ts --help
```

Supported flags:

- `--mode supervisor|yolo`
- `--dev`
- `--debug`
- `--codebase <dir>`
- `--target <value>`
- `--prompt <value>`

## Notes

- It reads the same config and settings files under `~/.deadend` (persistent state) and caches runtime data under `~/.cache/deadend`.
- It preserves the terminal transcript model from the earlier CLI while using OpenTUI instead of Ink.
- `--dev` and `--debug` launch the Python JSON-RPC server with `uv` from the repo's `deadend_cli` package.
- Keyboard handling notes live in `docs/deadend-cli-keyboard.md`.
