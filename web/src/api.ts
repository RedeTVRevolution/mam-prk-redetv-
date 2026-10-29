import type { Autenticador } from './auth/autenticador.ts'

export class SessaoExpirada extends Error {}

/** Chama `/v1` com o token da sessão; 401 vira SessaoExpirada. */
export async function chamarApi<T>(
  autenticador: Autenticador,
  caminho: string,
  opcoes: { metodo?: string; corpo?: unknown } = {},
): Promise<T> {
  const token = await autenticador.token()
  if (!token) throw new SessaoExpirada()
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
  if (opcoes.corpo !== undefined) headers['Content-Type'] = 'application/json'
  const resposta = await fetch(caminho, {
    method: opcoes.metodo,
    headers,
    body: opcoes.corpo === undefined ? undefined : JSON.stringify(opcoes.corpo),
  })
  if (resposta.status === 401) throw new SessaoExpirada()
  if (!resposta.ok) throw new Error(`Falha ${resposta.status} em ${caminho}`)
  return (await resposta.json()) as T
}
