$ErrorActionPreference = "Stop"

$env:EXPO_NO_TELEMETRY = "1"

npx expo start --lan --clear
