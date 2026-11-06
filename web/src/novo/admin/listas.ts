import { useInfiniteQuery, type QueryKey } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useLayoutEffect, useRef, useState, useSyncExternalStore, type RefObject } from 'react'

/** Páginas de 50 na memória, no máximo (ADR 0014): 300 linhas. */
export const TETO_DE_PAGINAS = 6

/**
 * Uma lista da API que pagina por cursor, com teto de páginas na memória. A página que sai pelo
 * começo volta com "Carregar anteriores": o navegador guarda, de cada cursor, o que veio antes dele
 * (a API só sabe ir para a frente). O cursor da primeira página é ''.
 */
export function useListaPorCursor<P extends { proximo: string | null }>(
  queryKey: QueryKey,
  buscar: (cursor: string | null) => Promise<P>,
  enabled = true,
) {
  const anteriores = useRef(new Map<string, string>())
  const prefixo = JSON.stringify(queryKey)
  return useInfiniteQuery({
    queryKey,
    enabled,
    initialPageParam: '',
    queryFn: ({ pageParam }) => buscar(pageParam || null),
    getNextPageParam: (ultima, _todas, cursor) => {
      if (!ultima.proximo) return undefined
      anteriores.current.set(`${prefixo}|${ultima.proximo}`, cursor)
      return ultima.proximo
    },
    getPreviousPageParam: (_primeira, _todas, cursor) => (cursor === '' ? undefined : anteriores.current.get(`${prefixo}|${cursor}`)),
    maxPages: TETO_DE_PAGINAS,
  })
}

/**
 * As linhas que a tela desenha de uma tabela longa: só as que estão à vista, mais uma folga. Cada
 * item é um `<tbody>` (a linha e o que ela abre), medido de verdade; o espaço das que não estão no
 * DOM fica em duas linhas vazias, antes e depois. `rolagem` é a área da aba que rola.
 */
export function useLinhasVirtuais(total: number, rolagem: RefObject<HTMLElement | null>, chave: (i: number) => string) {
  const tabela = useRef<HTMLTableElement>(null)
  // A tabela começa abaixo dos filtros: a distância entra na conta de quais linhas estão à vista.
  const [margem, setMargem] = useState(0)
  // Medida quando a lista muda. Um aviso ou um botão que aparece acima dela erra a conta por uma
  // linha ou duas, e a folga de 10 linhas de cada lado cobre isso.
  useLayoutEffect(() => {
    const t = tabela.current
    if (t) setMargem(t.offsetTop)
  }, [total])
  // O virtualizador devolve funções novas a cada desenho; nada aqui é memorizado.
  // oxlint-disable-next-line react/incompatible-library
  const virtual = useVirtualizer({
    count: total,
    getScrollElement: () => rolagem.current,
    estimateSize: () => 41,
    overscan: 10,
    scrollMargin: margem,
    getItemKey: chave,
  })
  const itens = virtual.getVirtualItems()
  const antes = itens.length ? itens[0]!.start - margem : 0
  const depois = itens.length ? virtual.getTotalSize() - (itens.at(-1)!.end - margem) : 0
  return { tabela, itens, antes, depois, medir: virtual.measureElement }
}

// Os pontos do Tailwind (sm, md, lg) em que uma coluna escondida no celular aparece.
const PONTOS = ['sm', 'md', 'lg'] as const
const CONSULTAS = ['(min-width: 40rem)', '(min-width: 48rem)', '(min-width: 64rem)']

function assinarPontos(aviso: () => void) {
  const consultas = CONSULTAS.map((c) => matchMedia(c))
  for (const c of consultas) c.addEventListener('change', aviso)
  return () => consultas.forEach((c) => c.removeEventListener('change', aviso))
}

const pontosAtingidos = () => CONSULTAS.filter((c) => matchMedia(c).matches).length

/**
 * Quantas colunas a tabela mostra agora; `null` é a coluna que aparece sempre. Um `colSpan` maior
 * que isso cria colunas vazias que, na tabela fixa, dividem a largura com as de verdade.
 */
export function useColunasVisiveis(colunas: readonly ((typeof PONTOS)[number] | null)[]): number {
  const nivel = useSyncExternalStore(assinarPontos, pontosAtingidos)
  return colunas.filter((c) => c === null || PONTOS.indexOf(c) < nivel).length
}
