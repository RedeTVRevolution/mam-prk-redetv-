import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import type { ClienteDaFusao, ImpactoDaFusao } from '../../api.ts'
import { falhaDaAcao } from '../../falhaDaAcao.ts'
import { BotaoComDica } from './comum.tsx'
import { CAMPO, CampoDeNome, Rotulo } from './Correcao.tsx'

const MOTIVO_PADRAO = 'nome duplicado'

const videos = (n: number) => `${n} ${n === 1 ? 'vídeo' : 'vídeos'}`

/** O efeito da fusão, na frase que a pessoa lê antes de confirmar. */
function efeitoDaFusao(i: ImpactoDaFusao): string {
  const fotos = i.fotos_apagadas > 0 ? ` As fotos de referência de ${i.origem_nome} serão apagadas.` : ''
  return `${i.origem_nome} passa a ser ${i.destino_nome} em ${videos(i.videos)}.${fotos} A fusão não pode ser desfeita. Enter confirma · Esc cancela.`
}

/**
 * "Fundir com…": escolhe o destino no autocompletar do catálogo, mostra o efeito e, com Enter, funde. O
 * motivo vem preenchido ("nome duplicado") e é editável.
 */
export function FusaoDePessoa({
  origemId,
  nomeDaOrigem,
  fusao,
  limiteDoMotivo,
  aoFundir,
  aoCancelar,
}: {
  /** O id da pessoa no catálogo. */
  origemId: string
  nomeDaOrigem: string
  fusao: ClienteDaFusao
  limiteDoMotivo: number
  /** Chamado depois de fundir, para a tela recarregar a decupagem. */
  aoFundir: () => void
  aoCancelar: () => void
}) {
  const [destino, setDestino] = useState({ nome: '', id: '' })
  const [motivo, setMotivo] = useState(MOTIVO_PADRAO)
  const [impacto, setImpacto] = useState<ImpactoDaFusao | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [fundindo, setFundindo] = useState(false)
  const pedido = useRef(0)
  const raiz = useRef<HTMLFormElement>(null)

  useEffect(() => raiz.current?.querySelector('input')?.focus(), [])

  function escolher(nome: string, id: string) {
    const este = ++pedido.current
    setDestino({ nome, id })
    setImpacto(null)
    setErro(null)
    if (!id) return
    fusao.impacto(origemId, id).then(
      (i) => {
        if (este === pedido.current) setImpacto(i)
      },
      (e: unknown) => {
        if (este === pedido.current) setErro(falhaDaAcao(e, 'Não foi possível calcular o efeito da fusão. Escolha o destino de novo.').mensagem)
      },
    )
  }

  async function confirmar() {
    if (!impacto || fundindo || motivo.trim().length === 0) return
    setFundindo(true)
    setErro(null)
    try {
      await fusao.fundir(origemId, destino.id, motivo.trim())
      aoFundir()
    } catch (e) {
      setErro(falhaDaAcao(e, 'Não foi possível fundir as pessoas. Tente de novo.').mensagem)
      setFundindo(false)
    }
  }

  function aoTeclar(e: KeyboardEvent<HTMLFormElement>) {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      aoCancelar()
    } else if (e.key === 'Enter' && !(e.target instanceof HTMLButtonElement)) {
      e.preventDefault()
      void confirmar()
    }
  }

  return (
    <form ref={raiz} aria-label={`Fundir ${nomeDaOrigem} com`} className="grid gap-2" onKeyDown={aoTeclar} onSubmit={(e) => e.preventDefault()}>
      <CampoDeNome rotulo="Fundir com" catalogo="pessoas" soDoCatalogo valor={destino.nome} aoMudar={escolher} />
      <Rotulo texto="Motivo">
        <input className={CAMPO} maxLength={limiteDoMotivo} value={motivo} onChange={(e) => setMotivo(e.currentTarget.value)} />
      </Rotulo>
      {impacto && <p className="text-xs">{efeitoDaFusao(impacto)}</p>}
      {erro && (
        <p role="alert" className="text-xs text-destructive">
          {erro}
        </p>
      )}
      <div className="flex flex-wrap items-center justify-end gap-2">
        <BotaoComDica dica="Esc" variant="secondary" onClick={aoCancelar}>
          Cancelar
        </BotaoComDica>
        <BotaoComDica dica="Enter" disabled={!impacto || fundindo} onClick={() => void confirmar()}>
          {fundindo ? 'Fundindo…' : 'Fundir'}
        </BotaoComDica>
      </div>
    </form>
  )
}
