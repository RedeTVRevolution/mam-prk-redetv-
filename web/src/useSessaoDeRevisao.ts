import { useEffect, useRef } from 'react'
import type { ClienteDoJob, EventoDeRevisao } from './api.ts'

export const INTERVALO_DO_PULSO_MS = 60_000
export const INATIVIDADE_PADRAO_MS = 300_000

/**
 * A sessão de revisão (#251): enquanto `ativo`, avisa a API ao começar, a cada minuto com
 * atividade (tecla, clique ou player tocando) e ao sair. Um minuto sem atividade não avisa;
 * sem atividade por `inatividadeMs` a sessão pausa, e a próxima atividade abre outra. Não mostra nada: o objetivo é
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
    let houveAtividade = false
    let pausada = false
    avisar('inicio')
    // O minuto parado não avisa: a API soma o intervalo até o próximo aviso se ele couber no
    // limite, e não soma nada se passar dele.
    const comAtividade = () => {
      const agora = Date.now()
      if (pausada || agora - ultimaAtividade >= inatividadeMs) {
        pausada = false
        avisar('inicio')
      }
      ultimaAtividade = agora
      houveAtividade = true
    }
    const aCadaMinuto = setInterval(() => {
      if (tocandoAgora.current) comAtividade()
      if (pausada) return
      if (houveAtividade) {
        houveAtividade = false
        avisar('atividade')
      } else if (Date.now() - ultimaAtividade >= inatividadeMs) pausada = true
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
