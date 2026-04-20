# Vite Project

A React + Vite frontend application with Ant Design components, Redux Toolkit, React Router, i18next, and Tailwind CSS. It appears to be an educational platform with Student and Teacher login flows.

## Project Structure

- `vite-project/` - Main frontend application
  - `src/` - Source code
    - `api/` - API client modules
    - `components/` - Reusable React components
    - `hooks/` - Custom React hooks
    - `i18n/` - Internationalization config
    - `pages/` - Page-level components
    - `redux/` - Redux store and slices
    - `utils/` - Utility helpers
    - `config.js` - App configuration
  - `vite.config.js` - Vite configuration (host: 0.0.0.0, port: 5000, allowedHosts: true)
  - `.env` - Environment variables (VITE_API_BASE_URL)

## Tech Stack

- React 18 + Vite 7
- Ant Design 5 + @ant-design/x + @ant-design/pro-chat
- Redux Toolkit + React Redux
- React Router DOM 7
- i18next + react-i18next
- Tailwind CSS
- Axios
- Framer Motion

## Development

The app runs on port 5000 via the "Start application" workflow:
```
cd vite-project && npm run dev
```

## Deployment

Configured as a static site:
- Build: `cd vite-project && npm run build`
- Public dir: `vite-project/dist`
