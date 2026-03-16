#!/bin/bash
# Compile all standalone .tex files, log failures
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGFILE="scripts/compile_log.txt"
> "$LOGFILE"

SUCCESS=0
FAIL=0
XELATEX=0

for texfile in $(find . -name "*.tex" -not -path "./scripts/*" | sort); do
    dir=$(dirname "$texfile")
    base=$(basename "$texfile")
    
    # Check if xelatex is required
    if grep -q "% Requires: xelatex" "$texfile" 2>/dev/null || grep -q "\\\\usepackage{fontspec}" "$texfile" 2>/dev/null; then
        compiler="xelatex"
        XELATEX=$((XELATEX + 1))
    else
        compiler="pdflatex"
    fi
    
    # Compile
    cd "$dir"
    $compiler -interaction=nonstopmode -halt-on-error "$base" > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        SUCCESS=$((SUCCESS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: $texfile ($compiler)" >> "$REPO_ROOT/$LOGFILE"
    fi
    
    # Clean build artifacts
    rm -f *.aux *.log *.synctex.gz *.fdb_latexmk *.fls *.out 2>/dev/null
    
    cd "$REPO_ROOT"
done

echo "" >> "$LOGFILE"
echo "SUCCESS: $SUCCESS" >> "$LOGFILE"
echo "FAIL: $FAIL" >> "$LOGFILE"
echo "XELATEX: $XELATEX" >> "$LOGFILE"
echo "TOTAL: $((SUCCESS + FAIL))" >> "$LOGFILE"

echo "Compilation complete: $SUCCESS success, $FAIL failures (out of $((SUCCESS + FAIL)) total)"
cat "$LOGFILE"
