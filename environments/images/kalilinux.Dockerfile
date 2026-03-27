FROM kalilinux/kali-rolling

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH=$PATH:/usr/local/go/bin:/root/go/bin:/root/.cargo/bin:/root/.local/bin
ENV GOPATH=/root/go
ENV CARGO_HOME=/root/.cargo
ENV RUSTUP_HOME=/root/.rustup

RUN apt-get update --fix-missing && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        # Basic system utilities
        vim nano htop tree wget unzip tar gzip \
        # Network tools
        inetutils-* ncat tcpdump \
        # Development tools
        gcc make git curl \
        # Python environment
        python3 python3-pip python3-setuptools python3-dev python3-venv pipx \
        # Security tools
        nmap masscan nikto dirb sqlmap hydra john hashcat \
        # Additional security tools
        amap apt-utils bsdmainutils cewl crackmapexec crunch \
        dnsenum dnsrecon dnsutils dos2unix enum4linux ftp hping3 \
        joomscan kpcli libffi-dev mimikatz nasm nbtscan onesixtyone \
        oscanner passing-the-hash patator php powershell powersploit \
        theharvester whois wpscan && \
    # Install Go
    wget -O go.tar.gz https://go.dev/dl/go1.21.5.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go.tar.gz && \
    rm go.tar.gz && \
    # Install Rust
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y && \
    # Install Go tools
    /usr/local/go/bin/go install github.com/ffuf/ffuf@latest && \
    /usr/local/go/bin/go install github.com/OJ/gobuster/v3@latest && \
    # install semgrep
    pipx install semgrep && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* && \
    /usr/local/go/bin/go clean -cache -modcache -testcache 

CMD ["/bin/bash"]