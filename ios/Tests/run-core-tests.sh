#!/bin/zsh
# Unit tests for the pure core (stroke parsing, ink diff, pacer, voice parser) on macOS. No Xcode project needed.
here="${0:A:h}"
core="$here/../Worn/Core"
tmp="${TMPDIR:-/tmp}/worn-core-tests"
mkdir -p "$tmp" && cp "$here/CoreTests.swift" "$tmp/main.swift" \
  && swiftc -O -o "$tmp/run" "$core/StrokeData.swift" "$core/InkDiff.swift" "$core/Pacer.swift" "$core/StrokeTracker.swift" "$core/InkSplit.swift" "$core/VoiceCommand.swift" "$core/NameSpeller.swift" "$core/Models.swift" "$tmp/main.swift" \
  && "$tmp/run" "$here/../../content/strokes"
