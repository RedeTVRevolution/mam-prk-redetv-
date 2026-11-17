import { IconEye, IconEyeOff, IconLock } from '@tabler/icons-react'
import { useEffect, useState, type SubmitEvent } from 'react'
import logo from '../assets/redetv-logo.png'
import { CodigoDeSenhaInvalido, SenhaRecusada, type Autenticador } from '../auth/autenticador.ts'
import { seguir } from '../rotas.ts'
import { Button } from './ui/button.tsx'

// Igual à `politica_de_senha` de infra/modulos/mam/main.tf; quem recusa é o servidor.
const REGRA = 'Mínimo 12 caracteres, com letra minúscula, maiúscula, número e símbolo.'

type Estado = { tipo: 'verificando' } | { tipo: 'invalido'; mensagem: string } | { tipo: 'pronto'; email: string }

const LINK_INVALIDO = 'Link inválido. Peça um novo link ao administrador.'

// O link vem do e-mail: só `mode=resetPassword`, e o código nunca sai desta tela nem vai a log.
function lerLink(): string | null {
  const dados = new URLSearchParams(location.search)
  return dados.get('mode') === 'resetPassword' ? dados.get('oobCode') || null : null
}

function mensagemDeErro(falha: unknown) {
  if (falha instanceof CodigoDeSenhaInvalido) return 'Link vencido ou já usado. Peça um novo link ao administrador.'
  if (falha instanceof SenhaRecusada) return `A senha não atende à regra: ${falha.message}`
  return 'Não foi possível definir a senha agora. Tente de novo.'
}

/** Página do link do e-mail de senha (conta nova ou refeita): define a senha e volta ao login, sem sessão. */
export default function RedefinirSenha({ autenticador, aoConcluir }: { autenticador: Autenticador; aoConcluir: () => void }) {
  const [codigo] = useState(lerLink)
  const [estado, setEstado] = useState<Estado>(codigo ? { tipo: 'verificando' } : { tipo: 'invalido', mensagem: LINK_INVALIDO })
  const [erro, setErro] = useState<string | null>(null)
  const [verSenha, setVerSenha] = useState(false)

  useEffect(() => {
    history.replaceState(null, '', location.pathname)
    if (!codigo) return
    let atual = true
    autenticador.verificarCodigoDeSenha(codigo).then(
      (email) => atual && setEstado({ tipo: 'pronto', email }),
      (falha) => atual && setEstado({ tipo: 'invalido', mensagem: falha instanceof CodigoDeSenhaInvalido ? mensagemDeErro(falha) : LINK_INVALIDO }),
    )
    return () => {
      atual = false
    }
  }, [autenticador, codigo])

  async function enviar(evento: SubmitEvent<HTMLFormElement>) {
    evento.preventDefault()
    const dados = new FormData(evento.currentTarget)
    const senha = String(dados.get('senha'))
    if (senha !== String(dados.get('confirmacao'))) return setErro('As senhas não são iguais.')
    setErro(null)
    try {
      await autenticador.redefinirSenha(codigo!, senha)
      aoConcluir()
    } catch (falha) {
      if (falha instanceof CodigoDeSenhaInvalido) setEstado({ tipo: 'invalido', mensagem: mensagemDeErro(falha) })
      else setErro(mensagemDeErro(falha))
    }
  }

  const campo = (nome: string, rotulo: string) => (
    <label className="grid gap-1 text-xs font-medium">
      {rotulo}
      <span className="flex h-10 items-center gap-2 rounded-sm border border-strong bg-input px-3 focus-within:border-primary">
        <IconLock size={16} className="shrink-0 text-muted-foreground" aria-hidden />
        <input
          name={nome}
          aria-label={rotulo}
          type={verSenha ? 'text' : 'password'}
          required
          autoComplete="new-password"
          className="min-w-0 flex-1 bg-transparent text-sm font-normal outline-none"
        />
      </span>
    </label>
  )

  return (
    <main className="flex min-h-dvh items-center justify-center bg-background p-6">
      <div className="grid w-full max-w-sm gap-6">
        <div className="flex items-center gap-2">
          <img src={logo} alt="RedeTV" className="h-7 w-auto" />
          <span className="text-lg font-semibold">MAM</span>
        </div>
        {estado.tipo === 'verificando' && (
          <p role="status" className="text-muted-foreground">
            Verificando o link…
          </p>
        )}
        {estado.tipo === 'invalido' && (
          <div className="grid gap-4">
            <p role="alert" className="rounded-sm border border-destructive/40 bg-destructive/12 px-3 py-2 text-sm text-destructive">
              {estado.mensagem}
            </p>
            <a href="/" onClick={(e) => seguir(e, '/')} className="justify-self-start text-sm text-link hover:underline">
              Ir ao login
            </a>
          </div>
        )}
        {estado.tipo === 'pronto' && (
          <form onSubmit={enviar} className="grid gap-4">
            <div>
              <h1 className="text-xl font-semibold">Definir senha</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Conta <span className="font-medium text-foreground">{estado.email}</span>
              </p>
              <p className="mt-1 text-sm text-muted-foreground">{REGRA}</p>
            </div>
            {campo('senha', 'Senha nova')}
            {campo('confirmacao', 'Confirme a senha nova')}
            <button
              type="button"
              onClick={() => setVerSenha(!verSenha)}
              className="flex items-center gap-1 justify-self-start text-xs text-muted-foreground hover:text-foreground"
            >
              {verSenha ? <IconEyeOff size={16} /> : <IconEye size={16} />} {verSenha ? 'Esconder as senhas' : 'Mostrar as senhas'}
            </button>
            <Button type="submit" size="lg">
              Definir senha
            </Button>
            {erro && (
              <p role="alert" className="rounded-sm border border-destructive/40 bg-destructive/12 px-3 py-2 text-sm text-destructive">
                {erro}
              </p>
            )}
          </form>
        )}
      </div>
    </main>
  )
}
