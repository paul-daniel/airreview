#!/usr/bin/env zsh
set -euo pipefail

AIRREVIEW_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AIRREVIEW_BIN="$AIRREVIEW_ROOT/.venv/bin/airreview"
AIRREVIEW_BIN_DIR="$AIRREVIEW_ROOT/.venv/bin"
SHELL_RC="${HOME}/.zshrc"
ALIAS_LINE="alias airreview='${AIRREVIEW_BIN}'"
PATH_LINE="export PATH=\"${AIRREVIEW_BIN_DIR}:\$PATH\""

if [[ ! -x "$AIRREVIEW_BIN" ]]; then
  echo "AirReview binary not found at: $AIRREVIEW_BIN"
  echo "Run from ${AIRREVIEW_ROOT}: python3 -m venv .venv && source .venv/bin/activate && pip install ."
  exit 1
fi

touch "$SHELL_RC"

if grep -Fq "$PATH_LINE" "$SHELL_RC"; then
  echo "PATH entry already installed in $SHELL_RC"
else
  {
    echo ""
    echo "# AirReview CLI PATH"
    echo "$PATH_LINE"
  } >> "$SHELL_RC"
  echo "Installed PATH entry in $SHELL_RC"
fi

if grep -Fq "$ALIAS_LINE" "$SHELL_RC"; then
  echo "Alias already installed in $SHELL_RC"
else
  {
    echo ""
    echo "# AirReview CLI"
    echo "$ALIAS_LINE"
  } >> "$SHELL_RC"
  echo "Installed alias in $SHELL_RC"
fi

echo "Run this now, or open a new terminal:"
echo "  source $SHELL_RC"
echo ""
echo "Then use:"
echo "  airreview --mock --output"
