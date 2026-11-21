#!/bin/zsh
# Unit tests for the pure core (stroke parsing, ink diff, pacer, voice parser) on macOS. No Xcode project needed.
cd "${0:A:h}/../Worn/Core" || exit 1
out="${TMPDIR:-/tmp}/worn-core-tests"
swiftc -O -o "$out" StrokeData.swift InkDiff.swift Pacer.swift VoiceCommand.swift "${0:A:h}/CoreTests.swift" && "$out" "${0:A:h}/../../content/strokes"
