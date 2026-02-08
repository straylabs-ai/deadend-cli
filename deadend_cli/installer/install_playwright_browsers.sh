#!/bin/bash
# Install Playwright browsers to the build directory
# Usage: install_playwright_browsers.sh <build_dir>

set -e

if [ -z "$1" ]; then
    echo "Error: Build directory not provided"
    echo "Usage: $0 <build_dir>"
    exit 1
fi

BUILD_DIR="$1"

# The browser path should match what's in the built package
BROWSER_BASE_PATH="${BUILD_DIR}/lib/playwright/driver/package"
BROWSER_PATH="${BROWSER_BASE_PATH}/.local-browsers"
mkdir -p "$BROWSER_PATH"

# Detect if we're on macOS (which requires --break-system-packages)
PIP_FLAGS=""
IS_MACOS=false
if [[ "$(uname -s)" == "Darwin" ]]; then
    PIP_FLAGS="--break-system-packages"
    IS_MACOS=true
fi

# Install playwright to get the driver and browser installation script
# Skip pip upgrade on macOS as it's managed by Homebrew and can't be upgraded via pip
if [ "$IS_MACOS" = false ]; then
    python3 -m pip install --upgrade pip $PIP_FLAGS
fi
python3 -m pip install playwright $PIP_FLAGS

# Set PLAYWRIGHT_BROWSERS_PATH to install directly to target location
export PLAYWRIGHT_BROWSERS_PATH="$BROWSER_PATH"

# Install chromium_headless_shell (the headless browser Playwright uses)
echo "Installing chromium_headless_shell to $BROWSER_PATH..."
python3 -m playwright install chromium_headless_shell

# Target version - must be exactly 1208
TARGET_VERSION="1208"
TARGET_DIR_NAME="chromium_headless_shell-$TARGET_VERSION"
TARGET_DIR="$BROWSER_PATH/$TARGET_DIR_NAME"

# Verify installation
if [ -d "$BROWSER_PATH" ]; then
    echo "Browser installation successful"
    echo "Browser directory contents:"
    ls -la "$BROWSER_PATH"
    
    # Check for chromium_headless_shell directory (any version)
    HEADLESS_SHELL_DIR=$(find "$BROWSER_PATH" -maxdepth 1 -type d -name "chromium_headless_shell-*" | head -n 1)
    
    # Also check for chromium directory as fallback
    if [ -z "$HEADLESS_SHELL_DIR" ]; then
        CHROMIUM_DIR=$(find "$BROWSER_PATH" -maxdepth 1 -type d -name "chromium-*" | head -n 1)
        if [ -n "$CHROMIUM_DIR" ]; then
            echo "Found chromium directory, will use it to create $TARGET_DIR_NAME"
            HEADLESS_SHELL_DIR="$CHROMIUM_DIR"
        fi
    fi
    
    if [ -n "$HEADLESS_SHELL_DIR" ]; then
        HEADLESS_SHELL_NAME=$(basename "$HEADLESS_SHELL_DIR")
        echo "Found browser directory: $HEADLESS_SHELL_NAME"
        
        # Rename or copy to the exact version name (chromium_headless_shell-1208)
        if [ "$HEADLESS_SHELL_NAME" != "$TARGET_DIR_NAME" ]; then
            echo "Renaming $HEADLESS_SHELL_NAME to $TARGET_DIR_NAME (version 1208)"
            if [ -d "$TARGET_DIR" ]; then
                echo "Target directory already exists, removing it first..."
                rm -rf "$TARGET_DIR"
            fi
            mv "$HEADLESS_SHELL_DIR" "$TARGET_DIR"
            echo "✓ Successfully renamed to $TARGET_DIR_NAME"
        else
            echo "✓ Directory already has correct name: $TARGET_DIR_NAME"
        fi
        
        # Verify the target directory exists
        if [ -d "$TARGET_DIR" ]; then
            echo "Browser executable check:"
            find "$TARGET_DIR" -type f -name "chrome-headless-shell" -o -name "chrome-headless-shell*" | head -5 || echo "Checking for browser executables..."
            find "$TARGET_DIR" -type d -name "*chrome*" | head -5 || echo "Checking for browser directories..."
            
            # Fix permissions on browser executables
            echo "Fixing permissions on browser executables..."
            find "$TARGET_DIR" -type f \( -name "chrome-headless-shell" -o -name "chrome-headless-shell*" -o -name "chrome*" -o -name "chromium*" \) -exec chmod +x {} \; 2>/dev/null || true
            find "$TARGET_DIR" -type d -name "*chrome*" -exec find {} -type f -exec chmod +x {} \; \; 2>/dev/null || true
        else
            echo "Error: Target directory $TARGET_DIR_NAME was not created"
            exit 1
        fi
    else
        echo "Warning: No chromium_headless_shell or chromium directory found"
        echo "Trying to find any chromium-related directories..."
        find "$BROWSER_PATH" -maxdepth 1 -type d | head -10
        
        # Try installing regular chromium as fallback
        echo "Attempting to install regular chromium as fallback..."
        python3 -m playwright install chromium
        
        # Check if chromium was installed
        CHROMIUM_DIR=$(find "$BROWSER_PATH" -maxdepth 1 -type d -name "chromium-*" | head -n 1)
        if [ -n "$CHROMIUM_DIR" ]; then
            echo "Found chromium directory, creating $TARGET_DIR_NAME from it"
            if [ -d "$TARGET_DIR" ]; then
                rm -rf "$TARGET_DIR"
            fi
            cp -r "$CHROMIUM_DIR" "$TARGET_DIR"
            echo "✓ Created $TARGET_DIR_NAME from chromium installation"
            # Fix permissions
            find "$TARGET_DIR" -type f \( -name "chrome*" -o -name "chromium*" \) -exec chmod +x {} \; 2>/dev/null || true
        else
            echo "Error: Could not find chromium installation after fallback attempt"
            exit 1
        fi
    fi
    
    # Final verification that the target directory exists with the correct name
    if [ ! -d "$TARGET_DIR" ]; then
        echo "Error: Final verification failed - $TARGET_DIR_NAME does not exist"
        exit 1
    fi
    echo "✓ Final verification: $TARGET_DIR_NAME exists and is ready"
else
    echo "Error: Browser installation failed - directory not created"
    exit 1
fi
