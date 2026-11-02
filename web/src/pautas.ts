/** Juntar e dividir pautas: os campos dos dois formulários e os pedidos que geram. */
import { type CatalogoDeCorrecoes } from './catalogo.ts'
import { type CampoDoEditor, type Editor, montar, texto } from './catalogacao.ts'
import type { Pauta } from './decupagem.ts'
import { relogio } from './linhaDoTempo.ts'

const OUTRO_TITULO = '__outro__'

/** As pautas marcadas, na ordem do vídeo, ou o aviso do que falta. */
export function pautasParaJuntar(
  todas: Pauta[],
  marcadas: ReadonlySet<string>,
): { pautas: Pauta[] } | { aviso: string } {
  const indices = todas.flatMap((p, i) => (marcadas.has(p.id) ? [i] : []))
  if (indices.length < 2) return { aviso: 'Marque duas ou mais pautas para juntar (M).' }
  if (indices.some((n, i) => i > 0 && n !== indices[i - 1] + 1))
    return { aviso: 'Só se juntam pautas seguidas: marque também a do meio.' }
  return { pautas: indices.map((i) => todas[i]) }
}

const motivado = (frase: string, e: Editor): Editor => ({ ...e, motivo: () => frase })

/** O título da junção: um dos das pautas ou um novo. */
export function editorDeJuncao(pautas: Pauta[], c: CatalogoDeCorrecoes): Editor {
  const titulos = [...new Set(pautas.map((p) => p.titulo))]
  const campos: CampoDoEditor[] = [
    {
      chave: 'escolha',
      rotulo: 'Título',
      tipo: 'opcoes',
      opcoes: [...titulos.map((t) => ({ valor: t, rotulo: t })), { valor: OUTRO_TITULO, rotulo: 'Outro título' }],
    },
    {
      chave: 'novo',
      rotulo: 'Novo título',
      tipo: 'texto',
      limite: c.limites.nome,
      visivel: (v) => v.escolha === OUTRO_TITULO,
    },
  ]
  return motivado(
    'pautas juntadas pelo editor',
    montar(campos, { escolha: titulos[0], novo: '' }, ['pauta.juntar'], (v) => {
      const titulo = v.escolha === OUTRO_TITULO ? texto(v.novo) : texto(v.escolha)
      if (!titulo) return null
      return [
        {
          tipo: 'pauta.juntar',
          item_id: pautas[0].id,
          valor: JSON.stringify({ ids: pautas.map((p) => p.id), titulo }),
        },
      ]
    }),
  )
}

/** O corte cabe dentro da pauta, com as duas metades de duração. */
export const cabeNaPauta = (p: Pauta, emMs: number) => emMs > p.inicio_ms && emMs < p.fim_ms

/** Os dois títulos da divisão no `emMs` (as duas metades começam com o título da pauta). */
export function editorDeDivisao(pauta: Pauta, emMs: number, c: CatalogoDeCorrecoes): Editor {
  const campos: CampoDoEditor[] = [
    { chave: 'primeiro', rotulo: 'Título da primeira parte', tipo: 'texto', limite: c.limites.nome },
    { chave: 'segundo', rotulo: 'Título da segunda parte', tipo: 'texto', limite: c.limites.nome },
  ]
  return motivado(
    `pauta dividida em ${relogio(emMs)} pelo editor`,
    montar(campos, { primeiro: pauta.titulo, segundo: pauta.titulo }, ['pauta.dividir'], (v) => {
      const titulos = [texto(v.primeiro), texto(v.segundo)]
      if (titulos.some((t) => !t)) return null
      return [{ tipo: 'pauta.dividir', item_id: pauta.id, valor: JSON.stringify({ em_ms: emMs, titulos }) }]
    }),
  )
}
