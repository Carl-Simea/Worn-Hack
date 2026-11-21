#!/bin/zsh
# Copies the feedback reports (screenshot, marked-up screenshot, note, context) from the iPhone to ./feedback/.
#   ios/scripts/pull-feedback.sh [device-udid] [bundle-id]
udid="${1:-$(xcrun devicectl list devices 2>/dev/null | awk '/connected|available/ && /iPhone/ {print $3; exit}')}"
bundle="${2:-com.larssloth.scribi}"
dest="${0:A:h:h:h}/feedback"
mkdir -p "$dest"
xcrun devicectl device copy from --device "$udid" --domain-type appDataContainer --domain-identifier "$bundle" \
  --source Documents/Feedback --destination "$dest" && echo "Feedback copied to $dest"
