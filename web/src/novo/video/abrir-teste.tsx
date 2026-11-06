import { type QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, expect, vi } from 'vitest'
import { criarClienteDaApi } from '../../api.ts'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from '../../auth/falso.ts'
import type { Job } from '../../jobs.ts'
import { AtalhosProvider } from '../Atalhos.tsx'
import { ContextoDaApi, criarClienteDeConsultas } from '../consultas.ts'
import { TooltipProvider } from '../ui/tooltip.tsx'
import { TelaDoVideo } from './TelaDoVideo.tsx'

// O que os testes da tela do vídeo têm em comum: o Job, o servidor simulado e a montagem.

export const JOB: Job = {
  id: 'j1',
  nome: 'FAMA_20261021_720_BLU.mp4',
  estado: 'concluido',
  codigo_falha: null,
  duracao_s: 2959,
  programa: 'TV Fama',
  data_exibicao: '2026-10-21',
  timecode_origem: '01:00:00:00',
  taxa_de_quadros: 30,
  cortes_ms: [60_000, 120_000],
  criado_em: '2026-10-21T10:00:00Z',
}

export const REPRODUCAO = { url: 'https://exemplo.test/v.mp4', expira_em: '2999-01-01T00:00:00Z' }

/** As rotas que toda abertura usa: o Job, o link do vídeo e a decupagem. */
export function rotasDoVideo(job: () => Partial<Job>, decupagem: () => object) {
  return [
    http.get('/v1/jobs/j1', () => HttpResponse.json({ ...JOB, ...job() })),
    http.get('/v1/jobs/j1/reproducao', () => HttpResponse.json(REPRODUCAO)),
    http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(decupagem())),
    // O pulso da sessão de revisão (#251): quem quiser contá-lo declara o próprio handler antes destas rotas.
    http.post('/v1/jobs/j1/revisao/pulso', () => new HttpResponse(null, { status: 204 })),
  ]
}

/** O jsdom não toca vídeo: `paused` e `playbackRate` ficam por conta do teste. */
export const playMock = vi.fn()
export const pauseMock = vi.fn()
export function simularPlayer() {
  beforeEach(() => {
    playMock.mockReset().mockImplementation(function (this: HTMLVideoElement) {
      Object.defineProperty(this, 'paused', { value: false, configurable: true })
      return Promise.resolve()
    })
    pauseMock.mockReset().mockImplementation(function (this: HTMLVideoElement) {
      Object.defineProperty(this, 'paused', { value: true, configurable: true })
    })
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(playMock)
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(pauseMock)
  })
}

export interface Abertura {
  t?: number | null
  permissoes?: string[]
  acompanhamentoMs?: number
  indexacaoMs?: number
  /** Espera o vídeo e a linha do tempo (só com a decupagem pronta). */
  esperarFaixas?: boolean
  /** O cliente de consultas, para o teste ver ou preparar o cache (o do acervo, por exemplo). */
  consultas?: QueryClient
}

export async function abrirVideo({ t = null, permissoes = ['decupagem.ver'], acompanhamentoMs = 5000, indexacaoMs = 2000, esperarFaixas = true, consultas = criarClienteDeConsultas() }: Abertura = {}) {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', '/video/j1')
  render(
    <QueryClientProvider client={consultas}>
      <ContextoDaApi.Provider value={criarClienteDaApi(auth, () => {})}>
        <AtalhosProvider>
          <TooltipProvider>
            <input aria-label="Campo" />
            <TelaDoVideo id="j1" t={t} permissoes={permissoes} intervalos={{ acompanhamentoMs, indexacaoMs }} />
          </TooltipProvider>
        </AtalhosProvider>
      </ContextoDaApi.Provider>
    </QueryClientProvider>,
  )
  const player = (await screen.findByLabelText('Player')) as HTMLVideoElement
  await waitFor(() => expect(player.getAttribute('src')).toBe(REPRODUCAO.url))
  if (esperarFaixas) await screen.findByRole('group', { name: /^Pautas \d+$/ })
  return player
}

export function irPara(player: HTMLVideoElement, segundos: number) {
  player.currentTime = segundos
  fireEvent.timeUpdate(player)
}

/** A faixa, com a largura de 1000 px a partir de x = 100: o clique em x vale (x − 100) / 1000 da duração. */
export function medir(el: Element) {
  el.getBoundingClientRect = () => ({ left: 100, width: 1000, top: 0, right: 1100, bottom: 18, height: 18, x: 100, y: 0, toJSON: () => ({}) }) as DOMRect
}
