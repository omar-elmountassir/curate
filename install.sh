#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$HOME/.claude/skills"
BIN_DIR="$HOME/.local/bin"

echo "Installing curate..."

# Install dependencies
echo "  Installing Python dependencies..."
cd "$SCRIPT_DIR"
uv sync 2>/dev/null || uv pip install -e ".[dev]" 2>/dev/null || pip install -e .

# Create wrapper script if it doesn't exist
if [ ! -f "$SCRIPT_DIR/curate" ]; then
    echo "  Creating wrapper script..."
    cat > "$SCRIPT_DIR/curate" << 'WRAPPER'
#!/usr/bin/env bash
# curate — File system curation CLI wrapper
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
exec uv run --project "$SCRIPT_DIR" "$SCRIPT_DIR/src/curate/cli.py" "$@"
WRAPPER
    chmod +x "$SCRIPT_DIR/curate"
fi

# Link skill
echo "  Linking skill..."
mkdir -p "$SKILLS_DIR"
ln -sf "$SCRIPT_DIR" "$SKILLS_DIR/curate"

# Link CLI
echo "  Linking CLI..."
mkdir -p "$BIN_DIR"
ln -sf "$SCRIPT_DIR/curate" "$BIN_DIR/curate"

echo ""
echo "Done! curate is now available."
echo "  CLI: curate --help"
echo "  Skill: ~/.claude/skills/curate/"
