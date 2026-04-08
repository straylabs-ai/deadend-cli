#!/bin/bash
# Wrapper script to set LD_LIBRARY_PATH for shared libraries
# This script should be placed next to the 'deadend' binary after building
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Include both lib and numpy/libs directories for OpenBLAS and other shared libraries
export LD_LIBRARY_PATH="${SCRIPT_DIR}/lib:${SCRIPT_DIR}/lib/numpy/libs${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

# Set PLAYWRIGHT_BROWSERS_PATH so Playwright knows where to find browsers
# This must point to the .local-browsers directory
export PLAYWRIGHT_BROWSERS_PATH="${SCRIPT_DIR}/lib/playwright/driver/package/.local-browsers"

# Ensure Playwright driver has execute permissions
if [ -f "${SCRIPT_DIR}/lib/playwright/driver/node" ]; then
    chmod +x "${SCRIPT_DIR}/lib/playwright/driver/node" 2>/dev/null
fi

# On macOS, strip any invalid signature and re-sign ad-hoc, then clear quarantine
if [ "$(uname)" = "Darwin" ] && [ -f "${SCRIPT_DIR}/deadend" ]; then
    # Remove existing (possibly broken) signature; ignore errors if not signed
    codesign --remove-signature "${SCRIPT_DIR}/deadend" 2>/dev/null || true
    # Ad-hoc sign (no certificate)
    codesign -s - --force --deep "${SCRIPT_DIR}/deadend" 2>/dev/null || true
    # Clear quarantine attributes if any
    xattr -c "${SCRIPT_DIR}/deadend" 2>/dev/null || true
fi

exec "${SCRIPT_DIR}/deadend" "$@"
