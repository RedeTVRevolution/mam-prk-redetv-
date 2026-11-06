import {
  IconArrowLeft,
  IconChevronDown,
  IconChevronRight,
  IconEdit,
  IconFocus2,
  IconLayoutSidebarRightCollapse,
  IconMovie,
  IconPlayerPlay,
  IconPlus,
  IconSearch,
  IconTrash,
} from '@tabler/icons-react'
import { observeElementRect, useVirtualizer } from '@tanstack/react-virtual'
import { cn } from 'cn'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useAtalhos } from '../../atalhos.ts'
import { type Marca, ROTULO_NA_BUSCA } from '../../catalogacao.ts'
import { CORES_DE_OBJETO } from '../../cores.ts'
import type { Decupagem } from '../../decupagem.ts'
import { type Intervalo, relogio, SEM_OBJETOS } from '../../linhaDoTempo.ts'
import {
  contem,
  type DadosDoObjeto,
  type ItemDoPainel,
  inventarioDoVideo,
  itensPorTipo,
  NAO_IDENTIFICADO,
  nomeNormalizado,
  type ObjetoDoVideo,
  objetosDaAba,
  semDecupagemEm,
  type Selo,
  textoDoSemDecupagem,
  vizinhoNoPainel,
} from '../../painel.ts'
import { Button } from '../ui/button.tsx'
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip.tsx'
import { BotaoDeIcone } from './comum.tsx'
import { type Secao, TIPOS, type TipoDaFaixa, tipoDaChave } from './tipos.ts'
import { type Instante, useNoInstante } from './instante.ts'

const SECOES: { chave: Secao; rotulo: string; tipo: TipoDaFaixa; vazio: string }[] = [
  { chave: 'pessoas', rotulo: 'Pessoas', tipo: 'aparicao', vazio: 'Nenhuma pessoa na imagem neste vídeo.' },
  { chave: 'pautas', rotulo: 'Pautas', tipo: 'pauta', vazio: 'Nenhuma pauta neste vídeo.' },
  { chave: 'objetos', rotulo: 'Objetos', tipo: 'objeto', vazio: SEM_OBJETOS },
  { chave: 'comerciais', rotulo: 'Comerciais', tipo: 'comercial', vazio: 'Nenhum comercial neste vídeo.' },
  { chave: 'textos', rotulo: 'Textos na tela', tipo: 'texto', vazio: 'Nenhum texto na tela neste vídeo.' },
  { chave: 'mencoes', rotulo: 'Menções', tipo: 'mencao', vazio: 'Nenhuma menção neste vídeo.' },
  { chave: 'falas', rotulo: 'Falas', tipo: 'fala', vazio: 'Este vídeo não tem transcrição.' },
]

const GRUPO = 'Inspetor'

/** Correção pelo inspetor, para quem edita com o catálogo carregado. */
export interface AcoesDeCorrecao {
  podeCorrigir: (i: ItemDoPainel) => boolean
  podeRemover: (i: ItemDoPainel) => boolean
  corrigir: (i: ItemDoPainel) => void
  remover: (i: ItemDoPainel) => void
  acrescentar: (pessoa: string) => void
  /** O formulário (ou a confirmação) aberto: a chave do item, ou `acrescentar:<pessoa>`. */
  edicao: { chave: string; conteudo: ReactNode } | null
  /** "aguardando o Curador", "indexando", "na busca", por chave de item. */
  marcas?: Record<string, Marca>
}

type Linha =
  | { tipo: 'item'; chave: string; item: ItemDoPainel; recuo: boolean }
  | { tipo: 'pessoa'; chave: string; id: string; nome: string; apoio: string | null; aparicoes: ItemDoPainel[]; aberta: boolean }
  | { tipo: 'objeto'; chave: string; dados: DadosDoObjeto; ocorrencias: ItemDoPainel[]; aberta: boolean }
  // O inventário dos planos: a categoria, o objeto (que abre os planos em que aparece) e o plano.
  | { tipo: 'categoria'; chave: string; nome: string }
  | { tipo: 'inventario'; chave: string; objeto: ObjetoDoVideo; aberta: boolean }
  | { tipo: 'plano'; chave: string; plano: ObjetoDoVideo['planos'][number] }

type Inventario = ReturnType<typeof inventarioDoVideo>

const ALTURA_ESTIMADA: Record<Linha['tipo'], number> = { item: 44, pessoa: 52, objeto: 60, categoria: 28, inventario: 52, plano: 32 }

const tempos = (i: Intervalo): string => `${relogio(i.inicio_ms)}–${relogio(i.fim_ms)}`

/** O selo do palpite sem prova, quando o nome é um. */
const naoConfirmado = (selos: Selo[]): Selo | undefined => selos.find((s) => s.tipo === 'nao_confirmado')

/** O nome e, no palpite, ", não confirmado": o leitor de tela ouve o selo junto do nome. */
const comSelo = (titulo: string, selos: Selo[]): string => {
  const selo = naoConfirmado(selos)
  return selo ? `${titulo}, ${selo.rotulo}` : titulo
}

const nomeDoItem = (i: ItemDoPainel): string =>
  i.tipo === 'fala'
    ? `${i.linhas[0] ? `${i.linhas[0]}: ` : ''}${i.titulo}, ${relogio(i.inicio_ms)}`
    : `${comSelo(i.titulo, i.selos)}, ${relogio(i.inicio_ms)} a ${relogio(i.fim_ms)}`

const casa = (texto: string, filtro: string) => !filtro || nomeNormalizado(texto).includes(filtro)
const textoDoItem = (i: ItemDoPainel) => [i.titulo, i.rotulo ?? '', ...i.linhas].join(' ')

/** As linhas da seção, na ordem da tela: pessoas e objetos agrupam as ocorrências, que abrem no clique. */
function linhasDaSecao(
  secao: Secao,
  d: Decupagem,
  porTipo: Map<string, ItemDoPainel[]>,
  inventario: Inventario,
  abertas: ReadonlySet<string>,
  filtro: string,
): Linha[] {
  const doTipo = (t: string) => porTipo.get(t) ?? []
  const item = (i: ItemDoPainel, recuo = false): Linha => ({ tipo: 'item', chave: i.chave, item: i, recuo })
  if (secao === 'pessoas') {
    const linhas: Linha[] = []
    for (const p of d.pessoas) {
      const aparicoes = doTipo('aparicao').filter((i) => i.pessoa === p.id)
      if (aparicoes.length === 0) continue
      const nome = aparicoes[0].titulo
      if (!casa(`${p.nome} ${nome}`, filtro)) continue
      const aberta = abertas.has(`pessoa:${p.id}`)
      linhas.push({ tipo: 'pessoa', chave: `pessoa:${p.id}`, id: p.id, nome, apoio: nome === NAO_IDENTIFICADO ? (aparicoes[0].linhas[0] ?? null) : null, aparicoes, aberta })
      if (aberta) linhas.push(...aparicoes.map((a) => item(a, true)))
    }
    return linhas
  }
  if (secao === 'objetos') {
    const linhas: Linha[] = []
    for (const o of objetosDaAba([...porTipo.values()].flat())) {
      if (!casa(`${o.dados.tipo} ${o.dados.tom} ${o.dados.marca ?? ''} ${o.dados.dono?.nome ?? ''}`, filtro)) continue
      const aberta = abertas.has(`objeto:${o.dados.id}`)
      linhas.push({ tipo: 'objeto', chave: `objeto:${o.dados.id}`, dados: o.dados, ocorrencias: o.ocorrencias, aberta })
      if (aberta) linhas.push(...o.ocorrencias.map((x) => item(x, true)))
    }
    for (const g of inventario) {
      const objetos = g.objetos.filter((o) => casa(`${o.nome} ${o.cor ?? ''} ${o.marca ?? ''} ${g.nome}`, filtro))
      if (objetos.length > 0) linhas.push({ tipo: 'categoria', chave: `categoria:${g.categoria}`, nome: g.nome })
      for (const o of objetos) {
        const chave = `inventario:${o.chave}`
        const aberta = abertas.has(chave)
        linhas.push({ tipo: 'inventario', chave, objeto: o, aberta })
        if (aberta) linhas.push(...o.planos.map((plano): Linha => ({ tipo: 'plano', chave: `${chave}:${plano.id}`, plano })))
      }
    }
    return linhas
  }
  const tipo = SECOES.find((s) => s.chave === secao)?.tipo ?? 'pauta'
  return doTipo(tipo)
    .filter((i) => casa(textoDoItem(i), filtro))
    .map((i) => item(i))
}

/** O tempo está numa linha: o item, ou uma das ocorrências da pessoa ou do objeto. */
function linhaNoTempo(l: Linha, ms: number): boolean {
  if (l.tipo === 'item') return contem(l.item, ms)
  if (l.tipo === 'categoria') return false
  if (l.tipo === 'plano') return contem(l.plano, ms)
  return (l.tipo === 'pessoa' ? l.aparicoes : l.tipo === 'objeto' ? l.ocorrencias : l.objeto.planos).some((i) => contem(i, ms))
}

/** O que a lista mede no jsdom e num painel ainda sem altura: uma janela de 600 px, para desenhar as primeiras linhas. */
const medirComFolga: typeof observeElementRect = (instancia, aviso) =>
  observeElementRect(instancia, (r) => aviso(r.height > 0 ? r : { width: r.width, height: 600 }))

/**
 * O inspetor (MAM_DESIGN_SYSTEM 10): o "Agora" no instante do vídeo e as seções por tipo, uma aberta
 * por vez, com filtro e "seguir a reprodução". Clicar num item abre o detalhe no próprio inspetor.
 */
export function Inspetor({
  decupagem: d,
  carregando,
  itens,
  instante,
  duracaoMs,
  secao,
  aoTrocarSecao,
  selecionada,
  detalhe,
  aoAbrir,
  aoMover,
  aoFecharDetalhe,
  aoSaltar,
  aoTocarTrecho,
  urlDoQuadro,
  acoes,
  aviso,
  acima,
  indexando,
  aoRecolher,
}: {
  decupagem: Decupagem | undefined
  carregando: boolean
  itens: ItemDoPainel[]
  instante: Instante
  duracaoMs: number
  secao: Secao | null
  aoTrocarSecao: (s: Secao | null) => void
  selecionada: string | null
  detalhe: boolean
  /** Abre o item (seção e detalhe); `saltar` leva o player ao início dele. */
  aoAbrir: (chave: string, saltar: boolean) => void
  /** Troca o item selecionado sem saltar (as setas). */
  aoMover: (chave: string) => void
  aoFecharDetalhe: () => void
  aoSaltar: (ms: number) => void
  aoTocarTrecho: (i: Intervalo) => void
  urlDoQuadro: (caminho: string) => Promise<string>
  acoes?: AcoesDeCorrecao
  aviso: string | null
  /** O que a revisão põe acima do "Agora": as sugestões, as pautas marcadas. */
  acima?: ReactNode
  indexando: boolean
  aoRecolher: () => void
}) {
  const porTipo = useMemo(() => itensPorTipo(itens), [itens])
  const inventario = useMemo(() => (d ? inventarioDoVideo(d.planos) : []), [d])
  const [abertas, setAbertas] = useState<ReadonlySet<string>>(new Set())
  const [filtro, setFiltro] = useState('')
  const [seguir, setSeguir] = useState(true)
  const selecionado = itens.find((i) => i.chave === selecionada)

  // O item selecionado de fora (na linha do tempo ou no Agora) abre a pessoa ou o objeto dele; depois fecha no clique.
  const grupoDoSelecionado = selecionado?.pessoa ? `pessoa:${selecionado.pessoa}` : selecionado?.objeto ? `objeto:${selecionado.objeto.id}` : null
  const [grupoVisto, setGrupoVisto] = useState<string | null>(null)
  if (grupoDoSelecionado !== grupoVisto) {
    setGrupoVisto(grupoDoSelecionado)
    if (grupoDoSelecionado && !abertas.has(grupoDoSelecionado)) setAbertas(new Set(abertas).add(grupoDoSelecionado))
  }

  const filtroNormalizado = nomeNormalizado(filtro)
  const linhas = useMemo(
    () => (d && secao ? linhasDaSecao(secao, d, porTipo, inventario, abertas, filtroNormalizado) : []),
    [d, secao, porTipo, inventario, abertas, filtroNormalizado],
  )
  const navegaveis = useMemo(() => linhas.flatMap((l) => (l.tipo === 'item' ? [l.chave] : [])), [linhas])

  const alternarGrupo = (chave: string) =>
    setAbertas((a) => {
      const novas = new Set(a)
      if (!novas.delete(chave)) novas.add(chave)
      return novas
    })

  const indiceDaSecao = SECOES.findIndex((s) => s.chave === secao)
  useAtalhos([
    {
      tecla: '↑ ↓',
      acao: 'No inspetor: mover a seleção na seção aberta',
      grupo: GRUPO,
      casa: (e) => e.key === 'ArrowUp' || e.key === 'ArrowDown',
      executar: (e) => {
        const chave = vizinhoNoPainel(navegaveis, selecionada, e.key === 'ArrowUp' ? -1 : 1)
        if (chave) aoMover(chave)
      },
    },
    {
      tecla: 'Enter',
      acao: 'No inspetor: saltar o player ao item selecionado',
      grupo: GRUPO,
      // Com o foco num botão ou link, o Enter faz o que o elemento faz; menos no próprio item, em que
      // o foco pode ter ficado enquanto as setas moveram a seleção.
      casa: (e) => e.key === 'Enter' && !(e.target instanceof HTMLElement && e.target.closest('button:not([data-item]), a, [role=slider]')),
      executar: () => {
        if (selecionado) aoSaltar(selecionado.inicio_ms)
      },
    },
    {
      tecla: 'Ctrl + ← →',
      acao: 'No inspetor: trocar de seção',
      grupo: GRUPO,
      ctrl: true,
      casa: (e) => e.key === 'ArrowLeft' || e.key === 'ArrowRight',
      executar: (e) => {
        const i = Math.min(Math.max(indiceDaSecao + (e.key === 'ArrowLeft' ? -1 : 1), 0), SECOES.length - 1)
        aoTrocarSecao(SECOES[i].chave)
        setFiltro('')
      },
    },
    {
      tecla: 'Esc',
      acao: 'No inspetor: voltar do detalhe à lista',
      grupo: GRUPO,
      casa: (e) => e.key === 'Escape' && detalhe,
      executar: aoFecharDetalhe,
    },
  ])

  const contagem = (s: Secao): number => {
    if (s === 'pessoas') return new Set((porTipo.get('aparicao') ?? []).map((i) => i.pessoa)).size
    if (s === 'objetos') return new Set((porTipo.get('objeto') ?? []).map((i) => i.objeto?.id)).size + inventario.reduce((n, g) => n + g.objetos.length, 0)
    return porTipo.get(SECOES.find((x) => x.chave === s)?.tipo ?? '')?.length ?? 0
  }

  return (
    <aside
      aria-label="Inspetor"
      className="flex h-[80dvh] w-full shrink-0 flex-col overflow-y-auto bg-background lg:h-auto lg:min-h-0 lg:w-[400px] xl:w-[420px]"
    >
      <div className="flex h-8 shrink-0 items-center gap-2 border-b bg-card px-3">
        <h2 className="min-w-0 flex-1 truncate text-xs font-semibold">Inspetor</h2>
        {indexando && (
          <span role="status" className="text-xs text-muted-foreground">
            Atualizando o índice…
          </span>
        )}
        <BotaoDeIcone rotulo="Recolher o inspetor" atalho="]" className="-mr-1.5" onClick={aoRecolher}>
          <IconLayoutSidebarRightCollapse size={16} stroke={1.75} aria-hidden />
        </BotaoDeIcone>
      </div>
      {aviso && (
        <p role="status" className="shrink-0 border-b px-3 py-2 text-sm">
          {aviso}
        </p>
      )}
      {!d ? (
        <p className="p-8 text-center text-sm text-muted-foreground">
          {carregando ? 'Carregando a decupagem…' : 'O inspetor aparece quando a decupagem estiver pronta.'}
        </p>
      ) : (
        <>
          {acima}
          <Agora decupagem={d} porTipo={porTipo} instante={instante} duracaoMs={duracaoMs} urlDoQuadro={urlDoQuadro} aoAbrir={aoAbrir} />
          {detalhe && selecionado ? (
            <Detalhe
              key={selecionado.chave}
              item={selecionado}
              itens={itens}
              aoVoltar={aoFecharDetalhe}
              aoSaltar={aoSaltar}
              aoTocarTrecho={aoTocarTrecho}
              aoAbrir={aoAbrir}
              urlDoQuadro={urlDoQuadro}
              acoes={acoes}
            />
          ) : (
            // A seção aberta tem um mínimo explícito (cabeçalho, barra e 8rem de lista): ela não passa por
            // cima das de baixo, e o inspetor rola quando falta altura. Um mínimo pelo conteúdo valeria a
            // lista inteira, e a lista virtual desenharia todas as linhas.
            <div className="flex min-h-0 flex-1 flex-col">
              {SECOES.map((s) => {
                const { Icone, cor } = TIPOS[s.tipo]
                const aberta = secao === s.chave
                return (
                  <section key={s.chave} aria-label={s.rotulo} className={cn('flex flex-col border-b', aberta && 'min-h-52 flex-1')}>
                    <button
                      type="button"
                      aria-expanded={aberta}
                      onClick={() => {
                        aoTrocarSecao(aberta ? null : s.chave)
                        setFiltro('')
                      }}
                      className={cn('flex h-9 shrink-0 items-center gap-2 px-3 text-left text-sm font-medium hover:bg-card', aberta && 'bg-card')}
                    >
                      <Icone size={16} stroke={1.75} style={{ color: cor }} aria-hidden />
                      {s.rotulo}{' '}
                      <span className="font-normal text-muted-foreground tabular-nums">{contagem(s.chave)}</span>
                      <IconChevronDown size={16} aria-hidden className={cn('ml-auto text-muted-foreground transition-transform motion-reduce:transition-none', aberta && 'rotate-180')} />
                    </button>
                    {aberta && (
                      <div className="flex min-h-40 flex-1 flex-col">
                        <div className="flex h-10 shrink-0 items-center gap-2 border-y px-2">
                          <label className="flex h-7 min-w-0 flex-1 items-center gap-1.5 rounded-sm border border-strong bg-input px-2 text-muted-foreground focus-within:border-primary">
                            <IconSearch size={14} aria-hidden />
                            <input
                              value={filtro}
                              aria-label={`Filtrar ${s.rotulo.toLowerCase()}`}
                              placeholder="Filtrar a lista…"
                              onChange={(e) => setFiltro(e.target.value)}
                              className="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
                            />
                          </label>
                          <BotaoDeIcone rotulo={seguir ? 'Seguindo a reprodução' : 'Seguir a reprodução'} ativo={seguir} onClick={() => setSeguir(!seguir)}>
                            <IconFocus2 size={18} stroke={1.75} aria-hidden />
                          </BotaoDeIcone>
                        </div>
                        {linhas.length === 0 ? (
                          <p className="px-3 py-8 text-center text-sm text-muted-foreground">
                            {filtro ? `Nada com “${filtro}” em ${s.rotulo.toLowerCase()}.` : s.vazio}
                          </p>
                        ) : (
                          <Lista
                            linhas={linhas}
                            instante={instante}
                            selecionada={selecionada}
                            seguir={seguir}
                            aoSeguir={setSeguir}
                            centro={s.chave === 'falas'}
                            renderizar={(l, atual) =>
                              l.tipo === 'item' ? (
                                <ItemDaLista
                                  item={l.item}
                                  recuo={l.recuo}
                                  atual={atual}
                                  selecionado={l.chave === selecionada}
                                  marca={acoes?.marcas?.[l.chave]}
                                  urlDoQuadro={urlDoQuadro}
                                  aoAbrir={() => aoAbrir(l.chave, true)}
                                />
                              ) : l.tipo === 'pessoa' ? (
                                <LinhaDaPessoa linha={l} atual={atual} duracaoMs={duracaoMs} urlDoQuadro={urlDoQuadro} aoAlternar={() => alternarGrupo(l.chave)} />
                              ) : l.tipo === 'objeto' ? (
                                <LinhaDoObjeto linha={l} atual={atual} urlDoQuadro={urlDoQuadro} aoAlternar={() => alternarGrupo(l.chave)} />
                              ) : l.tipo === 'categoria' ? (
                                <h3 className="border-b border-border/60 px-3 pt-3 pb-1 text-xs font-semibold text-muted-foreground">{l.nome} nos planos</h3>
                              ) : l.tipo === 'inventario' ? (
                                <LinhaDoInventario
                                  linha={l}
                                  atual={atual}
                                  urlDoQuadro={urlDoQuadro}
                                  aoAlternar={() => {
                                    if (!l.aberta) aoSaltar(l.objeto.planoDaCaixa.inicio_ms)
                                    alternarGrupo(l.chave)
                                  }}
                                />
                              ) : (
                                <button
                                  type="button"
                                  onClick={() => aoSaltar(l.plano.inicio_ms)}
                                  className={cn('relative flex w-full border-b border-border/60 py-1.5 pr-3 pl-8 text-left text-xs text-muted-foreground hover:bg-card', atual && ATUAL)}
                                >
                                  {`${l.plano.ambiente} · ${relogio(l.plano.inicio_ms)}`}
                                </button>
                              )
                            }
                          />
                        )}
                      </div>
                    )}
                  </section>
                )
              })}
            </div>
          )}
        </>
      )}
    </aside>
  )
}

/** A lista virtual da seção aberta: só as linhas à vista existem, e a seleção e o item atual entram na vista. */
function Lista({
  linhas,
  instante,
  selecionada,
  seguir,
  aoSeguir,
  centro,
  renderizar,
}: {
  linhas: Linha[]
  instante: Instante
  selecionada: string | null
  seguir: boolean
  aoSeguir: (v: boolean) => void
  /** As falas acompanham no meio da lista; as outras seções, só entrando na vista. */
  centro: boolean
  renderizar: (l: Linha, atual: boolean) => ReactNode
}) {
  const rolagem = useRef<HTMLDivElement>(null)
  // oxlint-disable-next-line react/incompatible-library
  const virtual = useVirtualizer({
    count: linhas.length,
    getScrollElement: () => rolagem.current,
    estimateSize: (i) => ALTURA_ESTIMADA[linhas[i].tipo],
    getItemKey: (i) => linhas[i].chave,
    overscan: 6,
    observeElementRect: medirComFolga,
    useFlushSync: false,
  })
  // As linhas no tempo do vídeo, numa string: a lista só renderiza de novo quando elas mudam.
  const atuais = useNoInstante(instante, (ms) => linhas.filter((l) => linhaNoTempo(l, ms)).map((l) => l.chave).join('\n'))
  const conjunto = useMemo(() => new Set(atuais.split('\n')), [atuais])
  // Com o grupo aberto, a lista vai à ocorrência atual, não ao cabeçalho, que fica no tempo do grupo
  // inteiro; com ele fechado, vai ao cabeçalho.
  const ocorrenciaAtual = linhas.findIndex((l) => conjunto.has(l.chave) && !('aberta' in l && l.aberta))
  const primeiraAtual = ocorrenciaAtual >= 0 ? ocorrenciaAtual : linhas.findIndex((l) => conjunto.has(l.chave))

  useEffect(() => {
    if (seguir && primeiraAtual >= 0) virtual.scrollToIndex(primeiraAtual, { align: centro ? 'center' : 'auto' })
  }, [seguir, primeiraAtual, centro, virtual])
  const indiceDaSelecao = linhas.findIndex((l) => l.chave === selecionada)
  useEffect(() => {
    if (indiceDaSelecao >= 0) virtual.scrollToIndex(indiceDaSelecao, { align: 'auto' })
  }, [indiceDaSelecao, virtual])

  // Rolar à mão desliga o seguir; o botão "Voltar ao tempo atual" religa.
  const rolouAMao = () => {
    if (seguir) aoSeguir(false)
  }
  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div
        ref={rolagem}
        className="min-h-0 flex-1 overflow-y-auto"
        onWheel={rolouAMao}
        onTouchMove={rolouAMao}
        onPointerDown={(e) => {
          // A barra de rolagem: o ponteiro no próprio contêiner, não numa linha.
          if (e.target === e.currentTarget) rolouAMao()
        }}
      >
        <ul className="relative w-full" style={{ height: virtual.getTotalSize() }}>
          {virtual.getVirtualItems().map((v) => {
            const l = linhas[v.index]
            return (
              <li key={v.key} data-index={v.index} ref={virtual.measureElement} className="absolute inset-x-0 top-0" style={{ transform: `translateY(${v.start}px)` }}>
                {renderizar(l, conjunto.has(l.chave))}
              </li>
            )
          })}
        </ul>
      </div>
      {!seguir && primeiraAtual >= 0 && (
        <button
          type="button"
          onClick={() => aoSeguir(true)}
          className="absolute bottom-2 left-1/2 flex h-7 -translate-x-1/2 items-center gap-1.5 rounded-sm border bg-popover px-2.5 text-xs shadow-float hover:bg-accent"
        >
          <IconFocus2 size={14} aria-hidden /> Voltar ao tempo atual
        </button>
      )}
    </div>
  )
}

/** A miniatura do quadro: a URL assinada só é pedida quando a linha existe, e a lista é virtual. */
function Miniatura({ caminho, urlDoQuadro, className }: { caminho: string | null | undefined; urlDoQuadro: (c: string) => Promise<string>; className?: string }) {
  const [achada, setAchada] = useState<{ caminho: string; url: string } | null>(null)
  useEffect(() => {
    if (!caminho) return
    let ativo = true
    urlDoQuadro(caminho).then(
      (url) => ativo && setAchada({ caminho, url }),
      () => {},
    )
    return () => {
      ativo = false
    }
  }, [caminho, urlDoQuadro])
  const url = achada && achada.caminho === caminho ? achada.url : null
  return (
    <span aria-hidden className={cn('block shrink-0 overflow-hidden rounded-xs bg-input', className)}>
      {url && <img src={url} alt="" loading="lazy" className="size-full object-cover" />}
    </span>
  )
}

const ATUAL = 'bg-card before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-primary'

function SeloDaMarca({ marca }: { marca: Marca }) {
  const andando = marca.pendente || marca.na_busca === 'indexando'
  return (
    <span
      title={marca.dica}
      className={cn('inline-flex h-5 shrink-0 items-center rounded-xs px-1.5 text-xs font-medium whitespace-nowrap', andando ? 'bg-andamento/12 text-andamento' : 'bg-ok/12 text-ok')}
    >
      {marca.pendente ? 'aguardando o Curador' : ROTULO_NA_BUSCA[marca.na_busca]}
    </span>
  )
}

function ItemDaLista({
  item,
  recuo,
  atual,
  selecionado,
  marca,
  urlDoQuadro,
  aoAbrir,
}: {
  item: ItemDoPainel
  recuo: boolean
  atual: boolean
  selecionado: boolean
  marca?: Marca
  urlDoQuadro: (c: string) => Promise<string>
  aoAbrir: () => void
}) {
  const { cor } = TIPOS[item.tipo as TipoDaFaixa] ?? TIPOS.pauta
  const apoio = [item.tipo === 'texto' ? null : item.rotulo, ...item.linhas].filter(Boolean)
  return (
    <div data-chave={item.chave} aria-current={atual ? 'true' : undefined} className={cn('relative border-b border-border/60', atual && ATUAL, selecionado && 'bg-selected')}>
      <button
        type="button"
        data-item=""
        aria-label={nomeDoItem(item)}
        aria-pressed={selecionado}
        onClick={aoAbrir}
        className={cn('flex w-full items-start gap-2 py-1.5 pr-3 text-left hover:bg-card', recuo ? 'pl-8' : 'pl-3')}
      >
        <span className={cn('mt-0.5 w-12 shrink-0 font-mono text-xs tabular-nums', atual ? 'text-link' : 'text-muted-foreground')}>{relogio(item.inicio_ms)}</span>
        {item.quadro !== undefined && !recuo ? (
          <Miniatura caminho={item.quadro} urlDoQuadro={urlDoQuadro} className="h-9 w-16" />
        ) : (
          <span aria-hidden className="mt-1.5 size-2 shrink-0 rounded-full" style={{ background: cor }} />
        )}
        <span className="min-w-0 flex-1">
          <span className={cn('block text-sm leading-snug', item.tipo === 'fala' ? 'line-clamp-3' : 'truncate', item.titulo === NAO_IDENTIFICADO && 'text-muted-foreground italic')}>
            {item.tipo === 'texto' && item.rotulo && <span className="mr-1.5 text-xs font-medium text-muted-foreground">{item.rotulo}</span>}
            {item.titulo}
            {item.tipo === 'aparicao' && <SeloNaLinha selos={item.selos} className="ml-1.5" />}
          </span>
          {apoio.map((l) => (
            <span key={l} className={cn('block text-xs text-muted-foreground', item.tipo === 'pauta' ? 'line-clamp-2' : 'truncate')}>
              {l}
            </span>
          ))}
          {item.tipo !== 'fala' && <span className="block font-mono text-xs text-muted-foreground tabular-nums">{tempos(item)}</span>}
        </span>
        {marca && <SeloDaMarca marca={marca} />}
      </button>
    </div>
  )
}

/** A presença ao longo do vídeo, num `<path>` só (como as faixas). */
function Presenca({ ocorrencias, duracaoMs }: { ocorrencias: Intervalo[]; duracaoMs: number }) {
  const d = ocorrencias.map((o) => `M${Math.round(o.inicio_ms)} 0h${Math.max(Math.round(o.fim_ms - o.inicio_ms), 0)}v1h${-Math.max(Math.round(o.fim_ms - o.inicio_ms), 0)}z`).join('')
  return (
    <svg aria-hidden className="mt-1 block h-1.5 w-full rounded-xs bg-input" viewBox={`0 0 ${Math.max(duracaoMs, 1)} 1`} preserveAspectRatio="none">
      <path d={d} fill="var(--color-tipo-aparicao)" stroke="var(--color-tipo-aparicao)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

function LinhaDaPessoa({
  linha,
  atual,
  duracaoMs,
  urlDoQuadro,
  aoAlternar,
}: {
  linha: Extract<Linha, { tipo: 'pessoa' }>
  atual: boolean
  duracaoMs: number
  urlDoQuadro: (c: string) => Promise<string>
  aoAlternar: () => void
}) {
  const n = linha.aparicoes.length
  const quantas = `${n} ${n === 1 ? 'aparição' : 'aparições'}`
  const total = linha.aparicoes.reduce((s, a) => s + (a.fim_ms - a.inicio_ms), 0)
  const semNome = linha.nome === NAO_IDENTIFICADO
  return (
    <button
      type="button"
      aria-expanded={linha.aberta}
      aria-label={`${comSelo(linha.nome, linha.aparicoes[0].selos)}, ${quantas}`}
      onClick={aoAlternar}
      className={cn('relative flex w-full items-center gap-2 border-b border-border/60 px-3 py-1.5 text-left hover:bg-card', atual && ATUAL)}
    >
      <Miniatura caminho={linha.aparicoes.find((a) => a.quadro)?.quadro} urlDoQuadro={urlDoQuadro} className="size-9 rounded-sm" />
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className={cn('truncate text-sm font-medium', semNome && 'font-normal text-muted-foreground italic')}>{linha.nome}</span>
          <SeloNaLinha selos={linha.aparicoes[0].selos} />
        </span>
        {linha.apoio && <span className="block truncate text-xs text-muted-foreground">{linha.apoio}</span>}
        <Presenca ocorrencias={linha.aparicoes} duracaoMs={duracaoMs} />
      </span>
      <span className="w-20 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
        {relogio(total)}
        <span className="block">{quantas}</span>
      </span>
      <IconChevronRight size={14} aria-hidden className={cn('shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none', linha.aberta && 'rotate-90')} />
    </button>
  )
}

/** O quadradinho da cor base e o tom em palavras: a cor nunca vem sem a palavra. */
function CorDoObjeto({ dados }: { dados: DadosDoObjeto }) {
  return (
    <span className="flex items-center gap-1.5">
      {dados.coresBase.slice(0, 2).map((c) => (
        <span key={c} aria-hidden data-cor-base={c} className="size-2.5 shrink-0 rounded-xs border border-muted-foreground" style={{ background: CORES_DE_OBJETO[c] }} />
      ))}
      {dados.tom && <span className="text-xs">{dados.tom}</span>}
    </span>
  )
}

function LinhaDoObjeto({
  linha,
  atual,
  urlDoQuadro,
  aoAlternar,
}: {
  linha: Extract<Linha, { tipo: 'objeto' }>
  atual: boolean
  urlDoQuadro: (c: string) => Promise<string>
  aoAlternar: () => void
}) {
  const n = linha.ocorrencias.length
  const quantas = `${n} ${n === 1 ? 'ocorrência' : 'ocorrências'}`
  const { dados } = linha
  return (
    <button
      type="button"
      aria-expanded={linha.aberta}
      aria-label={`${dados.tipo}, ${quantas}`}
      onClick={aoAlternar}
      className={cn('relative flex w-full items-start gap-2 border-b border-border/60 px-3 py-1.5 text-left hover:bg-card', atual && ATUAL)}
    >
      <Miniatura caminho={linha.ocorrencias[0]?.quadro} urlDoQuadro={urlDoQuadro} className="h-9 w-16" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{dados.tipo}</span>
        <CorDoObjeto dados={dados} />
        <span className="block truncate text-xs text-muted-foreground">
          {[dados.categoria !== 'em cena' || dados.dono ? dados.categoria : null, dados.dono ? `de ${dados.dono.nome}` : 'em cena', dados.marca && `marca ${dados.marca}`]
            .filter(Boolean)
            .join(' · ')}
        </span>
      </span>
      <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{quantas}</span>
      <IconChevronRight size={14} aria-hidden className={cn('mt-1 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none', linha.aberta && 'rotate-90')} />
    </button>
  )
}

/** O objeto do inventário dos planos: abrir lista os planos em que aparece e leva o player ao da maior caixa. */
function LinhaDoInventario({
  linha,
  atual,
  urlDoQuadro,
  aoAlternar,
}: {
  linha: Extract<Linha, { tipo: 'inventario' }>
  atual: boolean
  urlDoQuadro: (c: string) => Promise<string>
  aoAlternar: () => void
}) {
  const { objeto } = linha
  const detalhes = [objeto.cor, objeto.marca].filter(Boolean).join(' · ')
  const nome = detalhes ? `${objeto.nome} (${detalhes})` : objeto.nome
  const quantos = `${objeto.planos.length} ${objeto.planos.length === 1 ? 'plano' : 'planos'}`
  return (
    <button
      type="button"
      aria-expanded={linha.aberta}
      aria-label={`${nome}, ${quantos}`}
      onClick={aoAlternar}
      className={cn('relative flex w-full items-center gap-2 border-b border-border/60 px-3 py-1.5 text-left hover:bg-card', atual && ATUAL)}
    >
      <Miniatura caminho={objeto.caixa.quadro} urlDoQuadro={urlDoQuadro} className="h-9 w-16" />
      <span className="min-w-0 flex-1 truncate text-sm">
        {objeto.nome}
        {detalhes && <span className="text-xs text-muted-foreground"> ({detalhes})</span>}
      </span>
      <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{quantos}</span>
      <IconChevronRight size={14} aria-hidden className={cn('shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none', linha.aberta && 'rotate-90')} />
    </button>
  )
}

// ---------- Agora ----------

/** As chaves do que está na tela no instante, numa string: o Agora só renderiza de novo quando elas mudam. */
function chavesDoAgora(d: Decupagem, porTipo: Map<string, ItemDoPainel[]>, duracaoMs: number, ms: number): string {
  const pautas = porTipo.get('pauta') ?? []
  const pauta = pautas.find((p) => contem(p, ms))
  const vazio = pauta ? null : semDecupagemEm(pautas, duracaoMs, ms)
  const chaves = [pauta?.chave ?? (vazio ? `vazio:${vazio.inicio_ms}:${vazio.fim_ms}` : '')]
  for (const t of ['plano', 'aparicao', 'mencao', 'objeto', 'comercial', 'texto', 'fala']) {
    for (const i of porTipo.get(t) ?? []) if (contem(i, ms)) chaves.push(i.chave)
  }
  void d
  return chaves.join('\n')
}

function RelogioDoAgora({ instante }: { instante: Instante }) {
  return <span className="font-mono text-xs text-muted-foreground tabular-nums">{useNoInstante(instante, relogio)}</span>
}

function LinhaDoAgora({ tipo, rotulo, children }: { tipo: TipoDaFaixa; rotulo: string; children: ReactNode }) {
  const { Icone, cor } = TIPOS[tipo]
  return (
    <div className="flex min-h-7 items-start gap-2 py-1">
      <Icone size={16} stroke={1.75} className="mt-0.5 shrink-0" style={{ color: cor }} aria-label={rotulo} role="img" />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

function Agora({
  decupagem,
  porTipo,
  instante,
  duracaoMs,
  urlDoQuadro,
  aoAbrir,
}: {
  decupagem: Decupagem
  porTipo: Map<string, ItemDoPainel[]>
  instante: Instante
  duracaoMs: number
  urlDoQuadro: (c: string) => Promise<string>
  aoAbrir: (chave: string, saltar: boolean) => void
}) {
  const chaves = useNoInstante(instante, (ms) => chavesDoAgora(decupagem, porTipo, duracaoMs, ms))
  const porChave = useMemo(() => new Map([...porTipo.values()].flat().map((i) => [i.chave, i])), [porTipo])
  const lista = chaves.split('\n')
  const doTipo = (t: string) => lista.flatMap((c) => (c.startsWith(`${t}-`) && porChave.has(c) ? [porChave.get(c) as ItemDoPainel] : []))
  const pauta = porChave.get(lista[0])
  const vazio = lista[0].startsWith('vazio:') ? lista[0].split(':').slice(1).map(Number) : null
  const plano = doTipo('plano')[0]
  const pessoas = doTipo('aparicao')
  const mencoes = doTipo('mencao')
  const objetos = doTipo('objeto')
  const comerciais = doTipo('comercial')
  const textos = doTipo('texto')
  const fala = doTipo('fala')[0]
  const abrir = (i: ItemDoPainel) => () => aoAbrir(i.chave, false)
  const link = 'text-left hover:underline'
  const vazia = (texto: string) => <span className="text-xs text-muted-foreground">{texto}</span>
  return (
    <section aria-label="Agora no vídeo" className="shrink-0 border-b px-3 py-2">
      <div className="mb-1 flex items-baseline gap-2">
        <h3 className="text-xs font-semibold">Agora</h3>
        <RelogioDoAgora instante={instante} />
      </div>
      <LinhaDoAgora tipo="pauta" rotulo="Pauta">
        {pauta ? (
          <button type="button" onClick={abrir(pauta)} className={cn(link, 'text-sm font-medium')}>
            {pauta.rotulo ? `${pauta.titulo} · ${pauta.rotulo}` : pauta.titulo}
          </button>
        ) : vazio ? (
          vazia(textoDoSemDecupagem({ inicio_ms: vazio[0], fim_ms: vazio[1] }))
        ) : (
          vazia('Fora de pauta')
        )}
        {plano && (
          <p className="flex items-center gap-1 text-xs text-muted-foreground">
            <IconMovie size={12} stroke={1.75} aria-hidden />
            {plano.linhas[0] ? `${plano.titulo}, ${plano.linhas[0]}` : plano.titulo}
          </p>
        )}
      </LinhaDoAgora>
      <LinhaDoAgora tipo="aparicao" rotulo="Pessoas na imagem">
        {pessoas.length ? (
          <div className="flex flex-wrap gap-1">
            {pessoas.map((p) => (
              <button
                key={p.chave}
                type="button"
                onClick={abrir(p)}
                className="flex h-8 max-w-full items-center gap-1.5 rounded-sm border border-strong bg-card pr-2 text-xs hover:border-muted-foreground"
              >
                <Miniatura caminho={p.quadro} urlDoQuadro={urlDoQuadro} className="h-full w-11 rounded-l-sm rounded-r-none" />
                <span className={cn('max-w-36 truncate', p.titulo === NAO_IDENTIFICADO && 'text-muted-foreground italic')}>{p.titulo}</span>
                <SeloNaLinha selos={p.selos} />
              </button>
            ))}
          </div>
        ) : (
          vazia('Ninguém na imagem')
        )}
      </LinhaDoAgora>
      {mencoes.length > 0 && (
        <LinhaDoAgora tipo="mencao" rotulo="Menções">
          <p className="text-sm leading-snug">
            {mencoes.map((m, i) => (
              <span key={m.chave}>
                {i > 0 && <span className="text-muted-foreground">, </span>}
                <button type="button" onClick={abrir(m)} className={link}>
                  {m.titulo}
                </button>
              </span>
            ))}
          </p>
        </LinhaDoAgora>
      )}
      {objetos.length > 0 && (
        <LinhaDoAgora tipo="objeto" rotulo="Objetos">
          <p className="text-sm leading-snug">
            {objetos.slice(0, 4).map((o, i) => (
              <span key={o.chave}>
                {i > 0 && <span className="text-muted-foreground">, </span>}
                <button type="button" onClick={abrir(o)} className={link}>
                  {o.titulo}
                  {o.objeto?.tom && <span className="text-muted-foreground"> ({o.objeto.tom})</span>}
                </button>
              </span>
            ))}
            {objetos.length > 4 && <span className="text-muted-foreground"> e mais {objetos.length - 4}</span>}
          </p>
        </LinhaDoAgora>
      )}
      {comerciais.length > 0 && (
        <LinhaDoAgora tipo="comercial" rotulo="Comerciais">
          {comerciais.map((c) => (
            <button key={c.chave} type="button" onClick={abrir(c)} className={cn(link, 'block text-sm')}>
              {c.titulo} <span className="text-xs text-muted-foreground">{c.linhas[0]}</span>
            </button>
          ))}
        </LinhaDoAgora>
      )}
      {textos.length > 0 && (
        <LinhaDoAgora tipo="texto" rotulo="Textos na tela">
          {textos.slice(0, 2).map((x) => (
            <button key={x.chave} type="button" onClick={abrir(x)} className={cn(link, 'block w-full truncate text-sm')}>
              {x.rotulo && <span className="mr-1.5 text-xs text-muted-foreground">{x.rotulo}</span>}
              {x.titulo}
            </button>
          ))}
        </LinhaDoAgora>
      )}
      <LinhaDoAgora tipo="fala" rotulo="Fala">
        {fala ? (
          <button type="button" onClick={abrir(fala)} className={cn(link, 'line-clamp-2 text-sm leading-snug')}>
            {fala.linhas[0] && <span className="mr-1.5 text-xs font-medium text-muted-foreground">{fala.linhas[0]}</span>}
            {fala.titulo}
          </button>
        ) : (
          vazia('Sem fala')
        )}
      </LinhaDoAgora>
    </section>
  )
}

// ---------- detalhe ----------

/**
 * O "não confirmado" ao lado do nome, dentro do botão da linha: só texto, com a dica no ponteiro. O foco
 * fica no botão, que já diz o selo no nome; a dica pelo teclado está no selo do detalhe.
 */
function SeloNaLinha({ selos, className }: { selos: Selo[]; className?: string }) {
  const selo = naoConfirmado(selos)
  if (!selo) return null
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn('inline-flex h-4 shrink-0 items-center rounded-xs border border-strong px-1 text-2xs whitespace-nowrap text-muted-foreground', className)}>
          {selo.rotulo}
        </span>
      </TooltipTrigger>
      <TooltipContent collisionPadding={8} className="max-w-64">{selo.dica}</TooltipContent>
    </Tooltip>
  )
}

function SeloDaProva({ selo, aoSaltar }: { selo: Selo; aoSaltar: (ms: number) => void }) {
  const base = 'inline-flex h-5 items-center rounded-xs border border-strong px-1.5 text-xs'
  if (selo.tipo === 'nao_confirmado') {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span tabIndex={0} className={cn(base, 'text-muted-foreground')}>
            {selo.rotulo}
          </span>
        </TooltipTrigger>
        <TooltipContent collisionPadding={8} className="max-w-64">{selo.dica}</TooltipContent>
      </Tooltip>
    )
  }
  if (selo.inicio_ms === null) return <span className={base}>{selo.rotulo}</span>
  const inicio = selo.inicio_ms
  return (
    <button type="button" onClick={() => aoSaltar(inicio)} className={cn(base, 'text-link hover:bg-accent')}>
      {`${selo.rotulo} ${relogio(inicio)}`}
    </button>
  )
}

/** O detalhe abre no próprio inspetor, sem diálogo; Esc volta à lista (MAM_DESIGN_SYSTEM 10). */
function Detalhe({
  item,
  itens,
  aoVoltar,
  aoSaltar,
  aoTocarTrecho,
  aoAbrir,
  urlDoQuadro,
  acoes,
}: {
  item: ItemDoPainel
  itens: ItemDoPainel[]
  aoVoltar: () => void
  aoSaltar: (ms: number) => void
  aoTocarTrecho: (i: Intervalo) => void
  aoAbrir: (chave: string, saltar: boolean) => void
  urlDoQuadro: (c: string) => Promise<string>
  acoes?: AcoesDeCorrecao
}) {
  const tipo = tipoDaChave(item.chave)
  const { Icone, cor } = TIPOS[tipo]
  const rotuloDoTipo = SECOES.find((s) => s.tipo === tipo)?.rotulo ?? ''
  const marca = acoes?.marcas?.[item.chave]
  const edicao = acoes?.edicao && (acoes.edicao.chave === item.chave || acoes.edicao.chave === `acrescentar:${item.pessoa}`) ? acoes.edicao : null
  const { dono } = item.objeto ?? {}
  // O dono do objeto: abre a primeira aparição dele.
  const irParaDono = (pessoa: string) => {
    const primeira = itens.find((i) => i.tipo === 'aparicao' && i.pessoa === pessoa)
    if (primeira) aoAbrir(primeira.chave, true)
  }
  return (
    <div className="flex flex-col" role="region" aria-label={`Detalhe: ${item.titulo}`}>
      <div className="flex h-10 shrink-0 items-center gap-1 border-b px-2">
        <BotaoDeIcone rotulo="Voltar à lista" atalho="Esc" onClick={aoVoltar}>
          <IconArrowLeft size={18} stroke={1.75} aria-hidden />
        </BotaoDeIcone>
        <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: cor }}>
          <Icone size={14} stroke={1.75} aria-hidden /> {rotuloDoTipo}
        </span>
        <span className="ml-auto font-mono text-xs text-muted-foreground tabular-nums">{tempos(item)}</span>
      </div>
      {item.quadro && <Miniatura caminho={item.quadro} urlDoQuadro={urlDoQuadro} className="aspect-video w-full rounded-none" />}
      <div className="grid gap-3 p-3">
        <h3 className={cn('text-lg leading-snug font-semibold break-words', item.titulo === NAO_IDENTIFICADO && 'font-normal text-muted-foreground italic')}>
          {item.tipo === 'texto' && item.rotulo && <span className="mr-2 text-sm font-medium text-muted-foreground">{item.rotulo}</span>}
          {item.titulo}
        </h3>
        {[item.tipo === 'texto' ? null : item.rotulo, ...item.linhas].filter(Boolean).map((l) => (
          <p key={l} className="text-base text-muted-foreground">
            {l}
          </p>
        ))}
        {item.objeto && (
          <div className="grid gap-0.5 text-sm">
            <CorDoObjeto dados={item.objeto} />
            {(dono || item.objeto.categoria !== 'em cena') && <p className="text-xs text-muted-foreground">{item.objeto.categoria}</p>}
            <p className="text-xs">
              {!dono ? (
                'em cena'
              ) : dono.naImagem ? (
                <>
                  {dono.relacao ? null : 'de '}
                  <button type="button" className="text-link underline" onClick={() => irParaDono(dono.id)}>
                    {dono.nome}
                  </button>
                  {dono.relacao ? ` ${dono.relacao}` : null}
                </>
              ) : dono.relacao ? (
                `${dono.nome} ${dono.relacao}`
              ) : (
                `de ${dono.nome}`
              )}
            </p>
            {item.objeto.marca && <p className="text-xs">{`marca ${item.objeto.marca}`}</p>}
            {item.objeto.detalhe && <p className="text-xs text-muted-foreground">{item.objeto.detalhe}</p>}
          </div>
        )}
        {(item.selos.length > 0 || marca) && (
          <div className="flex flex-wrap items-center gap-1">
            {item.selos.map((s) => (
              <SeloDaProva key={s.rotulo} selo={s} aoSaltar={aoSaltar} />
            ))}
            {marca && <SeloDaMarca marca={marca} />}
          </div>
        )}
        <dl className="grid grid-cols-[96px_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Duração</dt>
          <dd className="font-mono tabular-nums">{relogio(item.fim_ms - item.inicio_ms)}</dd>
        </dl>
        <div className="flex flex-wrap gap-1">
          <Button type="button" onClick={() => aoTocarTrecho(item)}>
            <IconPlayerPlay size={16} aria-hidden /> Tocar o trecho
          </Button>
          {acoes?.podeCorrigir(item) && (
            <Button type="button" variant="secondary" aria-pressed={edicao?.chave === item.chave} onClick={() => acoes.corrigir(item)}>
              <IconEdit size={16} stroke={1.75} aria-hidden /> Corrigir
            </Button>
          )}
          {acoes?.podeRemover(item) && (
            <Button type="button" variant="destructive" onClick={() => acoes.remover(item)}>
              <IconTrash size={16} stroke={1.75} aria-hidden /> Não é isto
            </Button>
          )}
          {acoes && item.tipo === 'aparicao' && item.pessoa && (
            <Button type="button" variant="secondary" onClick={() => acoes.acrescentar(item.pessoa as string)}>
              <IconPlus size={16} stroke={1.75} aria-hidden /> {`Acrescentar aparição de ${item.titulo}`}
            </Button>
          )}
        </div>
      </div>
      {edicao && <div className="border-t p-3">{edicao.conteudo}</div>}
    </div>
  )
}
