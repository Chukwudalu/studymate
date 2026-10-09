import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Optional: set PROXY_TARGET (e.g. the EKS ALB URL) to run the dev server
// against a remote backend. The browser then only talks to localhost, so the
// session cookie stays same-origin and works over plain HTTP.
const target = process.env.PROXY_TARGET
const apiPaths = ['/auth', '/lectures', '/subjects', '/uploads']

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: target
    ? {
        proxy: Object.fromEntries(
          apiPaths.map((p) => [p, { target, changeOrigin: true }]),
        ),
      }
    : undefined,
})
