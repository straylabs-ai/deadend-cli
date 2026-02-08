#!/bin/bash
# Wrapper script to set LD_LIBRARY_PATH for shared libraries
# This script should be placed next to the 'deadend' binary after building
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Include both lib and numpy/libs directories for OpenBLAS and other shared libraries
export LD_LIBRARY_PATH="${SCRIPT_DIR}/lib:${SCRIPT_DIR}/lib/numpy/libs${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

# Ensure Playwright driver has execute permissions
if [ -f "${SCRIPT_DIR}/lib/playwright/driver/node" ]; then
    chmod +x "${SCRIPT_DIR}/lib/playwright/driver/node" 2>/dev/null
fi

exec "${SCRIPT_DIR}/deadend" "$@"
