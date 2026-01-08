#!/usr/bin/env bash
# Stop all XBEN benchmarks by running 'make stop' in each directory
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XBEN_ROOT="$SCRIPT_DIR/xbow/validation-benchmarks/benchmarks"

if [[ ! -d "$XBEN_ROOT" ]]; then
    echo "Error: XBEN benchmarks directory not found: $XBEN_ROOT" >&2
    exit 1
fi

require_cmd() {
    local cmd="$1"
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "Missing required command: $cmd" >&2
        exit 1
    }
}

require_cmd make

# Find all XBEN-XXX-24 directories and sort them
bench_dirs=()
while IFS= read -r -d '' dir; do
    bench_dirs+=("$dir")
done < <(find "$XBEN_ROOT" -maxdepth 1 -type d -name "XBEN-*-24" -print0 | sort -z)

if [[ ${#bench_dirs[@]} -eq 0 ]]; then
    echo "No XBEN benchmark directories found in $XBEN_ROOT" >&2
    exit 1
fi

echo "Found ${#bench_dirs[@]} benchmark directories"
echo "Stopping all benchmarks..."
echo ""

success_count=0
fail_count=0
skipped_count=0

for bench_dir in "${bench_dirs[@]}"; do
    bench_name=$(basename "$bench_dir")
    
    if [[ ! -f "$bench_dir/Makefile" ]]; then
        echo "[SKIP] $bench_name - No Makefile found"
        ((skipped_count++)) || true
        continue
    fi
    
    echo -n "[STOP] $bench_name ... "
    
    # Change to the benchmark directory and run make stop
    # Continue on error so we can stop all benchmarks even if some fail
    if (cd "$bench_dir" && make stop >/dev/null 2>&1); then
        echo "OK"
        ((success_count++)) || true
    else
        echo "FAILED (may not be running)"
        ((fail_count++)) || true
    fi
done

echo ""
echo "Summary:"
echo "  Successfully stopped: $success_count"
echo "  Failed: $fail_count"
echo "  Skipped: $skipped_count"
echo "  Total: ${#bench_dirs[@]}"

# Exit with error if any failed (but allow skipped)
if [[ $fail_count -gt 0 ]]; then
    exit 1
fi

exit 0

