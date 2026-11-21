#!/bin/zsh
# Builds ios/build-glasses/: the vendor's MLDemo project (CocoaPods + MLVisionM6SDK already wired and tested by
# the vendor) with its demo UI swapped for Worn. Nothing here is committed (ios/.gitignore): the SDK is confidential.
#
#   ios/scripts/make-glasses-build.sh            # then open ios/build-glasses/WornGlasses.xcworkspace
#   WORN_BUNDLE_ID=com.you.worn WORN_TEAM=ABCDE12345 ios/scripts/make-glasses-build.sh
#
# Re-run it after pulling new Worn code: it refreshes the copy in a few seconds.
here="${0:A:h}"; ios="${here:h}"; repo="${ios:h}"
kit="$repo/Microlumin_Ship/04_Demo_Apps/MLDemo"
out="$ios/build-glasses"
bundle="${WORN_BUNDLE_ID:-com.worn.glasses}"

if [[ ! -d "$kit" ]]; then echo "error: SDK kit not found at $kit" >&2; exit 1; fi
mkdir -p "$out" || exit 1

# 1. Fresh copy of the vendor project (Pods are checked in, so no `pod install`).
rsync -a --delete --exclude 'xcuserdata' --exclude 'WornGlasses.xcworkspace' "$kit/" "$out/" || exit 1

# 2. Keep the vendor's SDK wrapper (GlassesSession, DiscoveryGate, InterpretingTap, SpeechLanguages, SavedNetworks,
#    MLAudioPlayerManager, MLVisionM6SDK/); drop the demo's UI and app entry point.
cd "$out/MLDemo" || exit 1
rm -f AppDelegate.swift SceneDelegate.swift HomeViewController.swift FeatureViewControllers.swift \
      Form.swift Components.swift Theme.swift WifiViewController.swift

# 3. Worn's sources (same files as the standalone project; SDKGlassesLink.swift switches on via canImport).
rsync -a --delete "$ios/Worn/" "$out/MLDemo/Worn/" || exit 1

# 4. SwiftUI lifecycle + Worn's permission strings and name.
plist="$out/MLDemo/Info.plist"
plutil -remove UIApplicationSceneManifest.UISceneConfigurations "$plist" 2>/dev/null
plutil -replace CFBundleDisplayName -string "Worn" "$plist" \
 && plutil -replace NSSpeechRecognitionUsageDescription -string "Voice commands are recognized on this iPhone so you can practice hands-free." "$plist" \
 && plutil -replace NSMicrophoneUsageDescription -string "Say next, again, slower or check to practice hands-free." "$plist" \
 && plutil -replace NSCameraUsageDescription -string "In Demo Mode the camera watches your page so the next stroke follows your pen." "$plist" \
 || exit 1

# 5. Bundle id, deployment target (Worn uses iOS 17 APIs), optional signing team.
pbx="$out/MLDemo.xcodeproj/project.pbxproj"
sed -i '' -e "s/com\.CHANGEME\.mldemo/$bundle/g" \
          -e "s/IPHONEOS_DEPLOYMENT_TARGET = 15;/IPHONEOS_DEPLOYMENT_TARGET = 17.0;/g" \
          -e 's/INFOPLIST_KEY_NSCameraUsageDescription = "[^"]*";/INFOPLIST_KEY_NSCameraUsageDescription = "In Demo Mode the camera watches your page so the next stroke follows your pen.";/g' \
          -e 's/INFOPLIST_KEY_NSMicrophoneUsageDescription = "[^"]*";/INFOPLIST_KEY_NSMicrophoneUsageDescription = "Say next, again, slower or check to practice hands-free.";/g' "$pbx" || exit 1
if [[ -n "$WORN_TEAM" ]]; then sed -i '' "s/DEVELOPMENT_TEAM = \"\";/DEVELOPMENT_TEAM = $WORN_TEAM;/g" "$pbx" || exit 1; fi

# 6. A workspace with Worn's name (same contents as MLDemo.xcworkspace: app project + Pods).
rm -rf "$out/WornGlasses.xcworkspace" && cp -R "$out/MLDemo.xcworkspace" "$out/WornGlasses.xcworkspace" || exit 1

echo "Ready: open \"$out/WornGlasses.xcworkspace\" (scheme MLDemo, product name Worn, bundle id $bundle)"
