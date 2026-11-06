import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Entradas from './Entradas.tsx'
import { AtalhosProvider } from '../Atalhos.tsx'
import { ContextoDaApi } from '../consultas.ts'
import { TooltipProvider } from '../ui/tooltip.tsx'
import { criarClienteDaApi } from '../../api.ts'
import { filtrosDasEntradas } from '../../entradas.ts'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from '../../auth/falso.ts'
import { useRota } from '../../rotas.ts'
import type { Job } from '../../jobs.ts'
import { comAlturaNaRolagem } from './teste.ts'

function job(extra: Partial<Job>): Job {
  return {
    id: 'j1',
    nome: 'clipe.mp4',
    estado: 'concluido',
    codigo_falha: null,
    programa: null,
    enviado_por: { tipo: 'pessoa', nome: 'ana@redetv.com.br' },
    criado_em: '2026-10-29T15:00:00Z',
    atualizado_em: '2026-10-29T15:10:00Z',
    ...extra,
  }
}

const ETAPA_OK = { inicio: '2026-10-29T15:01:00Z', fim: '2026-10-29T15:03:05Z', resultado: 'concluida' as const }

let jobs: Job[] = []
const consultas: string[] = []
const detalhes: string[] = []
const pedidos: string[][] = []
const reprocessos: { id: string; corpo: unknown }[] = []

const servidor = setupServer(
  http.get('/v1/jobs', ({ request }) => {
    const url = new URL(request.url)
    consultas.push(url.search)
    const sistema = url.searchParams.get('sistema')
    return HttpResponse.json(jobs.filter((j) => !sistema || j.enviado_por?.nome === sistema))
  }),
  http.get('/v1/jobs/andamento', ({ request }) => {
    const ids = new URL(request.url).searchParams.get('ids')!.split(',')
    pedidos.push(ids)
    detalhes.push(...ids)
    return HttpResponse.json(jobs.filter((j) => ids.includes(j.id)))
  }),
  http.get('/v1/admin/chaves', () => new HttpResponse(null, { status: 403 })),
  http.post('/v1/jobs/:id/reprocessar', async ({ params, request }) => {
    const corpo = await request.json().catch(() => null)
    reprocessos.push({ id: String(params.id), corpo })
    const antigo = jobs.find((j) => j.id === params.id)!
    const etapa = (corpo as { etapa?: string } | null)?.etapa ?? antigo.etapas?.find((e) => e.resultado === 'falhou')?.nome ?? 'leitura_da_tela'
    const novo: Job = {
      ...antigo,
      estado: antigo.estado === 'falhou' ? 'analisando' : antigo.estado,
      codigo_falha: null,
      etapa_atual: etapa,
    }
    jobs = jobs.map((j) => (j.id === novo.id ? novo : j))
    return HttpResponse.json(novo)
  }),
)

comAlturaNaRolagem()
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  history.replaceState(null, '', '/')
  servidor.resetHandlers()
  Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
  jobs = []
  consultas.length = 0
  detalhes.length = 0
  pedidos.length = 0
  reprocessos.length = 0
  cleanup()
})
afterAll(() => servidor.close())

function Tela({ podeReprocessar, podeEscolherEtapa, intervaloMs }: { podeReprocessar: boolean; podeEscolherEtapa: boolean; intervaloMs: number }) {
  const rota = useRota()
  if (rota.tipo !== 'admin') return null
  return <Entradas filtros={filtrosDasEntradas(rota.busca)} podeReprocessar={podeReprocessar} podeEscolherEtapa={podeEscolherEtapa} podeVerSistemas={false} intervaloMs={intervaloMs} />
}

async function abrir(opcoes: { endereco?: string; podeReprocessar?: boolean; podeEscolherEtapa?: boolean } = {}) {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', opcoes.endereco ?? '/admin/entradas')
  const consultas = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 30_000 } } })
  render(
    <QueryClientProvider client={consultas}>
      <ContextoDaApi.Provider value={criarClienteDaApi(auth, () => {})}>
        <TooltipProvider>
          <AtalhosProvider>
            <Tela podeReprocessar={opcoes.podeReprocessar ?? true} podeEscolherEtapa={opcoes.podeEscolherEtapa ?? false} intervaloMs={30} />
          </AtalhosProvider>
        </TooltipProvider>
      </ContextoDaApi.Provider>
    </QueryClientProvider>,
  )
}

async function linhaDe(nome: string) {
  const tabela = await screen.findByRole('table', { name: 'Entradas' })
  return within(tabela).getByRole('row', { name: new RegExp(nome) })
}

const falhaDeEtapa = () =>
  job({
    id: 'f1',
    nome: 'falhou-na-tela.mp4',
    estado: 'falhou',
    codigo_falha: 'ocr_falhou',
    etapas: [{ nome: 'leitura_da_tela', inicio: '2026-10-29T15:01:00Z', fim: '2026-10-29T15:02:00Z', resultado: 'falhou' }],
  })

test('a tabela mostra vídeos de pessoas e de sistemas, e o filtro por sistema vai à API', async () => {
  jobs = [
    job({ id: 'a', nome: 'de-pessoa.mp4' }),
    job({ id: 'b', nome: 'de-sistema.mp4', enviado_por: { tipo: 'sistema', nome: 'sistema-x' } }),
  ]
  await abrir()
  await linhaDe('de-pessoa.mp4')
  expect(await linhaDe('de-sistema.mp4')).toBeTruthy()
  expect(consultas[0]).not.toContain('sistema=')
  cleanup()
  consultas.length = 0
  await abrir({ endereco: '/admin/entradas?por=sistema:sistema-x' })
  await linhaDe('de-sistema.mp4')
  expect(consultas[0]).toContain('sistema=sistema-x')
  expect(screen.queryByText('de-pessoa.mp4')).toBeNull()
})

test('a falha mostra a frase em português com o código na dica', async () => {
  jobs = [falhaDeEtapa()]
  await abrir()
  const linha = await linhaDe('falhou-na-tela.mp4')
  expect(within(linha).getByText(/Não foi possível ler os textos na tela/)).toBeTruthy()
})

test('a linha aberta lista as etapas com início, fim e duração; Enter também abre', async () => {
  jobs = [job({ etapas: [{ nome: 'transcricao', ...ETAPA_OK }] })]
  await abrir()
  const linha = await linhaDe('clipe.mp4')
  expect(screen.queryByRole('table', { name: 'Etapas de clipe.mp4' })).toBeNull()
  await userEvent.click(linha)
  const etapas = await screen.findByRole('table', { name: 'Etapas de clipe.mp4' })
  expect(within(etapas).getByText('Transcrição')).toBeTruthy()
  expect(within(etapas).getByText('02:05')).toBeTruthy()
  expect(within(etapas).getByText('Concluída')).toBeTruthy()
  linha.focus()
  await userEvent.keyboard('{Enter}')
  expect(screen.queryByRole('table', { name: 'Etapas de clipe.mp4' })).toBeNull()
})

test('Reprocessar só aparece na falha de etapa e no concluído com etapa que falhou', async () => {
  jobs = [
    falhaDeEtapa(),
    job({ id: 'q', nome: 'falha-do-arquivo.mp4', estado: 'falhou', codigo_falha: 'arquivo_corrompido' }),
    // Sem código, a API recusa o reprocessamento mesmo com uma etapa falha no registro.
    job({ id: 's', nome: 'falha-sem-codigo.mp4', estado: 'falhou', etapas: [{ nome: 'analise', inicio: ETAPA_OK.inicio, fim: ETAPA_OK.fim, resultado: 'falhou' }] }),
    job({ id: 'c1', nome: 'concluido-com-falha.mp4', etapas: [{ nome: 'indexacao', inicio: ETAPA_OK.inicio, fim: ETAPA_OK.fim, resultado: 'falhou' }] }),
    job({ id: 'c2', nome: 'concluido-limpo.mp4', etapas: [{ nome: 'indexacao', ...ETAPA_OK }] }),
  ]
  await abrir()
  const botao = (nome: string) => within(screen.getByRole('row', { name: new RegExp(nome) })).queryByRole('button', { name: /^Reprocessar / })
  await linhaDe('falhou-na-tela.mp4')
  expect(botao('falhou-na-tela.mp4')).toBeTruthy()
  expect(botao('concluido-com-falha.mp4')).toBeTruthy()
  expect(botao('falha-do-arquivo.mp4')).toBeNull()
  expect(botao('falha-sem-codigo.mp4')).toBeNull()
  expect(botao('concluido-limpo.mp4')).toBeNull()
  const arquivo = screen.getByRole('row', { name: /falha-do-arquivo.mp4/ })
  expect(within(arquivo).getByText('Envie o arquivo de novo')).toBeTruthy()
})

test('processamento interrompido entre etapas: retoma da primeira que não concluiu; na validação, pede o arquivo', async () => {
  const concluida = (nome: string) => ({ nome, ...ETAPA_OK })
  jobs = [
    job({
      id: 'i1',
      nome: 'interrompido-na-analise.mp4',
      estado: 'falhou',
      codigo_falha: 'processamento_interrompido',
      etapas: [concluida('validacao'), concluida('transcricao'), concluida('leitura_da_tela')],
    }),
    job({
      id: 'i2',
      nome: 'interrompido-na-validacao.mp4',
      estado: 'falhou',
      codigo_falha: 'processamento_interrompido',
      etapas: [{ nome: 'validacao', inicio: ETAPA_OK.inicio, fim: null, resultado: null }],
    }),
  ]
  await abrir()
  const retomavel = await linhaDe('interrompido-na-analise.mp4')
  // O interrompido não falhou: o botão diz "Retomar", e o pedido é o mesmo do reprocessar.
  expect(within(retomavel).getByRole('button', { name: 'Retomar interrompido-na-analise.mp4' })).toBeTruthy()
  expect(within(retomavel).queryByText('Envie o arquivo de novo')).toBeNull()
  await userEvent.click(within(retomavel).getByRole('button', { name: 'Retomar interrompido-na-analise.mp4' }))
  expect(screen.getByText('Reprocessar a partir da análise? As etapas já concluídas não são refeitas.')).toBeTruthy()
  cleanup()
  await abrir()
  const reenvio = await linhaDe('interrompido-na-validacao.mp4')
  expect(within(reenvio).getByText('Envie o arquivo de novo')).toBeTruthy()
  expect(within(reenvio).queryByRole('button', { name: /^(Reprocessar|Retomar) / })).toBeNull()
})

test('concluído entre duas etapas segue sendo consultado e só libera "Reprocessar…" quando a indexação termina', async () => {
  const agora = new Date().toISOString()
  jobs = [
    job({
      id: 'g1',
      nome: 'entre-etapas.mp4',
      criado_em: agora,
      atualizado_em: agora,
      etapa_atual: null,
      indexacao: { estado: 'pendente', em: agora },
      etapas: [{ nome: 'analise', inicio: agora, fim: agora, resultado: 'concluida' }],
    }),
  ]
  await abrir({ podeEscolherEtapa: true })
  const linha = await linhaDe('entre-etapas.mp4')
  expect(within(linha).queryByRole('button', { name: /a partir de uma etapa/ })).toBeNull()
  const antes = detalhes.length
  await waitFor(() => expect(detalhes.length).toBeGreaterThan(antes + 1))
  jobs = jobs.map((j) => ({
    ...j,
    indexacao: { estado: 'indexado', em: agora },
    etapas: [...(j.etapas ?? []), { nome: 'indexacao', inicio: agora, fim: agora, resultado: 'concluida' as const }],
  }))
  await waitFor(() => expect(within(screen.getByRole('row', { name: /entre-etapas.mp4/ })).getByRole('button', { name: /a partir de uma etapa/ })).toBeTruthy())
})

test('Reprocessar pede confirmação na linha, com a etapa de partida, e a linha passa a em andamento', async () => {
  jobs = [falhaDeEtapa()]
  await abrir()
  await linhaDe('falhou-na-tela.mp4')
  await userEvent.click(screen.getByRole('button', { name: 'Reprocessar falhou-na-tela.mp4' }))
  expect(screen.getByText('Reprocessar a partir da leitura da tela? As etapas já concluídas não são refeitas.')).toBeTruthy()
  expect(reprocessos).toEqual([])
  await userEvent.type(screen.getByLabelText('Motivo (opcional)'), 'Serviço voltou')
  await userEvent.click(screen.getAllByRole('button', { name: 'Reprocessar' }).at(-1)!)
  await waitFor(() => expect(reprocessos).toEqual([{ id: 'f1', corpo: { motivo: 'Serviço voltou' } }]))
  const linha = await linhaDe('falhou-na-tela.mp4')
  await waitFor(() => expect(within(linha).getByText('Leitura da tela')).toBeTruthy())
  expect(screen.queryByLabelText('Motivo (opcional)')).toBeNull()
  expect(within(linha).queryByText(/Não foi possível ler/)).toBeNull()
})

test('no vídeo concluído, o Reprocessar continua concluído e mostra a etapa em andamento', async () => {
  jobs = [job({ nome: 'c.mp4', etapas: [{ nome: 'quadros_chave', inicio: ETAPA_OK.inicio, fim: ETAPA_OK.fim, resultado: 'falhou' }] })]
  await abrir()
  await linhaDe('c.mp4')
  await userEvent.click(screen.getByRole('button', { name: 'Reprocessar c.mp4' }))
  expect(screen.getByText(/a partir dos quadros-chave\?/)).toBeTruthy()
  await userEvent.click(screen.getAllByRole('button', { name: 'Reprocessar' }).at(-1)!)
  await waitFor(() => expect(reprocessos).toEqual([{ id: 'j1', corpo: null }]))
  const linha = await linhaDe('c.mp4')
  await waitFor(() => expect(within(linha).getByText('Quadros-chave')).toBeTruthy())
  expect(within(linha).getByText('Concluído')).toBeTruthy()
})

test('"Reprocessar…" com etapa só aparece com a permissão, nas linhas concluídas, e exige o motivo', async () => {
  jobs = [job({ nome: 'c.mp4' }), job({ id: 'f', nome: 'f.mp4', estado: 'falhou', codigo_falha: 'arquivo_corrompido' })]
  await abrir({ podeEscolherEtapa: false })
  await linhaDe('c.mp4')
  expect(screen.queryByRole('button', { name: /a partir de uma etapa/ })).toBeNull()
  cleanup()

  await abrir({ podeEscolherEtapa: true })
  await linhaDe('c.mp4')
  expect(screen.getAllByRole('button', { name: /a partir de uma etapa/ })).toHaveLength(1)
  await userEvent.click(screen.getByRole('button', { name: 'Reprocessar c.mp4 a partir de uma etapa' }))
  const confirmar = screen.getAllByRole('button', { name: 'Reprocessar' }).at(-1)!
  expect((confirmar as HTMLButtonElement).disabled).toBe(true)
  await userEvent.click(screen.getByRole('radio', { name: /Quadros-chave/ }))
  await userEvent.type(screen.getByLabelText(/Motivo/), 'Quadros ruins')
  await userEvent.click(confirmar)
  await waitFor(() => expect(reprocessos).toEqual([{ id: 'j1', corpo: { etapa: 'quadros_chave', motivo: 'Quadros ruins' } }]))
  const linha = await linhaDe('c.mp4')
  await waitFor(() => expect(within(linha).getByText('Quadros-chave')).toBeTruthy())
})

test('atualiza só as linhas em andamento e para com a aba escondida', async () => {
  jobs = [
    job({ id: 'p', nome: 'pronto.mp4' }),
    job({ id: 'a', nome: 'andando.mp4', estado: 'analisando', etapa_atual: 'analise' }),
    job({ id: 'b', nome: 'outro.mp4', estado: 'validando', etapa_atual: 'validacao' }),
  ]
  await abrir()
  await linhaDe('andando.mp4')
  await waitFor(() => expect(pedidos.filter((p) => p.includes('a')).length).toBeGreaterThan(1))
  expect(detalhes).not.toContain('p')
  // Uma rodada, um pedido, mesmo com mais de um vídeo em andamento (sob carga, um pedido
  // atrasado do teste anterior pode cair aqui: só contam os deste).
  const deste = pedidos.filter((p) => p.includes('a') || p.includes('b'))
  expect(deste.length).toBeGreaterThan(0)
  expect(deste.every((p) => [...p].sort().join() === 'a,b')).toBe(true)
  Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
  await new Promise((r) => setTimeout(r, 80))
  const antes = detalhes.length
  await new Promise((r) => setTimeout(r, 120))
  expect(detalhes.length).toBe(antes)
})

test('a atualização do andamento, que vem sem capa, não apaga a capa da linha', async () => {
  jobs = [job({ id: 'a', nome: 'andando.mp4', estado: 'analisando', etapa_atual: 'analise', capa_url: '/capa-a.jpg' })]
  // Como a API: o GET /v1/jobs/andamento não traz capa_url.
  servidor.use(http.get('/v1/jobs/andamento', () => HttpResponse.json([{ ...jobs[0], etapa_atual: 'transcricao', capa_url: undefined }])))
  await abrir()
  const linha = await linhaDe('andando.mp4')
  expect(linha.querySelector('img')?.getAttribute('src')).toBe('/capa-a.jpg')
  await waitFor(() => expect(within(linha).getByText('Transcrição')).toBeTruthy())
  expect(linha.querySelector('img')?.getAttribute('src')).toBe('/capa-a.jpg')
})

test('a linha mostra a capa, o estado com ícone e a régua das etapas; o filtro de estado vai à API', async () => {
  jobs = [
    job({ capa_url: 'https://exemplo.invalid/capa.jpg', etapas: [{ nome: 'validacao', ...ETAPA_OK }, { nome: 'transcricao', inicio: ETAPA_OK.inicio, fim: ETAPA_OK.fim, resultado: 'falhou' }] }),
  ]
  await abrir()
  const linha = await linhaDe('clipe.mp4')
  expect(linha.querySelector('img')?.getAttribute('src')).toBe('https://exemplo.invalid/capa.jpg')
  expect(within(linha).getByText('Concluído')).toBeTruthy()
  const regua = within(linha).getByRole('img', { name: /^Etapas:/ }).getAttribute('aria-label')
  expect(regua).toContain('Validação: 02:05, concluída')
  expect(regua).toContain('Transcrição: 02:05, falhou')
  expect(regua).toContain('Indexação: ainda não rodou')
  await userEvent.click(within(screen.getByRole('group', { name: 'Estado' })).getByRole('button', { name: 'Falhou' }))
  await waitFor(() => expect(consultas.at(-1)).toContain('estado=falhou'))
  expect(location.search).toBe('?estado=falhou')
})
