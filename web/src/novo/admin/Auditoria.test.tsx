import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from '../../auth/falso.ts'
import App from '../App.tsx'
import { comAlturaNaRolagem } from './teste.ts'

interface Registro {
  id: string
  quando: string
  uid?: string | null
  email?: string | null
  sistema?: string | null
  acao: string
  alvo_tipo: string
  alvo_id: string
  alvo_nome: string
  motivo: string | null
  detalhes: Record<string, unknown>
}

const registros = (): Registro[] => [
  {
    id: 'r1',
    quando: '2026-10-28T17:02:00Z',
    uid: 'u1',
    email: 'ana@redetv.com.br',
    acao: 'item.para_lixeira',
    alvo_tipo: 'video',
    alvo_id: 'j1',
    alvo_nome: 'TV Fama 21/10/2026.mp4',
    motivo: 'duplicado',
    detalhes: { decupagem: 1, correcoes: 37, arquivos: { copia_limpa: 1, proxy: 1, quadros: 1240 }, outros_jobs: [] },
  },
  {
    id: 'r2',
    quando: '2026-10-27T12:40:00Z',
    uid: 'u1',
    email: 'ana@redetv.com.br',
    acao: 'papeis.alterados',
    alvo_tipo: 'conta',
    alvo_id: 'u2',
    alvo_nome: 'rui@redetv.com.br',
    motivo: null,
    detalhes: { antes: ['consulta'], depois: ['consulta', 'editor'] },
  },
  {
    id: 'r3',
    quando: '2026-10-26T09:00:00Z',
    sistema: 'sistema-x',
    acao: 'video.reprocessado',
    alvo_tipo: 'video',
    alvo_id: 'j9',
    alvo_nome: 'outro.mp4',
    motivo: null,
    detalhes: { etapa: 'leitura_da_tela' },
  },
]

const ADMIN = { uid: 'u1', email: 'ana@redetv.com.br', papeis: ['administrador'], permissoes: ['decupagem.ver', 'auditoria.ver'] }

let lista = registros()
let escrita = false
const consultas: URLSearchParams[] = []

const servidor = setupServer(
  http.get('/v1/eu', () => HttpResponse.json(ADMIN)),
  http.get('/v1/admin/auditoria', ({ request }) => {
    const url = new URL(request.url)
    consultas.push(url.searchParams)
    const cursor = url.searchParams.get('cursor')
    const limite = Number(url.searchParams.get('limite') ?? 50)
    const inicio = cursor ? lista.findIndex((r) => r.id === cursor) + 1 : 0
    const pagina = lista.slice(inicio, inicio + limite)
    const ultimo = pagina.at(-1)
    const mais = inicio + limite < lista.length && ultimo
    return HttpResponse.json(pagina, mais ? { headers: { 'X-Proximo-Cursor': ultimo.id } } : {})
  }),
  http.all('/v1/admin/auditoria/*', () => {
    escrita = true
    return new HttpResponse(null, { status: 405 })
  }),
)

comAlturaNaRolagem()
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  history.replaceState(null, '', '/')
  servidor.resetHandlers()
  lista = registros()
  consultas.length = 0
  escrita = false
  cleanup()
})
afterAll(() => servidor.close())

async function abrir(endereco = '/admin/auditoria') {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', endereco)
  render(<App autenticador={auth} />)
}

/** O texto da opção escolhida num campo de escolha nativo. */
function escolhida(nome: string) {
  return (screen.getByRole('combobox', { name: nome }) as HTMLSelectElement).selectedOptions[0]?.textContent
}

async function linhaDe(nome: string) {
  const tabela = await screen.findByRole('table', { name: 'Auditoria' })
  return within(tabela).getByRole('row', { name: new RegExp(nome.replace('.', '\\.')) })
}

test('a tabela mostra quando, quem, ação em frase, alvo e motivo', async () => {
  await abrir()
  const v = await linhaDe('TV Fama')
  expect(within(v).getByText('ana@redetv.com.br')).toBeTruthy()
  expect(within(v).getByText('Mandou para a lixeira')).toBeTruthy()
  expect(within(v).getByText('duplicado')).toBeTruthy()
  expect(within(v).getByText(/28\/10\/2026/)).toBeTruthy()
  expect(within(await linhaDe('outro.mp4')).getByText('sistema-x')).toBeTruthy()
  expect(screen.getByRole('link', { name: 'Auditoria' }).getAttribute('href')).toBe('/admin/auditoria')
})

test('a linha aberta mostra o antes e o depois dos papéis, o impacto e a etapa', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await usuario.click(await linhaDe('rui@redetv'))
  expect(await screen.findByText('Antes: Consulta')).toBeTruthy()
  expect(screen.getByText('Depois: Consulta, Editor')).toBeTruthy()
  await usuario.click(await linhaDe('TV Fama'))
  expect(await screen.findByText(/37 correções/)).toBeTruthy()
  expect(screen.getByText(/1\.240 quadros-chave/)).toBeTruthy()
  await usuario.click(await linhaDe('outro.mp4'))
  expect(await screen.findByText('A partir da etapa Leitura da tela')).toBeTruthy()
})

test('os filtros vão para a API e para a URL', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await linhaDe('TV Fama')
  await usuario.type(screen.getByRole('textbox', { name: 'Pessoa' }), 'rui@redetv.com.br')
  await usuario.type(screen.getByRole('textbox', { name: 'Alvo' }), 'j1')
  await usuario.selectOptions(screen.getByRole('combobox', { name: 'Ação' }), 'Revogou a chave')
  await waitFor(() => expect(location.search).toContain('acao=chave.revogada'))
  expect(location.search).toContain('pessoa=rui%40redetv.com.br')
  expect(location.search).toContain('alvo=j1')
  await waitFor(() => {
    const ultima = consultas.at(-1)!
    expect(ultima.get('pessoa')).toBe('rui@redetv.com.br')
    expect(ultima.get('alvo')).toBe('j1')
    expect(ultima.get('acao')).toBe('chave.revogada')
  })
})

test('o filtro de ação agrupa os acessos e manda as três ações à API', async () => {
  const usuario = userEvent.setup()
  await abrir('/admin/auditoria?alvo=j1&acao=video.aberto,video.baixado,decupagem.baixada')
  await linhaDe('TV Fama')
  await waitFor(() => expect(consultas.at(-1)!.getAll('acao')).toEqual(['video.aberto', 'video.baixado', 'decupagem.baixada']))
  expect(escolhida('Ação')).toBe('Todos os acessos')

  const grupo = screen.getByRole('group', { name: 'Acessos' })
  expect(within(grupo).getAllByRole('option').map((o) => o.textContent)).toEqual(['Todos os acessos', 'Abriu o vídeo', 'Baixou o vídeo', 'Baixou a decupagem'])
  await usuario.selectOptions(screen.getByRole('combobox', { name: 'Ação' }), 'Baixou o vídeo')
  await waitFor(() => expect(consultas.at(-1)!.getAll('acao')).toEqual(['video.baixado']))
})

test('os acessos em outra ordem na URL ainda aparecem no campo Ação; duas ações soltas saem do filtro', async () => {
  await abrir('/admin/auditoria?alvo=j1&acao=decupagem.baixada,video.aberto,video.baixado,video.aberto')
  await linhaDe('TV Fama')
  expect(escolhida('Ação')).toBe('Todos os acessos')
  expect(consultas.at(-1)!.getAll('acao')).toHaveLength(3)

  cleanup()
  consultas.length = 0
  await abrir('/admin/auditoria?alvo=j1&acao=video.aberto,video.baixado')
  await linhaDe('TV Fama')
  expect(consultas.at(-1)!.getAll('acao')).toEqual([])
  expect(escolhida('Ação')).toBe('Todas as ações')
})

test('o período vai à API como dia inteiro de São Paulo', async () => {
  await abrir('/admin/auditoria?de=2026-10-27&ate=2026-10-28')
  await linhaDe('TV Fama')
  const q = consultas[0]!
  expect(q.get('de')).toBe('2026-10-27T00:00:00-03:00')
  expect(q.get('ate')).toBe('2026-10-28T23:59:59.999-03:00')
  expect((screen.getByLabelText('De') as HTMLInputElement).value).toBe('2026-10-27')
})

test('"Carregar mais" traz a página seguinte com o cursor', async () => {
  const usuario = userEvent.setup()
  lista = Array.from({ length: 60 }, (_, i) => ({ ...registros()[0]!, id: `r${i}`, alvo_nome: `video-${i}.mp4` }))
  await abrir()
  await linhaDe('video-0.mp4')
  await usuario.click(screen.getByRole('button', { name: 'Carregar mais' }))
  expect(await linhaDe('video-59.mp4')).toBeTruthy()
  expect(consultas.at(-1)!.get('cursor')).toBe('r49')
  expect(screen.queryByRole('button', { name: 'Carregar mais' })).toBeNull()
})

test('a lista longa desenha só as linhas à vista e guarda todas as páginas, também ao voltar à aba', async () => {
  const usuario = userEvent.setup()
  servidor.use(http.get('/v1/eu', () => HttpResponse.json({ ...ADMIN, permissoes: [...ADMIN.permissoes, 'chaves.gerir'] })), http.get('/v1/admin/chaves', () => HttpResponse.json([])))
  lista = Array.from({ length: 400 }, (_, i) => ({ ...registros()[0]!, id: `r${i}`, alvo_nome: `video-${i}.mp4` }))
  await abrir()
  await linhaDe('video-0.mp4')
  for (let n = 2; n <= 7; n++) {
    await usuario.click(screen.getByRole('button', { name: 'Carregar mais' }))
    await waitFor(() => expect(consultas).toHaveLength(n))
  }
  // Sete páginas pedidas, sete na memória: a lista é virtual, então o DOM continua pequeno.
  let tabela = await screen.findByRole('table', { name: 'Auditoria' })
  expect(within(tabela).getAllByRole('row')[1]!.textContent).toContain('video-0.mp4')
  expect(within(tabela).getAllByRole('row').length).toBeLessThan(100)
  expect(screen.queryByRole('button', { name: 'Carregar anteriores' })).toBeNull()
  // Sair e voltar com o cache vivo: o começo continua lá.
  await usuario.click(screen.getByRole('link', { name: 'Sistemas e chaves' }))
  await usuario.click(await screen.findByRole('link', { name: 'Auditoria' }))
  tabela = await screen.findByRole('table', { name: 'Auditoria' })
  await waitFor(() => expect(within(tabela).getAllByRole('row')[1]!.textContent).toContain('video-0.mp4'))
  expect(screen.queryByRole('button', { name: 'Carregar anteriores' })).toBeNull()
})

test('a aba é só de leitura: nenhum botão de editar ou apagar', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await usuario.click(await linhaDe('TV Fama'))
  const tabela = screen.getByRole('table', { name: 'Auditoria' })
  expect(within(tabela).queryAllByRole('button')).toEqual([])
  expect(screen.queryByRole('button', { name: /editar|apagar|excluir|remover/i })).toBeNull()
  expect(escrita).toBe(false)
})

test('sem registro, diz que não há', async () => {
  lista = []
  await abrir()
  expect(await screen.findByText('Nenhum registro ainda.')).toBeTruthy()
})

test('com filtro e sem resultado, diz que nenhum registro casa', async () => {
  lista = []
  await abrir('/admin/auditoria?alvo=j1')
  expect(await screen.findByText('Nenhum registro com esses filtros.')).toBeTruthy()
})

test('a correção de estado mostra o estado pelo nome, e o impacto conta os outros envios', async () => {
  const usuario = userEvent.setup()
  lista = [
    { ...registros()[0]!, detalhes: { ...registros()[0]!.detalhes, outros_jobs: [{ id: 'j2', nome: 'copia.mp4', enviado_por: 'rui' }] } },
    { ...registros()[2]!, id: 'r4', acao: 'job.estado_corrigido', alvo_nome: 'preso.mp4', detalhes: { de: 'analisando', para: 'falhou' } },
  ]
  await abrir()
  await usuario.click(await linhaDe('preso.mp4'))
  expect(await screen.findByText('Estado: de Decupando para Falhou')).toBeTruthy()
  await usuario.click(await linhaDe('TV Fama'))
  expect(await screen.findByText('1 outro envio tinha o mesmo conteúdo.')).toBeTruthy()
})

test('com "De" depois de "Até", avisa e não consulta a API', async () => {
  await abrir('/admin/auditoria?de=2026-10-28&ate=2026-10-27')
  expect(await screen.findByText(/"De" é depois da data em "Até"/)).toBeTruthy()
  expect(consultas).toEqual([])
})
