import { IconArrowLeft, IconExternalLink, IconEye, IconEyeOff, IconLock, IconMail, IconShieldLock } from '@tabler/icons-react'
import { useState, type ReactNode, type SubmitEvent } from 'react'
import logo from '../assets/redetv-logo.png'
import {
  ContaBloqueada,
  CredencialInvalida,
  type Autenticador,
  type ResultadoDaSenha,
} from '../auth/autenticador.ts'
import { Button } from './ui/button.tsx'

type Etapa = Exclude<ResultadoDaSenha, { tipo: 'logado' }> | { tipo: 'senha' }

const DIGITOS_DO_CODIGO = 6

// As mesmas mensagens do Login.tsx da interface antiga.
function mensagemDeErro(falha: unknown) {
  return falha instanceof CredencialInvalida
    ? 'Credenciais inválidas. Confira os dados e tente de novo.'
    : falha instanceof ContaBloqueada
      ? 'Muitas tentativas erradas. Espere alguns minutos e tente de novo.'
      : 'Login indisponível no momento.'
}

function Campo({ rotulo, icone, children }: { rotulo: string; icone: ReactNode; children: ReactNode }) {
  return (
    <label className="grid gap-1 text-xs font-medium">
      {rotulo}
      <span className="flex h-10 items-center gap-2 rounded-sm border border-strong bg-input px-3 focus-within:border-primary">
        {icone}
        {children}
      </span>
    </label>
  )
}

/** Login: e-mail e senha, depois o código do autenticador; no primeiro acesso, o cadastro dele. */
export default function Login({ autenticador, aoEntrar }: { autenticador: Autenticador; aoEntrar: () => void }) {
  const [etapa, setEtapa] = useState<Etapa>({ tipo: 'senha' })
  const [erro, setErro] = useState<string | null>(null)
  const [codigo, setCodigo] = useState('')
  const [verSenha, setVerSenha] = useState(false)

  function voltarAoInicio() {
    setEtapa({ tipo: 'senha' })
    setCodigo('')
    setErro(null)
  }

  async function enviarSenha(evento: SubmitEvent<HTMLFormElement>) {
    evento.preventDefault()
    const dados = new FormData(evento.currentTarget)
    setErro(null)
    try {
      const resultado = await autenticador.entrar(String(dados.get('email')), String(dados.get('senha')))
      if (resultado.tipo === 'logado') aoEntrar()
      else setEtapa(resultado)
    } catch (falha) {
      setErro(mensagemDeErro(falha))
    }
  }

  async function enviarCodigo(evento: SubmitEvent<HTMLFormElement>) {
    evento.preventDefault()
    if (etapa.tipo === 'senha' || codigo.length < DIGITOS_DO_CODIGO) return
    setErro(null)
    try {
      if (etapa.tipo === 'precisa_totp') await autenticador.confirmarTotp(codigo)
      else await autenticador.cadastrarTotp(codigo)
      aoEntrar()
    } catch (falha) {
      setErro(mensagemDeErro(falha))
    }
  }

  const alerta = erro && (
    <p role="alert" className="rounded-sm border border-destructive/40 bg-destructive/12 px-3 py-2 text-sm text-destructive">
      {erro}
    </p>
  )

  return (
    <div className="grid min-h-dvh bg-canvas lg:grid-cols-[1fr_480px]">
      <div className="relative hidden lg:block" aria-hidden>
        <div className="absolute bottom-8 left-8 max-w-md rounded-md border bg-background p-4">
          <p className="text-lg font-semibold">O acervo da RedeTV, decupado.</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Quem aparece, o que se fala e o que está na tela, em cada minuto de cada programa.
          </p>
        </div>
      </div>
      <main className="flex items-center justify-center bg-background p-6 lg:border-l">
        <div className="grid w-full max-w-sm gap-6">
          <div className="flex items-center gap-2">
            <img src={logo} alt="RedeTV" className="h-7 w-auto" />
            <span className="text-lg font-semibold">MAM</span>
          </div>
          {etapa.tipo === 'senha' ? (
            <form onSubmit={enviarSenha} className="grid gap-4">
              <div>
                <h1 className="text-xl font-semibold">Entrar</h1>
                <p className="mt-1 text-sm text-muted-foreground">Conta local com autenticador obrigatório.</p>
              </div>
              <Campo rotulo="E-mail" icone={<IconMail size={16} className="shrink-0 text-muted-foreground" aria-hidden />}>
                <input
                  name="email"
                  type="email"
                  required
                  autoComplete="username"
                  placeholder="nome@redetv.com.br"
                  className="min-w-0 flex-1 bg-transparent text-sm font-normal outline-none placeholder:text-muted-foreground"
                />
              </Campo>
              <Campo rotulo="Senha" icone={<IconLock size={16} className="shrink-0 text-muted-foreground" aria-hidden />}>
                <input
                  name="senha"
                  type={verSenha ? 'text' : 'password'}
                  required
                  autoComplete="current-password"
                  className="min-w-0 flex-1 bg-transparent text-sm font-normal outline-none"
                />
                <button
                  type="button"
                  aria-label={verSenha ? 'Esconder a senha' : 'Mostrar a senha'}
                  onClick={() => setVerSenha(!verSenha)}
                  className="shrink-0 rounded-xs text-muted-foreground hover:text-foreground"
                >
                  {verSenha ? <IconEyeOff size={16} /> : <IconEye size={16} />}
                </button>
              </Campo>
              <Button type="submit" size="lg">
                Entrar
              </Button>
              {alerta}
            </form>
          ) : (
            <form onSubmit={enviarCodigo} className="grid gap-4">
              <Button type="button" variant="ghost" size="sm" onClick={voltarAoInicio} className="justify-self-start">
                <IconArrowLeft stroke={1.75} /> Voltar
              </Button>
              <div>
                <h1 className="flex items-center gap-2 text-xl font-semibold">
                  <IconShieldLock size={20} stroke={1.75} className="text-muted-foreground" aria-hidden /> Verificação em duas
                  etapas
                </h1>
                {etapa.tipo === 'precisa_cadastro_totp' && (
                  <p className="mt-1 text-sm text-muted-foreground">
                    Primeiro acesso: cadastre um aplicativo autenticador com o segredo abaixo e digite o código que ele
                    mostrar.
                  </p>
                )}
              </div>
              {etapa.tipo === 'precisa_cadastro_totp' && (
                <div className="grid gap-2">
                  <code
                    aria-label="Segredo do autenticador"
                    className="rounded-sm border bg-card px-3 py-2 font-mono text-sm break-all select-all"
                  >
                    {etapa.segredo}
                  </code>
                  <a href={etapa.uri} className="flex items-center gap-1 justify-self-start text-sm text-link hover:underline">
                    <IconExternalLink size={16} stroke={1.75} aria-hidden /> Abrir no aplicativo autenticador
                  </a>
                </div>
              )}
              <label className="grid gap-1 text-xs font-medium">
                Digite o código de {DIGITOS_DO_CODIGO} números do seu aplicativo autenticador.
                <input
                  aria-label="Código do autenticador"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  maxLength={DIGITOS_DO_CODIGO}
                  value={codigo}
                  onChange={(e) => setCodigo(e.target.value.replace(/\D/g, ''))}
                  placeholder="000000"
                  className="h-12 rounded-sm border border-strong bg-input text-center font-mono text-2xl tracking-[0.4em] outline-none focus:border-primary"
                />
              </label>
              <Button type="submit" size="lg" disabled={codigo.length < DIGITOS_DO_CODIGO}>
                Confirmar
              </Button>
              {alerta}
            </form>
          )}
        </div>
      </main>
    </div>
  )
}
