#!/usr/bin/env bash
# Build, run, and generate metadata for an XBEN benchmark.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
XBEN_ROOT="$SCRIPT_DIR/xbow/validation-benchmarks/benchmarks"
METADATA_FILENAME="eval_metadata_file.json"

usage() {
    echo "Usage: $0 <benchmark-number>" >&2
    exit 1
}

require_cmd() {
    local cmd="$1"
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "Missing required command: $cmd" >&2
        exit 1
    }
}

if [[ $# -ne 1 ]]; then
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

BENCH_SLUG="$(printf "XBEN-%03d-24" "$BENCH_NUM")"
BENCH_DIR="$XBEN_ROOT/$BENCH_SLUG"
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
make -C "$BENCH_DIR" build
echo "[+] Running $BENCH_SLUG"
make -C "$BENCH_DIR" run

compose_json="$(cd "$BENCH_DIR" && docker compose ps --format json)"

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
        cd "$BENCH_DIR" && docker compose port "$service" "$port" 2>/dev/null | head -n 1 || true
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
        compose_services="$(cd "$BENCH_DIR" && docker compose config --services)"
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

env_file="$BENCH_DIR/.env"
if [[ ! -f "$env_file" ]]; then
    echo "Expected to find $env_file after starting the benchmark." >&2
    exit 1
fi

solution="$(grep -E '^FLAG=' "$env_file" | tail -n 1 | cut -d'=' -f2-)"
if [[ -z "$solution" ]]; then
    echo "FLAG entry not found inside $env_file" >&2
    exit 1
fi

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
(
    cd "$REPO_ROOT/deadend_cli/src/deadend_cli" && \
    uv run main.py eval-agent --eval-metadata-file "$META_FILE"
)

echo "[+] Stopping benchmark services with make stop"
make -C "$BENCH_DIR" stop

