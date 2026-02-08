#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
INSTALL_DIR="${INSTALL_DIR:-$HOME/.cache/server}"
VERSION="${VERSION:-latest}"
REPO="${REPO:-xoxruns/deadend-cli}"

# Detect OS and architecture
detect_platform() {
    local os=""
    local arch=""
    
    case "$(uname -s)" in
        Linux*)
            os="linux"
            ;;
        Darwin*)
            os="macos"
            ;;
        *)
            echo -e "${RED}Error: Unsupported operating system: $(uname -s)${NC}"
            exit 1
            ;;
    esac
    
    case "$(uname -m)" in
        x86_64)
            arch="x86_64"
            ;;
        arm64|aarch64)
            arch="aarch64"
            ;;
        *)
            echo -e "${RED}Error: Unsupported architecture: $(uname -m)${NC}"
            exit 1
            ;;
    esac
    
    if [ "$os" == "linux" ]; then
        PLATFORM="linux"
        TARGET="x86_64-unknown-linux-gnu"
    else
        PLATFORM="macos"
        # Only support ARM64 for macOS
        if [ "$arch" != "aarch64" ]; then
            echo -e "${YELLOW}Warning: x86_64 macOS is not supported. Using ARM64 build.${NC}"
        fi
        TARGET="aarch64-apple-darwin"
    fi
    
    PACKAGE_NAME="deadend-${PLATFORM}-${TARGET}"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --version)
            VERSION="$2"
            shift 2
            ;;
        --install-dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --repo)
            REPO="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --version VERSION     Version to install (default: latest)"
            echo "  --install-dir DIR     Installation directory (default: ~/.cache/server)"
            echo "  --repo REPO           GitHub repository (default: xoxruns/deadend-cli)"
            echo "  -h, --help            Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done


# Get the latest release version
get_latest_version() {
    if [ "$VERSION" == "latest" ]; then
        VERSION=$(curl -s "https://api.github.com/repos/${REPO}/releases/latest" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')
        if [ -z "$VERSION" ]; then
            echo -e "${RED}Error: Could not determine latest version${NC}"
            exit 1
        fi
    fi
}

# Install
install() {
    echo -e "${GREEN}Installing Deadend CLI ${VERSION} for ${PLATFORM}...${NC}"
    
    # Create temporary directory
    TEMP_DIR=$(mktemp -d)
    trap "rm -rf $TEMP_DIR" EXIT
    
    # Determine CLI package name
    if [ "$PLATFORM" == "linux" ]; then
        CLI_PACKAGE_NAME="deadend-cli-linux-x86_64"
    else
        CLI_PACKAGE_NAME="deadend-cli-macos-aarch64"
    fi
    
    # Download the server package
    SERVER_DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${VERSION}/${PACKAGE_NAME}.tar.gz"
    echo -e "${YELLOW}Downloading server package...${NC}"
    echo ""
    
    if ! curl -fSL --progress-bar -o "${TEMP_DIR}/${PACKAGE_NAME}.tar.gz" "$SERVER_DOWNLOAD_URL"; then
        echo -e "${RED}Error: Failed to download server package${NC}"
        exit 1
    fi
    echo ""
    
    # Download the CLI binary
    CLI_DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${VERSION}/${CLI_PACKAGE_NAME}.tar.gz"
    echo -e "${YELLOW}Downloading CLI binary...${NC}"
    echo ""
    
    if ! curl -fSL --progress-bar -o "${TEMP_DIR}/${CLI_PACKAGE_NAME}.tar.gz" "$CLI_DOWNLOAD_URL"; then
        echo -e "${RED}Error: Failed to download CLI package${NC}"
        exit 1
    fi
    echo ""
    echo ""
    
    # Verify checksums if available
    verify_checksum() {
        local file="$1"
        local checksum_url="https://github.com/${REPO}/releases/download/${VERSION}/${file}.sha256"
        if curl -fsSL --progress-bar -o "${TEMP_DIR}/${file}.sha256" "$checksum_url" 2>/dev/null; then
            cd "$TEMP_DIR"
            # Fix checksum file if it contains a path - replace with just the filename
            if grep -q "/" "${file}.sha256" 2>/dev/null; then
                hash=$(awk '{print $1}' "${file}.sha256" | head -1)
                echo "${hash}  ${file}" > "${file}.sha256"
            fi
            if command -v sha256sum >/dev/null 2>&1; then
                sha256sum -c "${file}.sha256" || return 1
            elif command -v shasum >/dev/null 2>&1; then
                shasum -a 256 -c "${file}.sha256" || return 1
            fi
            return 0
        fi
        return 2
    }
    
    echo -e "${YELLOW}Verifying checksums...${NC}"
    verify_checksum "${PACKAGE_NAME}.tar.gz"
    case $? in
        0) echo -e "${GREEN}Server package checksum verified${NC}" ;;
        1) echo -e "${RED}Error: Server package checksum verification failed${NC}"; exit 1 ;;
        2) echo -e "${YELLOW}Warning: Server package checksum file not found, skipping verification${NC}" ;;
    esac
    
    verify_checksum "${CLI_PACKAGE_NAME}.tar.gz"
    case $? in
        0) echo -e "${GREEN}CLI package checksum verified${NC}" ;;
        1) echo -e "${RED}Error: CLI package checksum verification failed${NC}"; exit 1 ;;
        2) echo -e "${YELLOW}Warning: CLI package checksum file not found, skipping verification${NC}" ;;
    esac
    
    # Extract packages
    echo -e "${YELLOW}Extracting packages...${NC}"
    cd "$TEMP_DIR"
    tar -xzf "${PACKAGE_NAME}.tar.gz"
    tar -xzf "${CLI_PACKAGE_NAME}.tar.gz"
    
    # Install server package
    echo -e "${YELLOW}Installing server to ${INSTALL_DIR}...${NC}"
    mkdir -p "$INSTALL_DIR"
    
    # Copy entire server package contents (includes deadend binary, deadend.sh, lib/, etc.)
    if [ -d "${PACKAGE_NAME}" ]; then
        cp -r "${PACKAGE_NAME}"/* "${INSTALL_DIR}/"
        chmod +x "${INSTALL_DIR}/deadend" 2>/dev/null || true
        chmod +x "${INSTALL_DIR}/deadend.sh" 2>/dev/null || true
        
        # Fix permissions for Playwright driver
        if [ -f "${INSTALL_DIR}/lib/playwright/driver/node" ]; then
            chmod +x "${INSTALL_DIR}/lib/playwright/driver/node"
        fi
        
        echo -e "${GREEN}Server installed to ${INSTALL_DIR}${NC}"
    else
        echo -e "${RED}Error: Server package directory not found${NC}"
        exit 1
    fi
    
    # Install CLI binary to PATH
    echo -e "${YELLOW}Installing CLI binary...${NC}"
    
    # Determine the best location for the CLI binary
    if [ "$PLATFORM" == "linux" ]; then
        CLI_BIN_DIR="$HOME/.local/bin"
    else
        # macOS: use ~/.local/bin or /usr/local/bin
        CLI_BIN_DIR="$HOME/.local/bin"
        # Try /usr/local/bin if ~/.local/bin doesn't exist and we have write access
        if [ ! -d "$HOME/.local" ] && [ -w "/usr/local/bin" ]; then
            CLI_BIN_DIR="/usr/local/bin"
        fi
    fi
    
    mkdir -p "$CLI_BIN_DIR"
    
    # Find and copy the CLI binary
    if [ -d "${CLI_PACKAGE_NAME}" ]; then
        CLI_BINARY=""
        # Look for the binary (could be named deadend-cli or deadend)
        for bin in "${CLI_PACKAGE_NAME}"/deadend-cli "${CLI_PACKAGE_NAME}"/deadend "${CLI_PACKAGE_NAME}"/*; do
            if [ -f "$bin" ] && [ -x "$bin" ] || [ -f "$bin" ]; then
                CLI_BINARY="$bin"
                break
            fi
        done
        
        if [ -n "$CLI_BINARY" ] && [ -f "$CLI_BINARY" ]; then
            cp "$CLI_BINARY" "${CLI_BIN_DIR}/deadend"
            chmod +x "${CLI_BIN_DIR}/deadend"
            echo -e "${GREEN}CLI binary installed to ${CLI_BIN_DIR}/deadend${NC}"
        else
            echo -e "${YELLOW}Warning: Could not find CLI binary in package${NC}"
        fi
    else
        echo -e "${RED}Error: CLI package directory not found${NC}"
        exit 1
    fi
    
    # Check if CLI_BIN_DIR is in PATH
    if [[ ":$PATH:" != *":$CLI_BIN_DIR:"* ]]; then
        echo ""
        echo -e "${YELLOW}Note: ${CLI_BIN_DIR} is not in your PATH${NC}"
        echo -e "${YELLOW}Add it by running:${NC}"
        echo -e "  export PATH=\"${CLI_BIN_DIR}:\$PATH\""
        echo ""
        echo -e "${YELLOW}Or add to your shell configuration file:${NC}"
        if [ "$PLATFORM" == "linux" ]; then
            echo -e "  echo 'export PATH=\"${CLI_BIN_DIR}:\$PATH\"' >> ~/.bashrc"
        else
            echo -e "  echo 'export PATH=\"${CLI_BIN_DIR}:\$PATH\"' >> ~/.zshrc"
        fi
    fi
    
    echo ""
    echo -e "${GREEN}Installation complete!${NC}"
    echo ""
    echo "The Deadend CLI server is installed at:"
    echo "  ${INSTALL_DIR}/deadend.sh"
    echo ""
    if [ -f "${CLI_BIN_DIR}/deadend" ]; then
        echo "The Deadend CLI command is available at:"
        echo "  ${CLI_BIN_DIR}/deadend"
        if [[ ":$PATH:" == *":$CLI_BIN_DIR:"* ]]; then
            echo ""
            echo "You can now run: deadend"
        fi
    fi
    echo ""
    echo "You can set DEADEND_RPC_BINARY environment variable to use a custom server path:"
    echo "  export DEADEND_RPC_BINARY=\"${INSTALL_DIR}/deadend.sh\""
    echo ""
}

# Main
main() {
    echo -e "${GREEN}Deadend CLI Server Installer${NC}"
    echo ""
    
    detect_platform
    get_latest_version
    
    echo -e "${YELLOW}Platform: ${PLATFORM}${NC}"
    echo -e "${YELLOW}Target: ${TARGET}${NC}"
    echo -e "${YELLOW}Version: ${VERSION}${NC}"
    echo -e "${YELLOW}Install directory: ${INSTALL_DIR}${NC}"
    echo ""
    
    # Skip confirmation if running non-interactively
    if [ -t 0 ]; then
        read -p "Continue with installation? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Installation cancelled"
            exit 0
        fi
    fi
    
    install
}

main "$@"
