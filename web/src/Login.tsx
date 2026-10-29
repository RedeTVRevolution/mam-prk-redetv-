import { useState, type SubmitEvent } from 'react'
import {
  CredencialInvalida,
  type Autenticador,
  type ResultadoDaSenha,
} from './auth/autenticador.ts'

type Etapa = Exclude<ResultadoDaSenha, { tipo: 'logado' }> | { tipo: 'senha' }

export default function Login({
  autenticador,
  aoEntrar,
}: {
  autenticador: Autenticador
  aoEntrar: () => void
}) {
  const [etapa, setEtapa] = useState<Etapa>({ tipo: 'senha' })
  const [erro, setErro] = useState<string | null>(null)

  async function enviar(evento: SubmitEvent<HTMLFormElement>) {
    evento.preventDefault()
    const dados = new FormData(evento.currentTarget)
    setErro(null)
    try {
      if (etapa.tipo === 'senha') {
        const resultado = await autenticador.entrar(
          String(dados.get('email')),
          String(dados.get('senha')),
        )
        if (resultado.tipo === 'logado') aoEntrar()
        else setEtapa(resultado)
      } else {
        const codigo = String(dados.get('codigo'))
        if (etapa.tipo === 'precisa_totp') await autenticador.confirmarTotp(codigo)
        else await autenticador.cadastrarTotp(codigo)
        aoEntrar()
      }
    } catch (erro) {
      setErro(
        erro instanceof CredencialInvalida
          ? 'Credenciais inválidas. Confira os dados e tente de novo.'
          : 'Login indisponível no momento.',
      )
    }
  }

  return (
    <main>
      <h1>MAM RedeTV</h1>
      <form key={etapa.tipo === 'senha' ? 'senha' : 'totp'} onSubmit={enviar}>
        {etapa.tipo === 'senha' ? (
          <>
            <label>
              E-mail
              <input name="email" type="email" autoComplete="username" required />
            </label>
            <label>
              Senha
              <input name="senha" type="password" autoComplete="current-password" required />
            </label>
            <button type="submit">Entrar</button>
          </>
        ) : (
          <>
            {etapa.tipo === 'precisa_cadastro_totp' && (
              <section>
                <p>
                  Primeiro acesso: cadastre um aplicativo autenticador com o segredo abaixo e
                  digite o código que ele mostrar.
                </p>
                <code>{etapa.segredo}</code>
                <p>
                  <a href={etapa.uri}>Abrir no aplicativo autenticador</a>
                </p>
              </section>
            )}
            <label>
              Código do autenticador
              <input name="codigo" inputMode="numeric" autoComplete="one-time-code" required />
            </label>
            <button type="submit">Confirmar</button>
          </>
        )}
        {erro && <p role="alert">{erro}</p>}
      </form>
    </main>
  )
}
