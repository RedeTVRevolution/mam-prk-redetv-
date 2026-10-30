import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Fuso de quem usa o MAM, fixo para os testes não dependerem da máquina.
process.env.TZ = 'America/Sao_Paulo'

export default defineConfig({
  plugins: [react()],
  test: { environment: 'jsdom', setupFiles: ['./src/setup-testes.ts'] },
})
