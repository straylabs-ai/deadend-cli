#!/usr/bin/env bash
# Build, run, and generate metadata for an XBEN benchmark.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
XBEN_ROOT="$SCRIPT_DIR/xbow/validation-benchmarks/benchmarks"
METADATA_FILENAME="eval_metadata_file.json"

usage() {
    echo "Usage: $0 <benchmark-number> [OUTPUT_DIR=<directory>]" >&2
    echo "  OUTPUT_DIR: Directory to save output logs (default: current directory)" >&2
    exit 1
}

require_cmd() {
    local cmd="$1"
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "Missing required command: $cmd" >&2
        exit 1
    }
}

run_with_network_prune() {
    local max_retries=2
    local retry_count=0
    
    while (( retry_count <= max_retries )); do
        if output=$("$@" 2>&1); then
            echo "$output"
            return 0
        fi
        
        if echo "$output" | grep -q "all predefined address pools have been fully subnetted"; then
            echo "[!] Docker network pool exhausted, pruning unused networks..." >&2
            docker network prune -f >/dev/null 2>&1 || true
            retry_count=$((retry_count + 1))
            if (( retry_count <= max_retries )); then
                echo "[+] Retrying after network prune (attempt $retry_count/$max_retries)..." >&2
                continue
            fi
        fi
        
        echo "$output" >&2
        return 1
    done
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
    usage
fi

require_cmd jq
require_cmd docker
require_cmd make
require_cmd uv
BENCH_NUM="$1"
if ! [[ "$BENCH_NUM" =~ ^[0-9]+$ ]] || (( BENCH_NUM <= 0 )); then
    echo "Benchmark number must be a positive integer." >&2
    exit 1
fi

# Get output directory from environment variable or use default
OUTPUT_DIR="${OUTPUT_DIR:-.}"
if [[ ! -d "$OUTPUT_DIR" ]]; then
    mkdir -p "$OUTPUT_DIR" || {
        echo "Failed to create output directory: $OUTPUT_DIR" >&2
        exit 1
    }
fi

BENCH_SLUG="$(printf "XBEN-%03d-24" "$BENCH_NUM")"
BENCH_DIR="$XBEN_ROOT/$BENCH_SLUG"
LOG_FILE="$OUTPUT_DIR/${BENCH_SLUG}.log"

BENCH_JSON="$BENCH_DIR/benchmark.json"
META_FILE="$BENCH_DIR/$METADATA_FILENAME"

if [[ ! -d "$BENCH_DIR" ]]; then
    echo "Benchmark directory not found: $BENCH_DIR" >&2
    exit 1
fi

if [[ ! -f "$BENCH_JSON" ]]; then
    echo "Missing benchmark.json in $BENCH_DIR" >&2
    exit 1
fi

name="$(jq -r '.name // empty' "$BENCH_JSON")"
description="$(jq -r '.description // ""' "$BENCH_JSON")"
tags_json="$(jq '.tags // []' "$BENCH_JSON")"
level="$(jq -r '(.level // "") | tostring' "$BENCH_JSON")"
win_condition="$(jq -r '.win_condition // "flag"' "$BENCH_JSON")"
subtasks_json="$(jq '.subtasks // []' "$BENCH_JSON")"

echo "[+] Building $BENCH_SLUG"
if ! make -C "$BENCH_DIR" build 2>&1 | tee /tmp/build_output.log; then
    if grep -q "all predefined address pools have been fully subnetted" /tmp/build_output.log; then
        echo "[!] Docker network pool exhausted during build, pruning unused networks..."
        docker network prune -f
        echo "[+] Retrying build after network prune..."
        make -C "$BENCH_DIR" build
    else
        exit 1
    fi
fi

echo "[+] Running $BENCH_SLUG"
if ! make -C "$BENCH_DIR" run 2>&1 | tee /tmp/run_output.log; then
    if grep -q "all predefined address pools have been fully subnetted" /tmp/run_output.log; then
        echo "[!] Docker network pool exhausted during run, pruning unused networks..."
        docker network prune -f
        echo "[+] Retrying run after network prune..."
        make -C "$BENCH_DIR" run
    else
        exit 1
    fi
fi

compose_json="$(cd "$BENCH_DIR" && run_with_network_prune docker compose ps --format json)"

host=""
host_port=""

extract_host_port() {
    local line="$1"
    line="${line##*-> }"
    line="${line//[/}"
    line="${line//]/}"
    local h="${line%:*}"
    local p="${line##*:}"
    printf '%s\t%s\n' "$h" "$p"
}

container_names="$(printf '%s\n' "$compose_json" | jq -rs '.[] | select(.Name != null) | .Name')"
if [[ -n "$container_names" ]]; then
    while read -r container; do
        [[ -n "$container" ]] || continue
        port_output="$(docker port "$container" 2>/dev/null || true)"
        status="$(docker inspect --format '{{.State.Status}}' "$container" 2>/dev/null || true)"
        if [[ -z "$port_output" || "$status" != "running" ]]; then
            continue
        fi
        first_line="$(printf '%s\n' "$port_output" | head -n 1)"
        if [[ -n "$first_line" ]]; then
            map_line="$(extract_host_port "$first_line")"
            host="127.0.0.1"
            host_port="${map_line##*$'\t'}"
            break
        fi
    done <<< "$container_names"
fi

if [[ -z "$host_port" ]]; then
    candidate_ports="$(printf '%s\n' "$compose_json" | jq -rs '
        map(.Service as $svc | (.Publishers[]? | select(.TargetPort != null) | [$svc, (.TargetPort|tostring)]))
        | .[]
        | @tsv
    ')"

    resolve_port() {
        local service="$1"
        local port="$2"
        cd "$BENCH_DIR" && run_with_network_prune docker compose port "$service" "$port" 2>/dev/null | head -n 1 || true
    }

    if [[ -n "$candidate_ports" ]]; then
        while IFS=$'\t' read -r service_name target_port; do
            [[ -n "$service_name" && -n "$target_port" ]] || continue
            mapping="$(resolve_port "$service_name" "$target_port")"
            if [[ -n "$mapping" ]]; then
                host="127.0.0.1"
                host_port="${mapping##*:}"
                break
            fi
        done <<< "$candidate_ports"
    fi

    if [[ -z "$host_port" ]]; then
        compose_services="$(cd "$BENCH_DIR" && run_with_network_prune docker compose config --services)"
        if [[ -z "$compose_services" ]]; then
            echo "Unable to determine docker compose services for port resolution." >&2
            exit 1
        fi

        default_ports="80 443 8080 3000 8000 5000 1337 1338"
        while read -r service_name; do
            [[ -n "$service_name" ]] || continue
            for target_port in $default_ports; do
                mapping="$(resolve_port "$service_name" "$target_port")"
                if [[ -n "$mapping" ]]; then
                    host="127.0.0.1"
                    host_port="${mapping##*:}"
                    break 2
                fi
            done
        done <<< "$compose_services"
    fi
fi

if [[ -z "$host_port" ]]; then
    echo "Unable to resolve a mapped host port." >&2
    exit 1
fi

target_host="$host:$host_port"

# Generate flag the same way as common.mk:
# 1. Convert benchmark name to uppercase
# 2. Compute SHA256 hash
# 3. Format as FLAG{hash}
benchmark_upper="$(echo "$BENCH_SLUG" | tr '[:lower:]' '[:upper:]')"
flag_hash="$(echo -n "$benchmark_upper" | openssl sha256 -r | cut -d' ' -f1)"
solution="FLAG{$flag_hash}"

metadata="$(jq -n \
    --arg name "${name:-$BENCH_SLUG}" \
    --argjson categories "$tags_json" \
    --arg difficulty "$level" \
    --arg assets_path "$BENCH_DIR" \
    --arg hard_prompt "$description" \
    --arg soft_prompt "$description" \
    --arg target_host "$target_host" \
    --arg validation_type "$win_condition" \
    --arg validation_format "$win_condition" \
    --arg solution "$solution" \
    --argjson subtasks "$subtasks_json" \
    '{
        name: $name,
        categories: $categories,
        difficulty: $difficulty,
        assets_path: $assets_path,
        hard_prompt: $hard_prompt,
        soft_prompt: $soft_prompt,
        target_host: $target_host,
        validation_type: $validation_type,
        validation_format: $validation_format,
        solution: $solution,
        subtasks: $subtasks
    }'
)"

printf '%s\n' "$metadata" > "$META_FILE"
echo "[+] Metadata written to $META_FILE"
echo "[+] Benchmark ready at $target_host"

echo "[+] Launching eval agent with uv run"
echo "[+] Logging uv run output to: $LOG_FILE"
(
    cd "$REPO_ROOT/deadend_cli/src/deadend_cli" && \
    uv run main.py eval-agent --eval-metadata-file "$META_FILE" --llm-providers local
) 2>&1 | tee "$LOG_FILE"

echo "[+] Stopping benchmark services with make stop"
make -C "$BENCH_DIR" stop

rm -f /tmp/build_output.log /tmp/run_output.log

