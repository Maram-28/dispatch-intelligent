import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Force Vite's dev server to open in Microsoft Edge instead of the OS default browser
process.env.BROWSER = 'edge'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    open: true,
  },
})
