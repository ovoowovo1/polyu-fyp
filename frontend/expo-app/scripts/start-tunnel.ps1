$ErrorActionPreference = "Stop"

# Expo SDK 55 tries to run ADB reverse when an Android SDK is detected.
# On this Windows environment that can fail with "spawn EPERM" before the QR is usable.
# Point ANDROID_HOME at a non-existing path for this process only so Expo skips ADB reverse.
$env:ANDROID_HOME = "D:\__no_android_sdk_for_expo_tunnel__"
$env:ANDROID_SDK_ROOT = ""
$env:EXPO_NO_TELEMETRY = "1"

npx expo start --tunnel --clear
