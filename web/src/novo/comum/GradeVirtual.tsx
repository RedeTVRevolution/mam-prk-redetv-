import { useQueryClient } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { cn } from 'cn'
import { Fragment, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { lembrarPosicao } from '../paginas.ts'

const VAO = 12 // o gap-3 da grade, em px

/**
 * A rolagem de uma lista paginada (o acervo, a busca): o cabeçalho fixo no alto e a grade virtual,
 * em que só as fileiras à vista e 3 de folga existem na página. Voltar do vídeo volta ao mesmo
 * item, pelo índice; as setas andam entre os itens (`data-foco` com o índice).
 */
export function GradeVirtual({
  chave,
  voltaInicial,
  chegouNaVolta,
  recomecos,
  quantidade,
  aoVer,
  largura: larguraMinima,
  lista = false,
  alturaDoTexto,
  alturaDaLinha = 80,
  desenhar,
  esqueleto,
  carregando,
  cabecalho,
  avisos,
  children,
}: {
  /** A da consulta: outra começa do topo, e a volta do vídeo vale para a mesma. */
  chave: string
  /** O índice a que voltar ao abrir (do usePaginas), ou 0. */
  voltaInicial: number
  /** A tela chegou à volta (do usePaginas): a consulta recomeça do topo daqui em diante. */
  chegouNaVolta: () => void
  /** Um recomeço da mesma consulta (cursor vencido) também volta ao topo. */
  recomecos: number
  quantidade: number
  aoVer: (de: number, ate: number) => void
  /** A largura mínima do cartão. */
  largura: number
  lista?: boolean
  /** A altura do cartão abaixo da imagem 16:9, para a estimativa antes de medir. */
  alturaDoTexto: number
  alturaDaLinha?: number
  /** O item `i` (ou o esqueleto dele, se a página não está na memória). */
  desenhar: (i: number) => ReactNode
  esqueleto: ReactNode
  /** O rótulo do carregamento da primeira página, ou `null`. */
  carregando: string | null
  cabecalho: ReactNode
  avisos?: ReactNode
  /** Depois da grade: o erro, o vazio e os diálogos. */
  children?: ReactNode
}) {
  // As colunas saem da largura, com a conta do repeat(auto-fill, minmax(min(100%, Wpx), 1fr)).
  // A margem é onde a grade começa dentro da rolagem (abaixo do cabeçalho, que pode quebrar linha).
  const rolagem = useRef<HTMLDivElement>(null)
  const topoFixo = useRef<HTMLDivElement>(null)
  const area = useRef<HTMLDivElement>(null)
  const [medidas, setMedidas] = useState({ largura: 0, margem: 0, topo: 0 })
  useLayoutEffect(() => {
    const el = area.current!
    const ro = new ResizeObserver((entradas) => {
      const daArea = entradas.find((e) => e.target === el)
      setMedidas((m) => ({ largura: daArea ? daArea.contentRect.width : m.largura, margem: el.offsetTop, topo: topoFixo.current!.offsetHeight }))
    })
    ro.observe(el)
    ro.observe(topoFixo.current!)
    return () => ro.disconnect()
  }, [])
  const { largura, margem, topo } = medidas
  const minimo = Math.min(largura, larguraMinima)
  const colunas = lista ? 1 : Math.max(1, Math.floor((largura + VAO) / (minimo + VAO)))
  const larguraDoCartao = (largura - (colunas - 1) * VAO) / colunas
  const fileiras = Math.ceil(quantidade / colunas)

  // O useVirtualizer devolve funções que o React Compiler não memoriza; aqui ninguém o memoriza.
  // oxlint-disable-next-line react/incompatible-library
  const virtual = useVirtualizer({
    count: fileiras,
    getScrollElement: () => rolagem.current,
    estimateSize: () => (lista ? alturaDaLinha : (larguraDoCartao * 9) / 16 + alturaDoTexto + VAO),
    overscan: 3,
    scrollMargin: margem,
    // O cabeçalho fixo cobre o alto da rolagem: a fileira levada ao topo fica logo abaixo dele.
    scrollPaddingStart: topo,
  })
  const visiveis = virtual.getVirtualItems() // com as 3 fileiras de folga
  const vistaDe = virtual.range?.startIndex ?? -1 // só as fileiras à vista, sem a folga
  const vistaAte = virtual.range?.endIndex ?? -1
  const primeira = visiveis[0]?.index ?? 0
  const ultima = visiveis[visiveis.length - 1]?.index ?? 0

  // Voltar do vídeo: pelo índice e não pelos pixels, porque as colunas podem ser outras na volta.
  const cliente = useQueryClient()
  const volta = useRef(voltaInicial)
  const noTopo = useRef(0)
  useEffect(() => {
    if (!fileiras) return
    if (volta.current) {
      // Até a fileira do destino estar à vista, a faixa é a do topo: buscar daqui descartaria a página do destino.
      const alvo = Math.floor(volta.current / colunas)
      if (!largura || alvo < vistaDe || alvo > vistaAte) return
      volta.current = 0
      chegouNaVolta()
    }
    aoVer(primeira * colunas, (ultima + 1) * colunas - 1)
    noTopo.current = Math.max(0, vistaDe) * colunas
  }, [primeira, ultima, vistaDe, vistaAte, colunas, largura, fileiras, aoVer, chegouNaVolta])
  const rolouAteVolta = useRef(false)
  useEffect(() => {
    const alvo = Math.floor(volta.current / colunas)
    if (!largura || !volta.current || rolouAteVolta.current || alvo >= fileiras) return
    virtual.scrollToIndex(alvo, { align: 'start' })
    rolouAteVolta.current = true
  }, [largura, colunas, fileiras, virtual])
  useEffect(() => () => lembrarPosicao(cliente, chave, noTopo.current), [cliente, chave])
  // Mudou a forma das fileiras (colunas, largura, lista): as alturas guardadas não valem mais.
  useEffect(() => {
    virtual.measure()
  }, [virtual, colunas, larguraDoCartao, lista])
  // Outra consulta (outro filtro, outra ordem) começa do topo, sem a volta da de antes; o recomeço
  // (cursor vencido) e a lista que se pede do zero também.
  const vista = `${chave}#${recomecos}`
  const chaveVista = useRef(vista)
  useEffect(() => {
    if (chaveVista.current !== vista) {
      volta.current = 0
      if (rolagem.current) rolagem.current.scrollTop = 0
    }
    chaveVista.current = vista
  }, [vista])
  // A lista recomeçou (um envio novo a refaz do zero): o topo, onde o item novo aparece. Se a
  // volta ainda não tinha chegado, ela fica para trás (senão a grade esperaria a fileira dela).
  const jaCarregou = useRef(false)
  const estaCarregando = carregando !== null
  useEffect(() => {
    if (!estaCarregando) {
      jaCarregou.current = true
      return
    }
    if (jaCarregou.current && volta.current) {
      volta.current = 0
      chegouNaVolta()
    }
    if (rolagem.current) rolagem.current.scrollTop = 0
  }, [estaCarregando, chegouNaVolta])

  // As setas andam entre os itens; a fileira de destino entra na tela antes do foco.
  function aoTeclar(e: KeyboardEvent<HTMLDivElement>) {
    const atual = (e.target as HTMLElement).dataset.foco
    const passo = ({ ArrowRight: 1, ArrowLeft: -1, ArrowDown: colunas, ArrowUp: -colunas } as Record<string, number>)[e.key]
    if (atual === undefined || !passo) return
    const destino = Number(atual) + passo
    if (destino < 0 || destino >= quantidade) return
    e.preventDefault()
    virtual.scrollToIndex(Math.floor(destino / colunas), { align: 'auto' })
    requestAnimationFrame(() => rolagem.current?.querySelector<HTMLElement>(`[data-foco="${destino}"]`)?.focus())
  }

  const grade = lista ? undefined : `repeat(${colunas}, minmax(0, 1fr))`
  return (
    <div ref={rolagem} className="relative min-h-0 flex-1 overflow-y-auto bg-background">
      <div ref={topoFixo} className="sticky top-0 z-10 grid gap-2 border-b bg-background px-3 py-2 md:px-4">
        {cabecalho}
      </div>
      {avisos}
      <div className={lista ? undefined : 'p-3 md:p-4'} onKeyDown={aoTeclar}>
        <div ref={area} className="relative" style={{ height: virtual.getTotalSize() }}>
          {visiveis.map((fileira) => (
            <div
              key={fileira.key}
              data-index={fileira.index}
              ref={virtual.measureElement}
              className={cn('absolute inset-x-0 top-0', !lista && 'grid gap-3 pb-3')}
              style={{ transform: `translateY(${fileira.start - virtual.options.scrollMargin}px)`, gridTemplateColumns: grade }}
            >
              {Array.from({ length: colunas }, (_, c) => {
                const i = fileira.index * colunas + c
                return i < quantidade ? desenhar(i) : null
              })}
            </div>
          ))}
        </div>
        {carregando && (
          <div role="status" aria-label={carregando} className={cn(!lista && 'grid gap-3')} style={{ gridTemplateColumns: grade }}>
            {Array.from({ length: lista ? 8 : colunas * 3 }, (_, i) => (
              <Fragment key={i}>{esqueleto}</Fragment>
            ))}
          </div>
        )}
      </div>
      {children}
    </div>
  )
}
