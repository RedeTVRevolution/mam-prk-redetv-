import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { render } from './render-teste.tsx'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import App from './App.tsx'
import { ContaBloqueada } from './auth/autenticador.ts'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'

const chamadas: { url: string; autorizacao: string | null }[] = []

// API simulada: só reconhece o token que o autenticador falso emite para a Ana.
const servidor = setupServer(
  http.get('/v1/eu', ({ request }) => {
    const autorizacao = request.headers.get('Authorization')
    chamadas.push({ url: request.url, autorizacao })
    if (autorizacao !== 'Bearer token-de-ana@redetv.com.br') {
      return new HttpResponse(null, { status: 401 })
    }
    return HttpResponse.json({
      uid: 'u1',
      email: 'ana@redetv.com.br',
      papeis: ['consulta', 'operador'],
      permissoes: ['decupagem.ver', 'video.enviar'],
    })
  }),
  http.get('/v1/jobs', () => HttpResponse.json([])),
  http.get('/v1/programas', () => HttpResponse.json([])),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  history.replaceState(null, '', '/')
  servidor.resetHandlers()
  chamadas.length = 0
  cleanup()
})
afterAll(() => servidor.close())

function autenticador(totpCadastrado = true) {
  return new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado },
  ])
}

async function preencherSenha(
  usuario: ReturnType<typeof userEvent.setup>,
  senha = 'senha-forte-1',
) {
  await usuario.type(screen.getByLabelText(/^E-mail/), 'ana@redetv.com.br')
  await usuario.type(screen.getByLabelText(/^Senha/), senha)
  await usuario.click(screen.getByRole('button', { name: 'Entrar' }))
}

async function digitarCodigo(usuario: ReturnType<typeof userEvent.setup>, codigo: string) {
  const grupo = await screen.findByLabelText('Código do autenticador')
  const campos = within(grupo).getAllByRole('textbox')
  expect(campos).toHaveLength(6)
  await usuario.type(campos[0], codigo)
}

async function confirmarCodigo(usuario: ReturnType<typeof userEvent.setup>) {
  await digitarCodigo(usuario, CODIGO_TOTP_FALSO)
  await usuario.click(screen.getByRole('button', { name: 'Confirmar' }))
}

async function autenticadorComSessao() {
  const auth = autenticador()
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  return auth
}

test('sem sessão, mostra só o login e não chama a API', async () => {
  render(<App autenticador={autenticador()} />)

  expect(await screen.findByLabelText(/^E-mail/)).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Sair' })).toBeNull()
  expect(screen.queryByText('Nenhum vídeo enviado ainda.')).toBeNull()
  expect(chamadas).toEqual([])
})

test('login com senha e código TOTP abre o Acervo com o token na API', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)

  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)
  expect(screen.queryByText('Nenhum vídeo enviado ainda.')).toBeNull()
  await confirmarCodigo(usuario)

  expect(await screen.findByText('Nenhum vídeo enviado ainda.')).toBeTruthy()
  expect(screen.getByText('ana@redetv.com.br')).toBeTruthy()
  expect(chamadas.at(-1)?.autorizacao).toBe('Bearer token-de-ana@redetv.com.br')
})

test('senha errada mostra erro e continua no login', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)
  await screen.findByLabelText(/^E-mail/)

  await preencherSenha(usuario, 'errada')

  expect((await screen.findByRole('alert')).textContent).toContain('inválid')
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('conta bloqueada por tentativas erradas pede para esperar', async () => {
  const usuario = userEvent.setup()
  const auth = autenticador()
  auth.entrar = async () => {
    throw new ContaBloqueada()
  }
  render(<App autenticador={auth} />)
  await screen.findByLabelText(/^E-mail/)

  await preencherSenha(usuario)

  expect((await screen.findByRole('alert')).textContent).toContain('Muitas tentativas')
})

test('falha inesperada no login mostra login indisponível', async () => {
  const usuario = userEvent.setup()
  const auth = autenticador()
  auth.entrar = async () => {
    throw new Error('rede fora')
  }
  render(<App autenticador={auth} />)
  await screen.findByLabelText(/^E-mail/)

  await preencherSenha(usuario)

  expect((await screen.findByRole('alert')).textContent).toContain('Login indisponível')
})

test('código incompleto não pode ser confirmado', async () => {
  const usuario = userEvent.setup()
  const auth = autenticador()
  let tentativas = 0
  auth.confirmarTotp = async () => {
    tentativas++
  }
  render(<App autenticador={auth} />)
  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)

  await digitarCodigo(usuario, '123')

  const confirmar = screen.getByRole('button', { name: 'Confirmar' })
  expect(confirmar.hasAttribute('disabled')).toBe(true)
  await usuario.click(confirmar)
  expect(tentativas).toBe(0)
})

test('código TOTP errado mostra erro e não entra', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)
  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)

  await digitarCodigo(usuario, '000000')
  await usuario.click(screen.getByRole('button', { name: 'Confirmar' }))

  expect((await screen.findByRole('alert')).textContent).toContain('inválid')
  expect(screen.queryByText('Nenhum vídeo enviado ainda.')).toBeNull()
})

test('primeiro acesso mostra o cadastro do autenticador e entra ao confirmar o código', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador(false)} />)
  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)

  expect(await screen.findByText('SEGREDOFALSO')).toBeTruthy()
  expect(
    screen.getByRole('link', { name: 'Abrir no aplicativo autenticador' }).getAttribute('href'),
  ).toBe('otpauth://totp/MAM')
  await confirmarCodigo(usuario)

  expect(await screen.findByText('Nenhum vídeo enviado ainda.')).toBeTruthy()
})

test('fechar o modal do autenticador volta ao início do login', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)
  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)
  await screen.findByRole('dialog', { name: 'Verificação em duas etapas' })

  await usuario.click(screen.getByRole('button', { name: 'Fechar' }))

  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect((screen.getByLabelText(/^E-mail/) as HTMLInputElement).value).toBe('')
  expect((screen.getByLabelText(/^Senha/) as HTMLInputElement).value).toBe('')
})

test('o botão sair volta ao login e apaga a sessão', async () => {
  const usuario = userEvent.setup()
  const auth = autenticador()
  render(<App autenticador={auth} />)
  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)
  await confirmarCodigo(usuario)
  await usuario.click(await screen.findByRole('button', { name: /^Conta:/ }))
  await usuario.click(await screen.findByRole('menuitem', { name: 'Sair' }))

  expect(await screen.findByLabelText(/^E-mail/)).toBeTruthy()
  expect(screen.queryByText('Nenhum vídeo enviado ainda.')).toBeNull()
  expect(await auth.token()).toBeNull()
})

test('sessão já existente abre direto no Acervo', async () => {
  const auth = await autenticadorComSessao()
  render(<App autenticador={auth} />)

  expect(await screen.findByText('Nenhum vídeo enviado ainda.')).toBeTruthy()
})

test('401 da API derruba a sessão e leva ao login', async () => {
  const auth = await autenticadorComSessao()
  servidor.use(http.get('/v1/eu', () => new HttpResponse(null, { status: 401 })))
  render(<App autenticador={auth} />)

  expect(await screen.findByLabelText(/^E-mail/)).toBeTruthy()
  await waitFor(async () => expect(await auth.token()).toBeNull())
  expect(screen.queryByText('Nenhum vídeo enviado ainda.')).toBeNull()
})

test('várias chamadas com 401 ao mesmo tempo derrubam a sessão uma vez só', async () => {
  const usuario = userEvent.setup()
  const auth = await autenticadorComSessao()
  const sair = vi.spyOn(auth, 'sair')
  servidor.use(
    http.get('/v1/jobs', () =>
      HttpResponse.json([
        {
          id: 'j1',
          nome: 'pronto.mp4',
          estado: 'concluido',
          codigo_falha: null,
          duracao_s: null,
          programa: null,
          criado_em: '2026-10-29T15:00:00Z',
          atualizado_em: '2026-10-29T15:00:00Z',
        },
      ]),
    ),
    http.get('/v1/jobs/j1', () =>
      HttpResponse.json({
        id: 'j1',
        nome: 'pronto.mp4',
        estado: 'concluido',
        codigo_falha: null,
        duracao_s: null,
        programa: null,
        criado_em: '2026-10-29T15:00:00Z',
        atualizado_em: '2026-10-29T15:00:00Z',
      }),
    ),
    // A tela do vídeo pede reprodução, decupagem e catálogo juntos.
    http.get('/v1/jobs/j1/*', () => new HttpResponse(null, { status: 401 })),
    http.get('/v1/correcoes/catalogo', () => new HttpResponse(null, { status: 401 })),
  )
  render(<App autenticador={auth} />)
  await usuario.click(await screen.findByRole('link', { name: 'pronto.mp4' }))

  expect(await screen.findByLabelText(/^E-mail/)).toBeTruthy()
  expect(sair).toHaveBeenCalledTimes(1)
})

test('API recusando o token logo depois do login volta ao início do login', async () => {
  servidor.use(http.get('/v1/eu', () => new HttpResponse(null, { status: 401 })))
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)
  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)
  await confirmarCodigo(usuario)

  expect(await screen.findByLabelText(/^E-mail/)).toBeTruthy()
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('API fora do ar mostra aviso sem dados, e tentar de novo entra', async () => {
  const usuario = userEvent.setup()
  const auth = await autenticadorComSessao()
  servidor.use(http.get('/v1/eu', () => new HttpResponse(null, { status: 500 })))
  render(<App autenticador={auth} />)

  expect((await screen.findByRole('alert')).textContent).toContain('API')
  expect(screen.queryByText('Nenhum vídeo enviado ainda.')).toBeNull()

  servidor.resetHandlers()
  await usuario.click(screen.getByRole('button', { name: 'Tentar de novo' }))
  expect(await screen.findByText('Nenhum vídeo enviado ainda.')).toBeTruthy()
})

test('com sessão, a barra mostra a marca, o link do acervo e a conta com o menu', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={await autenticadorComSessao()} />)

  expect(await screen.findByText('MAM')).toBeTruthy()
  expect(screen.getByText('RedeTV')).toBeTruthy()
  const barra = screen.getByRole('banner')
  expect(within(barra).getByRole('link', { name: 'Acervo' }).getAttribute('href')).toBe('/acervo')
  expect(barra.textContent).toContain('ana@redetv.com.br')
  expect(screen.queryByRole('menuitem', { name: 'Sair' })).toBeNull()
  await usuario.click(within(barra).getByRole('button', { name: /^Conta:/ }))
  expect(await screen.findByRole('menuitem', { name: 'Sair' })).toBeTruthy()
  expect(screen.getByRole('menuitem', { name: 'Atalhos (?)' })).toBeTruthy()
})

test('verificando a sessão mostra um indicador de carregamento', async () => {
  render(<App autenticador={await autenticadorComSessao()} />)

  expect(screen.getByRole('status', { name: 'Verificando a sessão' })).toBeTruthy()
  await screen.findByText('Nenhum vídeo enviado ainda.')
})

test('quem só tem Consulta não vê o upload no Acervo', async () => {
  servidor.use(
    http.get('/v1/eu', () =>
      HttpResponse.json({
        uid: 'u1',
        email: 'ana@redetv.com.br',
        papeis: ['consulta'],
        permissoes: ['decupagem.ver'],
      }),
    ),
  )
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)
  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)
  await confirmarCodigo(usuario)

  await screen.findByText('Nenhum vídeo enviado ainda.')
  expect(screen.queryByRole('button', { name: 'Enviar vídeo' })).toBeNull()
})

test('quem tem video.enviar vê o upload no Acervo', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)
  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)
  await confirmarCodigo(usuario)

  expect(await screen.findByRole('button', { name: 'Enviar vídeo' })).toBeTruthy()
})


const VIDEO_J1 = {
  id: 'j1',
  nome: 'pronto.mp4',
  estado: 'concluido',
  codigo_falha: null,
  duracao_s: null,
  programa: null,
  criado_em: '2026-10-29T15:00:00Z',
  atualizado_em: '2026-10-29T15:00:00Z',
}

test('a raiz redireciona para o acervo', async () => {
  render(<App autenticador={await autenticadorComSessao()} />)

  await screen.findByText('Nenhum vídeo enviado ainda.')
  expect(location.pathname).toBe('/acervo')
})

test('abrir /video/{id}?t= com sessão abre o Visualizador e posiciona o player no instante', async () => {
  history.replaceState(null, '', '/video/j1?t=724')
  servidor.use(
    http.get('/v1/jobs/j1', () => HttpResponse.json(VIDEO_J1)),
    http.get('/v1/jobs/j1/reproducao', () =>
      HttpResponse.json({ url: 'https://exemplo.test/v.mp4', expira_em: '2999-01-01T00:00:00Z' }),
    ),
  )
  const { container } = render(<App autenticador={await autenticadorComSessao()} />)

  const player = (await screen.findByLabelText('Player')) as HTMLVideoElement
  fireEvent.loadedMetadata(player)
  expect(player.currentTime).toBe(724)
  expect(location.pathname).toBe('/video/j1')
  expect(container.textContent).not.toContain('Página não encontrada')
  expect(screen.queryByText('Nenhum vídeo enviado ainda.')).toBeNull()
})

test('a tela antiga abre em /video/{id}/anterior', async () => {
  history.replaceState(null, '', '/video/j1/anterior')
  servidor.use(
    http.get('/v1/jobs/j1', () => HttpResponse.json(VIDEO_J1)),
    http.get('/v1/jobs/j1/*', () => new HttpResponse(null, { status: 500 })),
    http.get('/v1/correcoes/catalogo', () => new HttpResponse(null, { status: 500 })),
  )
  render(<App autenticador={await autenticadorComSessao()} />)

  await waitFor(() => expect(screen.queryByRole('status')).toBeNull())
  expect(location.pathname).toBe('/video/j1/anterior')
  expect(screen.queryByText('Página não encontrada.')).toBeNull()
  expect(screen.queryByRole('link', { name: 'Tela anterior' })).toBeNull()
})

test('vídeo inexistente mostra o aviso e o link para o acervo', async () => {
  history.replaceState(null, '', '/video/x')
  servidor.use(
    http.get('/v1/jobs/x', () => HttpResponse.json({ detail: 'Job não encontrado' }, { status: 404 })),
  )
  render(<App autenticador={await autenticadorComSessao()} />)

  expect((await screen.findByRole('alert')).textContent).toContain('Vídeo não encontrado')
  expect(screen.getAllByRole('link', { name: 'Voltar ao acervo' })[0].getAttribute('href')).toBe(
    '/acervo',
  )
})

test('sem sessão, /video/x leva ao login e, depois dele, ao vídeo', async () => {
  history.replaceState(null, '', '/video/x')
  servidor.use(
    http.get('/v1/jobs/x', () => HttpResponse.json({ ...VIDEO_J1, id: 'x', estado: 'falhou' })),
  )
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)
  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)
  await confirmarCodigo(usuario)

  await waitFor(() => expect(screen.queryByLabelText(/^E-mail/)).toBeNull())
  expect(location.pathname).toBe('/video/x')
  expect(screen.queryByText('Nenhum vídeo enviado ainda.')).toBeNull()
})

test('endereço desconhecido mostra "Página não encontrada" com link para o acervo', async () => {
  history.replaceState(null, '', '/nada/aqui')
  render(<App autenticador={await autenticadorComSessao()} />)

  expect(await screen.findByText('Página não encontrada.')).toBeTruthy()
  expect(screen.getByRole('link', { name: 'Ir ao acervo' }).getAttribute('href')).toBe('/acervo')
})

test('/amostra abre a página de amostra sem login e sem chamar a API', async () => {
  history.replaceState(null, '', '/amostra')
  render(<App autenticador={autenticador()} />)

  expect(await screen.findByRole('heading', { name: /Sistema visual/i }, { timeout: 5000 })).toBeTruthy()
  expect(screen.queryByLabelText(/^E-mail/)).toBeNull()
  expect(chamadas).toEqual([])
})

test('/amostra com sessão também abre sem chamar a API', async () => {
  history.replaceState(null, '', '/amostra')
  render(<App autenticador={await autenticadorComSessao()} />)

  expect(await screen.findByRole('heading', { name: /Sistema visual/i }, { timeout: 5000 })).toBeTruthy()
  expect(chamadas).toEqual([])
})

test('clicar no link do endereço atual não empilha outra entrada no histórico', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={await autenticadorComSessao()} />)
  await screen.findByText('Nenhum vídeo enviado ainda.')
  const antes = history.length

  await usuario.click(within(screen.getByRole('banner')).getByRole('link', { name: 'Acervo' }))

  expect(location.pathname).toBe('/acervo')
  expect(history.length).toBe(antes)
})

test('Ctrl+clique no cartão fica com o navegador (outra aba) e não muda a tela', async () => {
  servidor.use(http.get('/v1/jobs', () => HttpResponse.json([VIDEO_J1])))
  render(<App autenticador={await autenticadorComSessao()} />)
  const link = await screen.findByRole('link', { name: 'pronto.mp4' })

  const seguiu = fireEvent.click(link, { button: 0, ctrlKey: true })

  // O app não cancelou o clique: quem decide é o navegador.
  expect(seguiu).toBe(true)
  expect(location.pathname).toBe('/acervo')
})

test('na tela anterior do vídeo, ? lista também as teclas da linha do tempo', async () => {
  history.replaceState(null, '', '/video/j1/anterior')
  servidor.use(
    http.get('/v1/jobs/j1', () => HttpResponse.json(VIDEO_J1)),
    http.get('/v1/jobs/j1/*', () => new HttpResponse(null, { status: 500 })),
    http.get('/v1/correcoes/catalogo', () => new HttpResponse(null, { status: 500 })),
  )
  const usuario = userEvent.setup()
  render(<App autenticador={await autenticadorComSessao()} />)
  await waitFor(() => expect(screen.queryByRole('status')).toBeNull())

  await usuario.keyboard('?')

  const dialogo = await screen.findByRole('dialog', { name: 'Atalhos' })
  expect(within(dialogo).getByRole('table', { name: 'Linha do tempo' })).toBeTruthy()
  expect(within(dialogo).getByText('Na faixa: ir à ocorrência em foco')).toBeTruthy()
})

test('falha ao abrir o vídeo mostra o código para o suporte e tenta de novo', async () => {
  history.replaceState(null, '', '/video/j1')
  let falhar = true
  servidor.use(
    http.get('/v1/jobs/j1', () =>
      falhar ? new HttpResponse(null, { status: 503 }) : HttpResponse.json(VIDEO_J1),
    ),
    http.get('/v1/jobs/j1/*', () => new HttpResponse(null, { status: 500 })),
    http.get('/v1/correcoes/catalogo', () => new HttpResponse(null, { status: 500 })),
  )
  const usuario = userEvent.setup()
  render(<App autenticador={await autenticadorComSessao()} />)

  const aviso = await screen.findByRole('alert')
  expect(aviso.textContent).toContain('Não foi possível abrir o vídeo')
  expect(aviso.textContent).toContain('Código para o suporte: http_503')
  falhar = false
  await usuario.click(within(aviso).getByRole('button', { name: 'Tentar de novo' }))

  await waitFor(() =>
    expect(screen.queryByText(/Código para o suporte: http_503/)).toBeNull(),
  )
})

test('voltar no navegador volta ao acervo', async () => {
  const usuario = userEvent.setup()
  servidor.use(
    http.get('/v1/jobs', () => HttpResponse.json([VIDEO_J1])),
    http.get('/v1/jobs/j1', () => HttpResponse.json(VIDEO_J1)),
    http.get('/v1/jobs/j1/*', () => new HttpResponse(null, { status: 500 })),
    http.get('/v1/correcoes/catalogo', () => new HttpResponse(null, { status: 500 })),
  )
  render(<App autenticador={await autenticadorComSessao()} />)
  await usuario.click(await screen.findByRole('link', { name: 'pronto.mp4' }))
  await waitFor(() => expect(location.pathname).toBe('/video/j1'))

  history.back()

  expect(await screen.findByRole('link', { name: 'pronto.mp4' })).toBeTruthy()
  expect(location.pathname).toBe('/acervo')
})

test('? abre os atalhos da tela, e com o foco num campo de texto vira texto', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={await autenticadorComSessao()} />)
  await screen.findByRole('button', { name: 'Enviar vídeo' })
  const campo = document.createElement('input')
  document.body.append(campo)

  campo.focus()
  await usuario.keyboard('?')
  expect(campo.value).toBe('?')
  expect(screen.queryByRole('dialog')).toBeNull()
  campo.remove()

  await usuario.keyboard('?')
  const dialogo = await screen.findByRole('dialog', { name: 'Atalhos' })
  expect(within(dialogo).getByRole('table', { name: 'Geral' })).toBeTruthy()
  expect(within(dialogo).getByText('Fechar o que estiver aberto')).toBeTruthy()

  await usuario.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})
