import { useEffect, useRef } from 'react'
import type { ClienteDoJob, EventoDeRevisao } from './api.ts'

export const INTERVALO_DO_PULSO_MS = 60_000
export const INATIVIDADE_PADRAO_MS = 300_000

/**
 * A sessão de revisão (#251): enquanto `ativo`, avisa a API ao começar, a cada minuto com
 * atividade (tecla, clique ou player tocando) e ao sair. Sem atividade por `inatividadeMs`
 * a sessão pausa e não avisa; a próxima atividade abre outra. Não mostra nada: o objetivo é
 * medir. A falha de um aviso é calada, para não atrapalhar quem revisa.
 */
export function useSessaoDeRevisao(
  api: ClienteDoJob,
  ativo: boolean,
  tocando: boolean,
  inatividadeMs: number = INATIVIDADE_PADRAO_MS,
  intervaloMs: number = INTERVALO_DO_PULSO_MS,
): void {
  const tocandoAgora = useRef(tocando)
  useEffect(() => {
    tocandoAgora.current = tocando
  }, [tocando])

  useEffect(() => {
    if (!ativo) return
    const avisar = (evento: EventoDeRevisao) => {
      api.pulsoDeRevisao(evento).catch(() => {})
    }
    let ultimaAtividade = Date.now()
    let pausada = false
    avisar('inicio')
    const comAtividade = () => {
      ultimaAtividade = Date.now()
      if (!pausada) return
      pausada = false
      avisar('inicio')
    }
    const aCadaMinuto = setInterval(() => {
      if (tocandoAgora.current) ultimaAtividade = Date.now()
      if (pausada) return
      if (Date.now() - ultimaAtividade >= inatividadeMs) pausada = true
      else avisar('atividade')
    }, intervaloMs)
    document.addEventListener('keydown', comAtividade)
    document.addEventListener('pointerdown', comAtividade)
    return () => {
      clearInterval(aCadaMinuto)
      document.removeEventListener('keydown', comAtividade)
      document.removeEventListener('pointerdown', comAtividade)
      if (!pausada) avisar('fim')
    }
  }, [api, ativo, inatividadeMs, intervaloMs])
}
