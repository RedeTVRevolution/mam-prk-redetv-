import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Fuso de quem usa o MAM, fixo para os testes não dependerem da máquina.
process.env.TZ = 'America/Sao_Paulo'

export default defineConfig({
  // O Tailwind só age no CSS que o importa: o da interface nova (src/novo/index.css).
  plugins: [react(), tailwindcss()],
  // O teste do mapa de falhas lê o `api/jobs.py`, fora da pasta do front: só a pasta da API é liberada, não a raiz.
  server: { fs: { allow: ['.', '../api'] } },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/setup-testes.ts'],
    // O vitest troca o CSS por vazio, até no `?raw`; os testes de estilo e de tokens leem o texto dele.
    css: { include: [/\.css\?raw$/] },
  },
})
