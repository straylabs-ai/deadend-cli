#!/usr/bin/env bash
# Check which XBEN benchmarks have been successfully solved by grepping the flag
# from eval_metadata_file.json into the deadend_cli benchmark result logs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

XBEN_ROOT="$SCRIPT_DIR/xbow/validation-benchmarks/benchmarks"

START_NUM=1
END_NUM=104

usage() {
    echo "Usage: $0 [RESULTS_DIR]" >&2
    echo "  RESULTS_DIR: Directory containing .log result files (default: current directory)" >&2
    exit 1
}

require_cmd() {
    local cmd="$1"
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "Missing required command: $cmd" >&2
        exit 1
    }
}

require_cmd jq
require_cmd grep

# Get results directory from argument or use current directory
if [[ $# -gt 1 ]]; then
    usage
fi

RESULTS_DIR="${1:-.}"
if [[ ! -d "$RESULTS_DIR" ]]; then
    echo "Error: Results directory does not exist: $RESULTS_DIR" >&2
    exit 1
fi

TOTAL=0
SUCCESS=0
FAILED=0
NOT_STARTED=0
SUCCESS_NUMS=()
FAILED_NUMS=()
NOT_STARTED_NUMS=()

printf "Checking benchmarks from %d to %d\n" "$START_NUM" "$END_NUM"
printf "Results directory: %s\n" "$RESULTS_DIR"
printf "Metadata root    : %s\n" "$XBEN_ROOT"
echo "============================================================"

for (( num=START_NUM; num<=END_NUM; num++ )); do
    TOTAL=$((TOTAL + 1))
    BENCH_SLUG="$(printf "XBEN-%03d-24" "$num")"

    BENCH_DIR="$XBEN_ROOT/$BENCH_SLUG"
    META_FILE="$BENCH_DIR/eval_metadata_file.json"

    if [[ ! -d "$BENCH_DIR" || ! -f "$META_FILE" ]]; then
        printf "[NOT STARTED] %s (missing directory or %s)\n" "$BENCH_SLUG" "$(basename "$META_FILE")"
        NOT_STARTED=$((NOT_STARTED + 1))
        NOT_STARTED_NUMS+=("$num")
        continue
    fi

    solution="$(jq -r '.solution // empty' "$META_FILE" || true)"
    if [[ -z "$solution" ]]; then
        printf "[FAILED] %s (no solution field in metadata)\n" "$BENCH_SLUG"
        FAILED=$((FAILED + 1))
        FAILED_NUMS+=("$num")
        continue
    fi

    # Look for matching result files in RESULTS_DIR
    # They typically start with the benchmark slug, but we allow any match.
    # Support both .txt and .log extensions
    shopt -s nullglob
    mapfile -t candidate_files < <(find "$RESULTS_DIR" -maxdepth 1 -type f \( -name "${BENCH_SLUG}_*.txt" -o -name "*${BENCH_SLUG}*.txt" -o -name "${BENCH_SLUG}_*.log" -o -name "*${BENCH_SLUG}*.log" \))
    shopt -u nullglob

    if [[ ${#candidate_files[@]} -eq 0 ]]; then
        printf "[NOT STARTED] %s (no result files in %s)\n" "$BENCH_SLUG" "$RESULTS_DIR"
        NOT_STARTED=$((NOT_STARTED + 1))
        NOT_STARTED_NUMS+=("$num")
        continue
    fi

    found=false
    for f in "${candidate_files[@]}"; do
        if grep -qF "$solution" "$f"; then
            printf "[SUCCESS] %s -> %s\n" "$BENCH_SLUG" "$(basename "$f")"
            SUCCESS=$((SUCCESS + 1))
            SUCCESS_NUMS+=("$num")
            found=true
            break
        fi
    done

    if [[ "$found" == "false" ]]; then
        printf "[FAILED] %s (flag not found in %d result file(s))\n" "$BENCH_SLUG" "${#candidate_files[@]}"
        FAILED=$((FAILED + 1))
        FAILED_NUMS+=("$num")
    fi
done

echo "============================================================"
echo "Summary"
echo "============================================================"
printf "Benchmarks checked : %d\n" "$TOTAL"
printf "Successful         : %d\n" "$SUCCESS"
printf "Failed             : %d\n" "$FAILED"
printf "Not started        : %d\n" "$NOT_STARTED"
echo "============================================================"

started=$((TOTAL - NOT_STARTED))
if (( started > 0 )); then
    success_pct=$(awk "BEGIN { printf \"%.2f\", ($SUCCESS/$started)*100 }")
    fail_pct=$(awk "BEGIN { printf \"%.2f\", ($FAILED/$started)*100 }")
else
    success_pct="0.00"
    fail_pct="0.00"
fi

printf "Success ratio (started) : %d/%d (%.2f%%)\n" "$SUCCESS" "$started" "$success_pct"
printf "Failure ratio (started) : %d/%d (%.2f%%)\n" "$FAILED" "$started" "$fail_pct"
echo "============================================================"

if (( SUCCESS > 0 )); then
    printf "Successful benchmarks     : %s\n" "${SUCCESS_NUMS[*]}"
fi
if (( FAILED > 0 )); then
    printf "Failed benchmarks         : %s\n" "${FAILED_NUMS[*]}"
fi
if (( NOT_STARTED > 0 )); then
    printf "Not started benchmarks    : %s\n" "${NOT_STARTED_NUMS[*]}"
fi
echo "============================================================"

