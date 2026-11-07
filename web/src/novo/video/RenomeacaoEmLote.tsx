import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import type { AndamentoDaRenomeacao, ClienteDaRenomeacao, ImpactoDaRenomeacao } from '../../api.ts'
import { falhaDaAcao } from '../../falhaDaAcao.ts'
import { Button } from '../ui/button.tsx'
import { BotaoComDica } from './comum.tsx'
import { CAMPO, Rotulo } from './Correcao.tsx'

const plural = (n: number, um: string, varios: string) => `${n} ${n === 1 ? um : varios}`

/** O efeito da renomeação, na frase que a pessoa lê antes de confirmar. */
function efeito(i: ImpactoDaRenomeacao): string {
  return `${i.nome_antigo} passa a ser ${i.nome_novo} em ${plural(i.videos, 'vídeo', 'vídeos')} (${i.momentos_afetados} momento${i.momentos_afetados === 1 ? '' : 's'}). Enter confirma · Esc cancela.`
}

function frase(a: AndamentoDaRenomeacao): string {
  if (a.estado === 'concluida') return `Pronto: ${a.nome_novo} em ${plural(a.total, 'vídeo', 'vídeos')}.`
  if (a.estado === 'falhou') return `A busca ainda tem o nome antigo em ${plural(a.total - a.feitos, 'vídeo', 'vídeos')}. O nome novo já vale nas decupagens.`
  return `Atualizando a busca: ${a.feitos} de ${a.total} vídeos.`
}

/**
 * "Renomear em todos os vídeos" (Curador): o nome novo, a prévia do efeito, a confirmação com Enter e o
 * andamento. Desde o #417 a renomeação já nasce concluída; o andamento e o "Tentar de novo" só aparecem
 * numa renomeação antiga que ficou presa.
 */
export function RenomeacaoEmLote({
  pessoaId,
  nomeAtual,
  renomeacao,
  aoRenomear,
  aoFechar,
  intervaloMs = 1500,
}: {
  /** O id da pessoa no catálogo. */
  pessoaId: string
  nomeAtual: string
  renomeacao: ClienteDaRenomeacao
  /** Chamado quando o nome novo passa a valer, para a tela recarregar a decupagem. */
  aoRenomear: () => void
  aoFechar: () => void
  intervaloMs?: number
}) {
  const [nome, setNome] = useState(nomeAtual)
  const [impacto, setImpacto] = useState<ImpactoDaRenomeacao | null>(null)
  const [andamento, setAndamento] = useState<AndamentoDaRenomeacao | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const raiz = useRef<HTMLFormElement>(null)

  useEffect(() => raiz.current?.querySelector('input')?.focus(), [])

  // Com o andamento, o campo e o botão que tinham o foco saem: o foco vai para a mensagem de andamento.
  const comAndamento = andamento !== null
  useEffect(() => {
    if (comAndamento) raiz.current?.querySelector<HTMLElement>('[role=status]')?.focus()
  }, [comAndamento])

  // Enquanto a busca é atualizada, pergunta de tempos em tempos até terminar ou falhar.
  const acompanhando = andamento?.estado === 'em_andamento'
  useEffect(() => {
    if (!acompanhando) return
    let ativo = true
    const id = setInterval(() => {
      renomeacao.andamento(pessoaId).then(
        (a) => ativo && setAndamento(a),
        () => undefined,
      )
    }, intervaloMs)
    return () => {
      ativo = false
      clearInterval(id)
    }
  }, [acompanhando, renomeacao, pessoaId, intervaloMs])

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
      setAndamento(await renomeacao.andamento(pessoaId))
    } catch (e) {
      setErro(falhaDaAcao(e, 'Não foi possível renomear. Tente de novo.').mensagem)
    } finally {
      setOcupado(false)
    }
  }

  async function tentarDeNovo() {
    setErro(null)
    try {
      setAndamento(await renomeacao.retomar(pessoaId))
    } catch (e) {
      setErro(falhaDaAcao(e, 'Não foi possível retomar. Tente de novo.').mensagem)
    }
  }

  function aoTeclar(e: KeyboardEvent<HTMLFormElement>) {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      aoFechar()
    } else if (e.key === 'Enter' && !(e.target instanceof HTMLButtonElement) && !andamento) {
      e.preventDefault()
      void (impacto ? confirmar() : ver())
    }
  }

  return (
    <form ref={raiz} aria-label={`Renomear ${nomeAtual} em todos os vídeos`} className="grid gap-2" onKeyDown={aoTeclar} onSubmit={(e) => e.preventDefault()}>
      {!andamento && (
        <Rotulo texto="Novo nome">
          <input className={CAMPO} value={nome} maxLength={200} onChange={(e) => mudar(e.currentTarget.value)} />
        </Rotulo>
      )}
      {impacto && !andamento && <p className="text-xs">{efeito(impacto)}</p>}
      {andamento && (
        <p role="status" tabIndex={-1} className="text-xs outline-none">
          {frase(andamento)}
        </p>
      )}
      {erro && (
        <p role="alert" className="text-xs text-destructive">
          {erro}
        </p>
      )}
      <div className="flex flex-wrap items-center justify-end gap-2">
        <BotaoComDica dica="Esc" variant="secondary" onClick={aoFechar}>
          {andamento ? 'Fechar' : 'Cancelar'}
        </BotaoComDica>
        {andamento?.estado === 'falhou' && (
          <Button type="button" size="sm" onClick={() => void tentarDeNovo()}>
            Tentar de novo
          </Button>
        )}
        {!andamento && !impacto && (
          <BotaoComDica dica="Enter" disabled={ocupado || nome.trim().length === 0} onClick={() => void ver()}>
            {ocupado ? 'Calculando…' : 'Ver o efeito'}
          </BotaoComDica>
        )}
        {!andamento && impacto && (
          <BotaoComDica dica="Enter" disabled={ocupado} onClick={() => void confirmar()}>
            {ocupado ? 'Renomeando…' : 'Renomear'}
          </BotaoComDica>
        )}
      </div>
    </form>
  )
}
