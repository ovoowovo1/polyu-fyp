# PolyU FYP Expo App

This Expo app is the mobile client for the PolyU FYP Learning Platform. It connects to the same FastAPI backend as the web app in `frontend/vite-project` and supports the core class, source, chat, quiz, and exam workflows on mobile.

## What This App Is

- Mobile frontend built with Expo Router and React Native
- Shares the backend with the web app
- Intended for Android, iOS, and Expo web development/testing

## Setup

From the repository root:

```powershell
cd frontend\expo-app
npm install
Copy-Item .env.example .env
```

If you are using macOS or Linux, use:

```bash
cd frontend/expo-app
npm install
cp .env.example .env
```

## Environment Variable

The Expo example file is `frontend/expo-app/.env.example`.

Use `EXPO_PUBLIC_API_BASE_URL` to point the app at a reachable backend URL.

Examples:

- Android emulator:
  `EXPO_PUBLIC_API_BASE_URL=http://10.0.2.2:3000`
- Physical device on the same Wi-Fi:
  `EXPO_PUBLIC_API_BASE_URL=http://<your-lan-ip>:3000`

## Run The App

Start the Expo dev server:

```powershell
cd frontend\expo-app
npm run start
```

Common launch commands:

```powershell
npm run android
npm run ios
npm run web
```

The app also includes helper scripts for mobile-device testing:

```powershell
npm run start:lan
npm run start:tunnel
```

## Development Notes

- Start the backend before using the app.
- For physical-device testing, `localhost` usually will not work; use a LAN IP or tunnel URL.
- The app uses Expo Router file-based routing under `frontend/expo-app/src/app`.
- The app uses React Context providers for auth, language, and document workspace state; it does not use Redux.

## Verification

Static verification for the Expo app:

```powershell
cd frontend\expo-app
npx tsc --noEmit
```

Optional lint check:

```powershell
npm run lint
```
