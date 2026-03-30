# Build Go CLIs on the official Go image so the final image does not ship ~400MB+ of Go SDK.
# Matches linux/amd64 and linux/arm64 from buildx (golang image is multi-arch).
FROM golang:tip-trixie AS go-tools
RUN go install github.com/ffuf/ffuf@latest && \
    go install github.com/OJ/gobuster/v3@latest

FROM kalilinux/kali-rolling

ENV DEBIAN_FRONTEND=noninteractive \
    PATH=$PATH:/root/.local/bin \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY --from=go-tools /go/bin/ffuf /go/bin/gobuster /usr/local/bin/

RUN apt-get update --fix-missing && \
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
        # Seclists
        seclists \
        # Additional security tools
        amap apt-utils bsdmainutils cewl crackmapexec crunch \
        dnsenum dnsrecon dnsutils dos2unix enum4linux ftp hping3 \
        joomscan kpcli libffi-dev mimikatz nasm nbtscan onesixtyone \
        oscanner passing-the-hash patator php\
        theharvester wpscan && \
    pipx install semgrep && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* \
        /usr/share/doc/* /usr/share/man/* /usr/share/info/* \
        /root/.cache/pip /root/.cache/pipx

CMD ["/bin/bash"]
