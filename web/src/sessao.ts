import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { criarClienteDaApi, SessaoExpirada } from './api.ts'
import type { Autenticador } from './auth/autenticador.ts'
import { limparCacheDeImagens } from './cacheDeImagens.ts'
import { limparCacheDeQuadros } from './quadros.ts'
import { navegar, telaInicial, useRota } from './rotas.ts'

export interface Usuario {
  uid: string
  email: string
  /** Os nomes dos papéis, como `consulta` e `editor` (`papeis.ts`). */
  papeis?: string[]
  permissoes: string[]
}

// Sem sessão não renderiza nada além do login e não chama a API.
export type Sessao =
  | { tipo: 'verificando' }
  | { tipo: 'sem_sessao' }
  | { tipo: 'api_indisponivel' }
  | { tipo: 'ativa'; usuario: Usuario }

/**
 * A sessão: confere o `GET /v1/eu`, leva `/` à tela inicial e trata o 401 de qualquer tela num
 * lugar só.
 */
export function useSessao(autenticador: Autenticador) {
  const [sessao, setSessao] = useState<Sessao>({ tipo: 'verificando' })
  // Muda a cada saída, para o login recomeçar do zero (inclusive após um 401 logo depois do TOTP).
  const [saidas, setSaidas] = useState(0)
  const rota = useRota()

  const sair = useCallback(async () => {
    // Antes da saída: mesmo que o SDK falhe, a próxima pessoa do navegador não herda os quadros.
    limparCacheDeQuadros()
    await limparCacheDeImagens()
    await autenticador.sair()
    // A UI pode ter recriado o cache enquanto a saída aguardava.
    limparCacheDeQuadros()
    setSessao({ tipo: 'sem_sessao' })
    setSaidas((n) => n + 1)
  }, [autenticador])

  // Chamadas em paralelo podem voltar 401 juntas: a sessão cai uma vez só, e o próximo login volta
  // a ouvir o aviso.
  const expirou = useRef(false)
  const aoSessaoExpirada = useCallback(() => {
    if (expirou.current) return
    expirou.current = true
    void sair()
  }, [sair])
  const api = useMemo(
    // O cliente só guarda o callback; o ref é lido quando chega um 401, fora da renderização.
    // oxlint-disable-next-line react/refs
    () => criarClienteDaApi(autenticador, aoSessaoExpirada),
    [autenticador, aoSessaoExpirada],
  )

  // `/` vai ao acervo, ou ao painel para quem só vê o painel (sem `decupagem.ver`); o endereço pedido
  // antes do login fica como está e abre depois dele.
  const inicio = sessao.tipo === 'ativa' ? telaInicial(sessao.usuario.permissoes) : null
  useEffect(() => {
    if (inicio && rota.tipo === 'raiz') navegar(inicio, { substituir: true })
  }, [inicio, rota.tipo])

  const verificar = useCallback(async () => {
    try {
      setSessao({ tipo: 'ativa', usuario: await api.eu() })
    } catch (erro) {
      // Sessão expirada: o cliente já avisou e `sair` cuida do resto.
      if (!(erro instanceof SessaoExpirada)) setSessao({ tipo: 'api_indisponivel' })
    }
  }, [api])

  useEffect(() => {
    // Sincroniza com o SDK de login, um sistema externo.
    // oxlint-disable-next-line react/set-state-in-effect
    void verificar()
  }, [verificar])

  const reverificar = useCallback(() => {
    expirou.current = false
    setSessao({ tipo: 'verificando' })
    void verificar()
  }, [verificar])

  return { sessao, saidas, api, sair, reverificar }
}
