import { IconArrowBackUp, IconCheck, IconX } from '@tabler/icons-react'
import { cn } from 'cn'
import { Tabs } from 'radix-ui'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { type ClienteDoJob, ConflitoNaApi, SessaoExpirada } from '../../api.ts'
import { type Atalho, useAtalhos } from '../../atalhos.ts'
import { desfazivel } from '../../catalogacao.ts'
import { type CatalogoDeCorrecoes, rotuloDe } from '../../catalogo.ts'
import type { ItemDaFila, ItemDoHistorico } from '../../decupagem.ts'
import { relogio } from '../../linhaDoTempo.ts'
import { Button } from '../ui/button.tsx'
import { BotaoComDica, BotaoDeIcone } from './comum.tsx'
import { CAMPO, Rotulo } from './Correcao.tsx'

export type AbaDaGaveta = 'historico' | 'fila' | 'aprovacao'

const GRUPO = 'Histórico'
// O motivo do gesto: a pessoa decide num clique, sem escrever (a recusa é a exceção e pede o motivo).
const MOTIVO_DE_DESFAZER = 'correção desfeita pelo editor'
const MOTIVO_DE_REAPLICAR = 'correção reaplicada pelo editor'
const MOTIVO_DE_DESCARTAR = 'correção descartada pelo editor'

// Quantas linhas das listas longas existem de uma vez: com centenas, o painel passaria de 3 mil elementos.
const POR_VEZ = 100

function MostrarMais({ total, mostrados, aoMostrar }: { total: number; mostrados: number; aoMostrar: () => void }) {
  if (total <= mostrados) return null
  return (
    <Button type="button" size="sm" variant="secondary" className="justify-self-center" onClick={aoMostrar}>
      {`Mostrar mais ${Math.min(POR_VEZ, total - mostrados)}`}
    </Button>
  )
}

const quando = (iso: string) => new Date(iso).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' })

const COR_DO_ESTADO: Record<ItemDoHistorico['estado'], string> = {
  ativa: 'bg-ok/12 text-ok',
  aprovada: 'bg-ok/12 text-ok',
  pendente: 'bg-andamento/12 text-andamento',
  recusada: 'bg-destructive/12 text-destructive',
  desfeita: 'bg-input text-muted-foreground',
  reaplicada: 'bg-input text-muted-foreground',
  descartada: 'bg-input text-muted-foreground',
}

const CARTAO = 'grid gap-1 rounded-sm border bg-card p-2'
const SELO = 'inline-flex h-5 shrink-0 items-center rounded-xs px-1.5 text-xs font-medium whitespace-nowrap'

function AntesEDepois({ item }: { item: Pick<ItemDoHistorico, 'antes_legivel' | 'depois_legivel'> }) {
  return (
    <>
      <p className="flex gap-1 text-sm">
        <span className="text-xs text-muted-foreground">Antes:</span>
        {item.antes_legivel}
      </p>
      <p className="flex gap-1 text-sm font-semibold">
        <span className="text-xs font-normal text-muted-foreground">Depois:</span>
        {item.depois_legivel}
      </p>
    </>
  )
}

/** O campo do motivo da recusa na própria linha: Enter recusa e Esc cancela; sem motivo, nada é enviado. */
function RecusaNaLinha({
  limite,
  enviando,
  aoCancelar,
  aoRecusar,
}: {
  limite: number | undefined
  enviando: boolean
  aoCancelar: () => void
  aoRecusar: (motivo: string) => void
}) {
  const [motivo, setMotivo] = useState('')
  const pronto = motivo.trim().length > 0
  return (
    <div className="grid gap-1">
      <Rotulo texto="Motivo da recusa">
        <input
          // O Esc daqui cancela só o campo, sem fechar a gaveta.
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          value={motivo}
          maxLength={limite}
          className={CAMPO}
          onChange={(e) => setMotivo(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault()
              aoCancelar()
            } else if (e.key === 'Enter' && pronto && !enviando) aoRecusar(motivo.trim())
          }}
        />
      </Rotulo>
      <div className="flex justify-end gap-1">
        <BotaoComDica dica="Esc" variant="secondary" onClick={aoCancelar}>
          Cancelar
        </BotaoComDica>
        <BotaoComDica dica="Enter" aria-busy={enviando} disabled={!pronto || enviando} onClick={() => aoRecusar(motivo.trim())}>
          Recusar
        </BotaoComDica>
      </div>
    </div>
  )
}

function CabecalhoDaCorrecao({ item, rotulo }: { item: ItemDoHistorico | ItemDaFila; rotulo: string }) {
  return (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold">{rotulo}</span>
        {'estado' in item && <span className={cn(SELO, COR_DO_ESTADO[item.estado])}>{item.estado}</span>}
      </div>
      <p className="text-xs text-muted-foreground">{item.autor_email}</p>
      <p className="text-xs text-muted-foreground">{quando(item.criada_em)}</p>
    </>
  )
}

/**
 * A gaveta das correções do vídeo, no lugar do inspetor, com o player à vista: o histórico, a fila das
 * que não casaram depois de reprocessar e a aprovação do Curador. Desfazer, reaplicar, descartar e
 * aprovar são um clique; recusar pede o motivo na própria linha. Nada se apaga: cada decisão acrescenta.
 */
export function Gaveta({
  aba,
  aoTrocarAba,
  aoFechar,
  historico,
  fila,
  podeAprovar,
  api,
  catalogo,
  falhaAoCarregar,
  aoMudar,
  aoSaltar,
  aoRefazerAMao,
}: {
  aba: AbaDaGaveta
  aoTrocarAba: (aba: AbaDaGaveta) => void
  aoFechar: () => void
  historico: ItemDoHistorico[]
  fila: ItemDaFila[]
  podeAprovar: boolean
  api: ClienteDoJob
  catalogo: CatalogoDeCorrecoes | null
  /** O histórico ou a fila não vieram da API. */
  falhaAoCarregar: boolean
  /** Recarrega a decupagem, o histórico e a fila depois de uma decisão. */
  aoMudar: () => void
  /** Salta o player ao item da correção; `false` se o item não está mais na decupagem. */
  aoSaltar: (correcao: ItemDoHistorico) => boolean
  /** Juntar ou dividir pautas que a reprocessagem não reaplicou: refazer na lista de pautas. */
  aoRefazerAMao?: () => void
}) {
  const pendentes = historico.filter((h) => h.estado === 'pendente')
  const [selecionado, setSelecionado] = useState(0)
  const [mostrados, setMostrados] = useState(POR_VEZ)
  const [ocupado, setOcupado] = useState<string | null>(null)
  const [recusando, setRecusando] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const lista = useRef<HTMLDivElement>(null)
  const rotulo = (tipo: string) => (catalogo ? rotuloDe(catalogo.tipos, tipo) : tipo)
  const indice = Math.min(selecionado, Math.max(historico.length - 1, 0))
  // A linha selecionada (pelas setas) sempre existe, mesmo além do que "Mostrar mais" já abriu.
  const doHistorico = Math.max(mostrados, indice + 1)
  const limiteDoMotivo = catalogo?.limites.motivo

  // A linha selecionada fica à vista ao mover a seleção.
  useEffect(() => {
    lista.current?.querySelector('[data-selecionada="true"]')?.scrollIntoView?.({ block: 'nearest' })
  }, [indice, aba])

  // O Esc fecha a gaveta, menos quando outro elemento já o usou (o formulário de correção no inspetor, a
  // confirmação na linha, a recusa): eles marcam o evento com `preventDefault` ou param a propagação.
  useEffect(() => {
    const aoTeclar = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented && !e.isComposing) aoFechar()
    }
    window.addEventListener('keydown', aoTeclar)
    return () => window.removeEventListener('keydown', aoTeclar)
  }, [aoFechar])

  function trocarAba(nova: string) {
    if (nova !== 'historico' && nova !== 'fila' && nova !== 'aprovacao') return
    setAviso(null)
    setErro(null)
    setRecusando(null)
    aoTrocarAba(nova)
  }

  function saltar(i: number) {
    const correcao = historico[i]
    if (!correcao) return
    setSelecionado(i)
    setAviso(aoSaltar(correcao) ? null : 'Este item não está mais na decupagem.')
  }

  const noHistorico = aba === 'historico'
  const atalhos: Atalho[] = [
    {
      tecla: '↑ ↓',
      acao: 'Na gaveta do histórico: mover a seleção',
      grupo: GRUPO,
      casa: (e) => noHistorico && (e.key === 'ArrowUp' || e.key === 'ArrowDown'),
      executar: (e) => {
        setAviso(null)
        setSelecionado(Math.max(Math.min(indice + (e.key === 'ArrowUp' ? -1 : 1), historico.length - 1), 0))
      },
    },
    {
      tecla: 'Enter',
      acao: 'Na gaveta do histórico: saltar o player ao item',
      grupo: GRUPO,
      // Com o foco num botão ou numa aba, o Enter faz o que o elemento faz.
      casa: (e) => noHistorico && e.key === 'Enter' && !(e.target instanceof HTMLElement && e.target.closest('button, a, [role="tab"]')),
      executar: () => saltar(indice),
    },
  ]
  useAtalhos(atalhos)

  /** Roda a decisão; qualquer que seja o resultado, as listas são recarregadas (outra pessoa pode ter decidido antes). */
  async function decidir(id: string, acao: () => Promise<void>, conflito: string, falha: string) {
    // Uma decisão por vez: o segundo clique, nesta ou noutra linha, espera a primeira terminar.
    if (ocupado) return
    setOcupado(id)
    setErro(null)
    setAviso(null)
    try {
      await acao()
      setRecusando(null)
    } catch (e) {
      setOcupado(null)
      // Com a sessão expirada, o aviso é da casca e recarregar só falharia de novo.
      if (e instanceof SessaoExpirada) return
      setErro(e instanceof ConflitoNaApi ? conflito : falha)
    }
    setOcupado(null)
    aoMudar()
  }

  const desfazer = (c: ItemDoHistorico) =>
    decidir(
      c.id,
      () => api.desfazer(c.id, MOTIVO_DE_DESFAZER),
      'Essa correção já foi desfeita, saiu da fila ou não casa com a versão atual. O histórico foi recarregado.',
      'Não foi possível desfazer a correção. Tente de novo em instantes.',
    )
  const aprovar = (c: ItemDoHistorico) =>
    decidir(
      c.id,
      () => api.aprovar(c.id),
      'Essa correção não está mais pendente. O histórico foi recarregado.',
      'Não foi possível aprovar a correção. Tente de novo em instantes.',
    )
  const recusar = (c: ItemDoHistorico, motivo: string) =>
    decidir(
      c.id,
      () => api.recusar(c.id, motivo),
      'Essa correção não está mais pendente. O histórico foi recarregado.',
      'Não foi possível recusar a correção. Tente de novo em instantes.',
    )

  return (
    <aside aria-label="Correções do vídeo" className="flex h-[80dvh] w-full shrink-0 flex-col overflow-y-auto bg-background lg:h-auto lg:min-h-0 lg:w-[400px] xl:w-[420px]">
      <div className="flex h-8 shrink-0 items-center gap-2 border-b bg-card px-3">
        <h2 className="min-w-0 flex-1 truncate text-sm font-medium">Correções do vídeo</h2>
        <BotaoDeIcone rotulo="Fechar" atalho="Esc" className="-mr-1.5" onClick={aoFechar}>
          <IconX size={16} stroke={1.75} aria-hidden />
        </BotaoDeIcone>
      </div>
      <Tabs.Root value={aba} onValueChange={trocarAba} className="flex min-h-0 flex-1 flex-col">
        <Tabs.List className="flex shrink-0 border-b px-1">
          <Aba valor="historico">Histórico</Aba>
          <Aba valor="fila">{`Fila de revisão (${fila.length})`}</Aba>
          {podeAprovar && <Aba valor="aprovacao">{`Aprovação (${pendentes.length})`}</Aba>}
        </Tabs.List>
        <div ref={lista} className="grid content-start gap-2 p-3">
          {aviso && (
            <p role="status" className="text-sm">
              {aviso}
            </p>
          )}
          {erro && (
            <div role="alert" className="rounded-sm border border-destructive/40 bg-destructive/12 px-3 py-2 text-sm text-destructive">
              {erro}
            </div>
          )}
          {falhaAoCarregar && (
            <div role="alert" className="grid justify-items-start gap-1 rounded-sm border border-destructive/40 bg-destructive/12 px-3 py-2 text-sm">
              <p className="text-destructive">Não foi possível carregar o histórico e a fila de revisão.</p>
              <Button type="button" size="sm" variant="secondary" onClick={aoMudar}>
                Tentar de novo
              </Button>
            </div>
          )}
          <Tabs.Content value="historico" className="grid gap-2">
            {historico.length === 0 && <p className="text-sm text-muted-foreground">Nenhuma correção ainda.</p>}
            {historico.slice(0, doHistorico).map((c, i) => (
              <div key={c.id} data-selecionada={i === indice} className={cn(CARTAO, i === indice && 'border-primary')}>
                <button
                  type="button"
                  aria-label={`Saltar ao item: ${rotulo(c.tipo)}, ${c.depois_legivel}`}
                  onClick={() => saltar(i)}
                  className="grid gap-1 rounded-xs text-left"
                >
                  <CabecalhoDaCorrecao item={c} rotulo={rotulo(c.tipo)} />
                  <AntesEDepois item={c} />
                  <span className="text-sm">{c.motivo}</span>
                  {c.reaplica && <span className="text-xs text-muted-foreground">{`Reaplica a correção de ${quandoDaOriginal(historico, c.reaplica)}`}</span>}
                </button>
                {desfazivel(c) && (
                  <div className="flex justify-end">
                    <Button type="button" size="sm" variant="secondary" title="Desfazer esta correção" aria-busy={ocupado === c.id} onClick={() => void desfazer(c)}>
                      <IconArrowBackUp size={14} stroke={1.75} aria-hidden />
                      Desfazer
                    </Button>
                  </div>
                )}
              </div>
            ))}
            <MostrarMais total={historico.length} mostrados={doHistorico} aoMostrar={() => setMostrados(doHistorico + POR_VEZ)} />
          </Tabs.Content>
          <Tabs.Content value="fila" className="grid gap-2">
            {fila.length === 0 && <p className="text-sm text-muted-foreground">Nada na fila.</p>}
            {fila.map((f) => (
              <ItemDaFilaDeRevisao
                key={f.id}
                item={f}
                rotulo={rotulo(f.tipo)}
                ocupado={ocupado === f.id}
                aoRefazerAMao={aoRefazerAMao}
                aoReaplicar={(candidato) =>
                  void decidir(
                    f.id,
                    () => api.reaplicar(f.id, candidato, MOTIVO_DE_REAPLICAR),
                    'Essa correção não está mais na fila. A fila foi recarregada.',
                    'Não foi possível reaplicar a correção. Tente de novo em instantes.',
                  )
                }
                aoDescartar={() =>
                  void decidir(
                    f.id,
                    () => api.descartar(f.id, MOTIVO_DE_DESCARTAR),
                    'Essa correção não está mais na fila. A fila foi recarregada.',
                    'Não foi possível descartar a correção. Tente de novo em instantes.',
                  )
                }
              />
            ))}
          </Tabs.Content>
          {podeAprovar && (
            <Tabs.Content value="aprovacao" className="grid gap-2">
              {pendentes.length === 0 && <p className="text-sm text-muted-foreground">Nada aguardando o Curador.</p>}
              {pendentes.slice(0, mostrados).map((c) => (
                <div key={c.id} className={CARTAO}>
                  <CabecalhoDaCorrecao item={c} rotulo={rotulo(c.tipo)} />
                  <AntesEDepois item={c} />
                  <span className="text-sm">{c.motivo}</span>
                  {recusando === c.id ? (
                    <RecusaNaLinha limite={limiteDoMotivo} enviando={ocupado === c.id} aoCancelar={() => setRecusando(null)} aoRecusar={(motivo) => void recusar(c, motivo)} />
                  ) : (
                    <div className="flex justify-end gap-1">
                      <Button type="button" size="sm" variant="secondary" title="Recusar a correção (pede o motivo)" disabled={ocupado === c.id} onClick={() => setRecusando(c.id)}>
                        <IconX size={14} stroke={1.75} aria-hidden />
                        Recusar
                      </Button>
                      <Button type="button" size="sm" title="Aprovar a correção: ela entra na decupagem" aria-busy={ocupado === c.id} onClick={() => void aprovar(c)}>
                        <IconCheck size={14} stroke={1.75} aria-hidden />
                        Aprovar
                      </Button>
                    </div>
                  )}
                </div>
              ))}
              <MostrarMais total={pendentes.length} mostrados={mostrados} aoMostrar={() => setMostrados(mostrados + POR_VEZ)} />
            </Tabs.Content>
          )}
        </div>
      </Tabs.Root>
    </aside>
  )
}

function Aba({ valor, children }: { valor: AbaDaGaveta; children: ReactNode }) {
  return (
    <Tabs.Trigger
      value={valor}
      className="h-8 border-b-2 border-transparent px-2 text-sm whitespace-nowrap text-muted-foreground hover:text-foreground data-[state=active]:border-primary data-[state=active]:text-foreground"
    >
      {children}
    </Tabs.Trigger>
  )
}

/** A data da correção que a reaplicação refaz, para ligar uma à outra. */
function quandoDaOriginal(itens: ItemDoHistorico[], id: string): string {
  const original = itens.find((o) => o.id === id)
  return original ? quando(original.criada_em) : id
}

function ItemDaFilaDeRevisao({
  item,
  rotulo,
  ocupado,
  aoReaplicar,
  aoDescartar,
  aoRefazerAMao,
}: {
  item: ItemDaFila
  rotulo: string
  ocupado: boolean
  aoReaplicar: (candidato: string) => void
  aoDescartar: () => void
  aoRefazerAMao?: () => void
}) {
  const estrutural = item.tipo === 'pauta.juntar' || item.tipo === 'pauta.dividir'
  const [candidato, setCandidato] = useState('')
  const [confirmando, setConfirmando] = useState(false)
  return (
    <div className={CARTAO}>
      <CabecalhoDaCorrecao item={item} rotulo={rotulo} />
      {estrutural && <span className={cn(SELO, 'justify-self-start bg-destructive/12 text-destructive')}>não reaplicada</span>}
      <AntesEDepois item={item} />
      <span className="text-sm">{item.motivo}</span>
      {estrutural ? (
        <p className="text-sm">Nenhuma pauta nova corresponde a esta correção: o modelo refez as pautas. Refaça à mão ou descarte.</p>
      ) : (
        <Rotulo texto="Candidato">
          <select value={candidato} onChange={(e) => setCandidato(e.currentTarget.value)} className={CAMPO}>
            <option value="">{item.candidatos.length ? 'Escolha o item' : 'Sem candidatos'}</option>
            {item.candidatos.map((c) => (
              <option key={c.item_id} value={c.item_id}>
                {`${c.nome} (${relogio(c.inicio_ms)}–${relogio(c.fim_ms)})`}
              </option>
            ))}
          </select>
        </Rotulo>
      )}
      {confirmando ? (
        // Descartar não tem volta: a confirmação fica na própria linha, com o botão de perigo.
        <div
          role="group"
          aria-label="Confirmar o descarte"
          className="flex items-center justify-between gap-2"
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault()
              setConfirmando(false)
            }
          }}
        >
          <span className="text-sm">Descartar esta correção? Ela não volta.</span>
          <div className="flex shrink-0 gap-1">
            <BotaoComDica dica="Esc" variant="secondary" onClick={() => setConfirmando(false)}>
              Cancelar
            </BotaoComDica>
            <Button type="button" size="sm" variant="destructive" aria-busy={ocupado} disabled={ocupado} onClick={aoDescartar}>
              Descartar
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex justify-end gap-1">
          <Button type="button" size="sm" variant="destructive" title="Descartar a correção: ela não volta (pede confirmação)" disabled={ocupado} onClick={() => setConfirmando(true)}>
            Descartar
          </Button>
          {estrutural ? (
            aoRefazerAMao && (
              <Button type="button" size="sm" disabled={ocupado} onClick={aoRefazerAMao}>
                Refazer à mão
              </Button>
            )
          ) : (
            <Button type="button" size="sm" title="Reaplicar no candidato escolhido" aria-busy={ocupado} disabled={!candidato || ocupado} onClick={() => aoReaplicar(candidato)}>
              Reaplicar
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
