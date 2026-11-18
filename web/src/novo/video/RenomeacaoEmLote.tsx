import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import type { ClienteDaRenomeacao, ImpactoDaRenomeacao } from '../../api.ts'
import { falhaDaAcao } from '../../falhaDaAcao.ts'
import { BotaoComDica } from './comum.tsx'
import { CAMPO, Rotulo } from './Correcao.tsx'

const plural = (n: number, um: string, varios: string) => `${n} ${n === 1 ? um : varios}`

/** O efeito da renomeação, na frase que a pessoa lê antes de confirmar. */
function efeito(i: ImpactoDaRenomeacao): string {
  return `${i.nome_antigo} passa a ser ${i.nome_novo} em ${plural(i.videos, 'vídeo', 'vídeos')} (${i.momentos_afetados} momento${i.momentos_afetados === 1 ? '' : 's'}). Enter confirma · Esc cancela.`
}

/**
 * "Renomear em todos os vídeos" (Curador): o nome novo, a prévia do efeito e a confirmação com Enter.
 * Desde o #417 a renomeação já nasce concluída: confirmar renomeia, avisa e fecha.
 */
export function RenomeacaoEmLote({
  pessoaId,
  nomeAtual,
  renomeacao,
  aoRenomear,
  aoFechar,
}: {
  /** O id da pessoa no catálogo. */
  pessoaId: string
  nomeAtual: string
  renomeacao: ClienteDaRenomeacao
  /** Chamado quando o nome novo passa a valer, para a tela recarregar a decupagem. */
  aoRenomear: () => void
  aoFechar: () => void
}) {
  const [nome, setNome] = useState(nomeAtual)
  const [impacto, setImpacto] = useState<ImpactoDaRenomeacao | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const raiz = useRef<HTMLFormElement>(null)

  useEffect(() => raiz.current?.querySelector('input')?.focus(), [])

  function mudar(valor: string) {
    setNome(valor)
    setImpacto(null)
    setErro(null)
  }

  async function ver() {
    const novo = nome.trim()
    if (!novo || ocupado) return
    setOcupado(true)
    setErro(null)
    try {
      setImpacto(await renomeacao.previa(pessoaId, novo))
    } catch (e) {
      setErro(falhaDaAcao(e, 'Não foi possível calcular o efeito. Tente de novo.').mensagem)
    } finally {
      setOcupado(false)
    }
  }

  async function confirmar() {
    if (!impacto || ocupado) return
    setOcupado(true)
    setErro(null)
    try {
      await renomeacao.renomear(pessoaId, impacto.nome_novo)
      aoRenomear()
      aoFechar()
    } catch (e) {
      setErro(falhaDaAcao(e, 'Não foi possível renomear. Tente de novo.').mensagem)
    } finally {
      setOcupado(false)
    }
  }

  function aoTeclar(e: KeyboardEvent<HTMLFormElement>) {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      aoFechar()
    } else if (e.key === 'Enter' && !(e.target instanceof HTMLButtonElement)) {
      e.preventDefault()
      void (impacto ? confirmar() : ver())
    }
  }

  return (
    <form ref={raiz} aria-label={`Renomear ${nomeAtual} em todos os vídeos`} className="grid gap-2" onKeyDown={aoTeclar} onSubmit={(e) => e.preventDefault()}>
      <Rotulo texto="Novo nome">
        <input className={CAMPO} value={nome} maxLength={200} onChange={(e) => mudar(e.currentTarget.value)} />
      </Rotulo>
      {impacto && <p className="text-xs">{efeito(impacto)}</p>}
      {erro && (
        <p role="alert" className="text-xs text-destructive">
          {erro}
        </p>
      )}
      <div className="flex flex-wrap items-center justify-end gap-2">
        <BotaoComDica dica="Esc" variant="secondary" onClick={aoFechar}>
          Cancelar
        </BotaoComDica>
        {!impacto && (
          <BotaoComDica dica="Enter" disabled={ocupado || nome.trim().length === 0} onClick={() => void ver()}>
            {ocupado ? 'Calculando…' : 'Ver o efeito'}
          </BotaoComDica>
        )}
        {impacto && (
          <BotaoComDica dica="Enter" disabled={ocupado} onClick={() => void confirmar()}>
            {ocupado ? 'Renomeando…' : 'Renomear'}
          </BotaoComDica>
        )}
      </div>
    </form>
  )
}
