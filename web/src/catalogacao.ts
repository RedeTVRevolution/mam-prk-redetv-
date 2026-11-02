/** A correção do item em foco sem React: os campos de cada tipo e os pedidos que as mudanças geram. */
import { type CatalogoDeCorrecoes, type Opcao } from './catalogo.ts'
import { type Intervalo, lerTempo, relogio, SEM_NOME, tempoDoCampo } from './linhaDoTempo.ts'
import type { ItemDoPainel } from './painel.ts'
import type { Decupagem, EstadoNaBusca, ItemDoHistorico } from './decupagem.ts'

export type Valor = string | string[] | boolean

export interface CampoDoEditor {
  chave: string
  rotulo: string
  tipo: 'texto' | 'nome' | 'area' | 'opcoes' | 'multiplas' | 'booleano' | 'tempo'
  /** Do tipo `nome`: o catálogo que o autocompletar consulta. */
  catalogo?: 'pessoas' | 'marcas'
  opcoes?: Opcao[]
  limite?: number
  /** Só aparece quando a função diz que sim (a evidência de quem passa a aparecer na imagem). */
  visivel?: (valores: Record<string, Valor>) => boolean
}

/** O corpo de `POST /v1/jobs/{id}/correcoes` sem o motivo e a versão, que a tela acrescenta. */
export interface Pedido {
  tipo: string
  item_id: string
  valor: string
  tipo_do_item?: string
  ocorrencia?: { lista: string; inicio_ms: number; fim_ms: number }
  /** O nome escolhido no catálogo (só `pessoa.renomear` e `comercial.marca`). */
  catalogo_id?: string
  /** O item é a pessoa de nome igual a este, que só existe depois do pedido anterior: a tela a procura na decupagem recarregada. */
  pessoa_do_nome?: string
}

export interface Editor {
  campos: CampoDoEditor[]
  inicial: Record<string, Valor>
  /**
   * Os pedidos das mudanças (nenhuma: lista vazia); `null` se os campos não permitem salvar.
   * `exatos` são os tempos das alças da linha do tempo (com os décimos), que valem no lugar dos campos.
   */
  pedidos(valores: Record<string, Valor>, exatos?: Intervalo | null): Pedido[] | null
  /** O intervalo do item, quando os tempos dele se corrigem (as alças da linha do tempo). */
  intervalo?: Intervalo
  /** O motivo do gesto, quando o editor não escreve um. */
  motivo(pedidos: Pedido[]): string
  /** Todos os tipos de correção que este editor sabe gerar. */
  tiposPossiveis: string[]
}

/** Os tipos do catálogo que não têm caminho no painel neste ticket. */
export const TIPOS_FORA_DESTE_TICKET = [
  'objeto.atributos',
  'objeto.dono',
  'descartar',
  'aprovar',
  'recusar',
]

const MOTIVOS: Record<string, string> = {
  'pessoa.renomear': 'nome corrigido pelo editor',
  'item.tempos': 'tempos ajustados pelo editor',
  'pauta.titulo': 'título da pauta corrigido pelo editor',
  'pauta.resumo': 'resumo da pauta corrigido pelo editor',
  'pauta.tom': 'tom da pauta corrigido pelo editor',
  'comercial.marca': 'marca do comercial corrigida pelo editor',
  'comercial.tipo': 'tipo do comercial corrigido pelo editor',
  'pessoa.fontes_do_nome': 'fontes do nome corrigidas pelo editor',
  'aparicao.papel_visual': 'papel e visual corrigidos pelo editor',
  'pessoa.aparicao_para_mencao': 'aparição trocada por menção pelo editor',
  'pessoa.mencao_para_aparicao': 'menção trocada por aparição pelo editor',
  'plano.descricao': 'descrição do plano corrigida pelo editor',
  'plano.limpo': 'plano limpo corrigido pelo editor',
  'fala.texto': 'fala corrigida pelo editor',
  'texto_na_tela.texto': 'texto na tela corrigido pelo editor',
  'pessoa.nao_e': 'pessoa removida desta aparição pelo editor',
  'pessoa.acrescentar_aparicao': 'aparição acrescentada pelo editor',
  'pauta.juntar': 'pautas juntadas pelo editor',
  'pauta.dividir': 'pauta dividida pelo editor',
}

/** As entradas do histórico que decidem sobre outra correção, e não corrigem um item. */
const DECISOES = ['desfazer', 'descartar', 'aprovar', 'recusar']

/** O motivo do gesto: o de uma correção só, ou os de todas, sem repetir. */
function motivoDoGesto(pedidos: Pedido[]): string {
  const frases = [...new Set(pedidos.map((p) => MOTIVOS[p.tipo] ?? 'correção feita pelo editor'))]
  return frases.join('; ')
}

const LISTAS: Opcao[] = [
  { valor: 'na_imagem', rotulo: 'Na imagem (aparição)' },
  { valor: 'citada_na_fala', rotulo: 'Citada na fala' },
  { valor: 'citada_no_texto', rotulo: 'Citada no texto' },
]

type Origem =
  | { tipo: 'aparicao' | 'mencao'; pessoa: Decupagem['pessoas'][number]; lista: string; intervalo: Intervalo }
  | { tipo: 'pauta'; pauta: Decupagem['pautas'][number] }
  | { tipo: 'comercial'; comercial: Decupagem['comerciais'][number] }
  | { tipo: 'texto'; texto: NonNullable<Decupagem['textos_na_tela']>[number] }
  | { tipo: 'plano'; plano: Decupagem['planos'][number] }
  | { tipo: 'fala'; fala: Decupagem['transcricao'][number] }

/** O dado da decupagem por trás do item do painel (as chaves seguem a ordem de `itensDoPainel`). */
function origemDoItem(d: Decupagem, item: ItemDoPainel): Origem | null {
  const n = Number(item.chave.split('-')[1])
  switch (item.tipo) {
    case 'aparicao': {
      const todas = d.pessoas.flatMap((pessoa) =>
        pessoa.na_imagem.map((intervalo) => ({ pessoa, intervalo })),
      )
      return todas[n] ? { tipo: 'aparicao', lista: 'na_imagem', ...todas[n] } : null
    }
    case 'mencao': {
      const todas = [
        ...d.pessoas.flatMap((pessoa) =>
          pessoa.citada_na_fala.map((intervalo) => ({ pessoa, intervalo, lista: 'citada_na_fala' })),
        ),
        ...d.pessoas.flatMap((pessoa) =>
          pessoa.citada_no_texto.map((intervalo) => ({ pessoa, intervalo, lista: 'citada_no_texto' })),
        ),
      ]
      return todas[n] ? { tipo: 'mencao', ...todas[n] } : null
    }
    case 'pauta':
      return d.pautas[n] ? { tipo: 'pauta', pauta: d.pautas[n] } : null
    case 'comercial':
      return d.comerciais[n] ? { tipo: 'comercial', comercial: d.comerciais[n] } : null
    case 'texto': {
      const texto = d.textos_na_tela?.[n]
      return texto ? { tipo: 'texto', texto } : null
    }
    case 'plano':
      return d.planos[n] ? { tipo: 'plano', plano: d.planos[n] } : null
    case 'fala':
      return d.transcricao[n] ? { tipo: 'fala', fala: d.transcricao[n] } : null
    default:
      return null
  }
}

/** A chave que guarda o id do catálogo escolhido no campo de nome `chave`. */
export const idDoNome = (chave: string): string => `${chave}__id`

/** O `catalogo_id` do nome escolhido, se há um. */
const comId = (v: Record<string, Valor>, chave: string): { catalogo_id?: string } =>
  texto(v[idDoNome(chave)]) ? { catalogo_id: texto(v[idDoNome(chave)]) } : {}

export const texto = (v: Valor | undefined): string => (typeof v === 'string' ? v.trim() : '')

export function camposDeTempo(): CampoDoEditor[] {
  return [
    { chave: 'inicio', rotulo: 'Início (MM:SS ou H:MM:SS)', tipo: 'tempo' },
    { chave: 'fim', rotulo: 'Fim (MM:SS ou H:MM:SS)', tipo: 'tempo' },
  ]
}

/** Os tempos dos campos; `undefined` se não são MM:SS ou H:MM:SS, ou se o início passa do fim. */
export function temposDosCampos(v: Record<string, Valor>, o: Intervalo, exatos?: Intervalo | null): Intervalo | undefined {
  if (exatos) return exatos.inicio_ms > exatos.fim_ms ? undefined : exatos
  const inicio = tempoDoCampo(texto(v.inicio), o.inicio_ms)
  const fim = tempoDoCampo(texto(v.fim), o.fim_ms)
  return inicio === null || fim === null || inicio > fim ? undefined : { inicio_ms: inicio, fim_ms: fim }
}

export function montar(
  campos: CampoDoEditor[],
  inicial: Record<string, Valor>,
  tiposPossiveis: string[],
  gerar: (valores: Record<string, Valor>, exatos?: Intervalo | null) => Pedido[] | null,
): Editor {
  return { campos, inicial, pedidos: gerar, motivo: motivoDoGesto, tiposPossiveis }
}

/** O pedido de tempos, se mudaram; `null` quando os campos não são tempos válidos. */
function pedidoDeTempos(
  v: Record<string, Valor>,
  o: Intervalo,
  base: Omit<Pedido, 'tipo' | 'valor'>,
  exatos?: Intervalo | null,
): Pedido[] | null {
  const novos = temposDosCampos(v, o, exatos)
  if (!novos) return null
  if (novos.inicio_ms === o.inicio_ms && novos.fim_ms === o.fim_ms) return []
  return [{ ...base, tipo: 'item.tempos', valor: `${novos.inicio_ms}-${novos.fim_ms}` }]
}

/** Junta os pedidos de cada parte; qualquer parte inválida (`null`) invalida o conjunto. */
function juntar(partes: (Pedido[] | null)[]): Pedido[] | null {
  return partes.some((p) => p === null) ? null : partes.flat() as Pedido[]
}

/** O editor do item: os campos do tipo (do catálogo, #134) e os pedidos das mudanças; `null` sem o que corrigir. */
export function editorDoItem(d: Decupagem, item: ItemDoPainel, c: CatalogoDeCorrecoes): Editor | null {
  const editor = montarEditor(d, item, c)
  if (editor?.campos.some((campo) => campo.chave === 'inicio'))
    editor.intervalo = { inicio_ms: item.inicio_ms, fim_ms: item.fim_ms }
  return editor
}

function montarEditor(d: Decupagem, item: ItemDoPainel, c: CatalogoDeCorrecoes): Editor | null {
  const o = origemDoItem(d, item)
  if (!o) return null
  const tempos = (i: Intervalo): Record<string, Valor> => ({ inicio: relogio(i.inicio_ms), fim: relogio(i.fim_ms) })
  switch (o.tipo) {
    case 'aparicao':
    case 'mencao': {
      const { pessoa, lista, intervalo } = o
      const ocorrencia = { lista, inicio_ms: intervalo.inicio_ms, fim_ms: intervalo.fim_ms }
      const daAparicao = o.tipo === 'aparicao' ? (intervalo as { papel?: string | null; visual?: string | null }) : null
      const comFontes = 'fontes_do_nome' in pessoa
      const destinos = o.tipo === 'aparicao' ? LISTAS : LISTAS.filter((l) => l.valor === lista || l.valor === 'na_imagem')
      const campos: CampoDoEditor[] = [
        { chave: 'nome', rotulo: 'Nome', tipo: 'nome', catalogo: 'pessoas', limite: c.limites.nome },
        { chave: 'destino', rotulo: 'Aparição ou menção', tipo: 'opcoes', opcoes: destinos },
        ...(o.tipo === 'mencao'
          ? [
              {
                chave: 'evidencia',
                rotulo: 'Evidência na imagem',
                tipo: 'texto' as const,
                limite: c.limites.nome,
                visivel: (v: Record<string, Valor>) => v.destino === 'na_imagem',
              },
            ]
          : [
              { chave: 'papel', rotulo: 'Papel na cena', tipo: 'texto' as const, limite: c.limites.nome },
              { chave: 'visual', rotulo: 'Visual', tipo: 'texto' as const, limite: c.limites.nome },
            ]),
        ...(comFontes
          ? [{ chave: 'fontes', rotulo: 'Fontes do nome', tipo: 'multiplas' as const, opcoes: c.fontes_do_nome }]
          : []),
        ...camposDeTempo(),
      ]
      const inicial: Record<string, Valor> = {
        nome: pessoa.nome,
        destino: lista,
        evidencia: '',
        papel: daAparicao?.papel ?? '',
        visual: daAparicao?.visual ?? '',
        fontes: pessoa.fontes_do_nome ?? [],
        ...tempos(intervalo),
      }
      const fontesAtuais = pessoa.fontes_do_nome ?? []
      return montar(
        campos,
        inicial,
        [
          'pessoa.renomear',
          'item.tempos',
          'pessoa.aparicao_para_mencao',
          'pessoa.mencao_para_aparicao',
          ...(o.tipo === 'aparicao' ? ['aparicao.papel_visual'] : []),
          ...(comFontes ? ['pessoa.fontes_do_nome'] : []),
        ],
        (v, exatos) => {
          const partes: (Pedido[] | null)[] = []
          const nome = texto(v.nome)
          if (!nome) return null
          if (nome !== pessoa.nome) partes.push([{ tipo: 'pessoa.renomear', item_id: pessoa.id, valor: nome, ...comId(v, 'nome') }])
          if (comFontes) {
            const fontes = c.fontes_do_nome.map((f) => f.valor).filter((f) => (v.fontes as string[]).includes(f))
            if (fontes.join() !== fontesAtuais.join())
              partes.push([{ tipo: 'pessoa.fontes_do_nome', item_id: pessoa.id, valor: JSON.stringify(fontes) }])
          }
          if (daAparicao && (texto(v.papel) !== (daAparicao.papel ?? '') || texto(v.visual) !== (daAparicao.visual ?? '')))
            partes.push([
              {
                tipo: 'aparicao.papel_visual',
                item_id: pessoa.id,
                ocorrencia,
                valor: JSON.stringify({ papel: texto(v.papel) || null, visual: texto(v.visual) || null }),
              },
            ])
          partes.push(pedidoDeTempos(v, intervalo, { tipo_do_item: 'pessoa', item_id: pessoa.id, ocorrencia }, exatos))
          // A troca de lista vai por último: as outras correções ainda acham a ocorrência onde ela está.
          if (v.destino !== lista) {
            if (o.tipo === 'mencao') {
              if (!texto(v.evidencia)) return null
              partes.push([{ tipo: 'pessoa.mencao_para_aparicao', item_id: pessoa.id, ocorrencia, valor: texto(v.evidencia) }])
            } else {
              partes.push([{ tipo: 'pessoa.aparicao_para_mencao', item_id: pessoa.id, ocorrencia, valor: String(v.destino) }])
            }
          }
          return juntar(partes)
        },
      )
    }
    case 'pauta': {
      const { pauta } = o
      if (!pauta.id) return null
      return montar(
        [
          { chave: 'titulo', rotulo: 'Título', tipo: 'texto', limite: c.limites.nome },
          { chave: 'resumo', rotulo: 'Resumo', tipo: 'area', limite: c.limites.texto },
          { chave: 'tom', rotulo: 'Tom', tipo: 'opcoes', opcoes: c.tons_da_pauta },
          ...camposDeTempo(),
        ],
        { titulo: pauta.titulo, resumo: pauta.resumo ?? '', tom: pauta.tom ?? '', ...tempos(pauta) },
        ['pauta.titulo', 'pauta.resumo', 'pauta.tom', 'item.tempos'],
        (v, exatos) => {
          const partes: (Pedido[] | null)[] = []
          if (!texto(v.titulo)) return null
          if (texto(v.titulo) !== pauta.titulo) partes.push([{ tipo: 'pauta.titulo', item_id: pauta.id, valor: texto(v.titulo) }])
          // Resumo apagado não vira correção: a API não aceita valor vazio.
          if (texto(v.resumo) && texto(v.resumo) !== (pauta.resumo ?? ''))
            partes.push([{ tipo: 'pauta.resumo', item_id: pauta.id, valor: texto(v.resumo) }])
          if (v.tom && v.tom !== (pauta.tom ?? ''))
            partes.push([{ tipo: 'pauta.tom', item_id: pauta.id, valor: String(v.tom) }])
          partes.push(pedidoDeTempos(v, pauta, { item_id: pauta.id }, exatos))
          return juntar(partes)
        },
      )
    }
    case 'comercial': {
      const { comercial } = o
      if (!comercial.id) return null
      const id = comercial.id
      return montar(
        [
          { chave: 'marca', rotulo: 'Marca', tipo: 'nome', catalogo: 'marcas', limite: c.limites.nome },
          { chave: 'tipo', rotulo: 'Tipo', tipo: 'opcoes', opcoes: c.tipos_de_comercial },
          ...camposDeTempo(),
        ],
        { marca: comercial.marca, tipo: comercial.tipo, ...tempos(comercial) },
        ['comercial.marca', 'comercial.tipo', 'item.tempos'],
        (v, exatos) => {
          const partes: (Pedido[] | null)[] = []
          if (!texto(v.marca)) return null
          if (texto(v.marca) !== comercial.marca) partes.push([{ tipo: 'comercial.marca', item_id: id, valor: texto(v.marca), ...comId(v, 'marca') }])
          if (v.tipo && v.tipo !== comercial.tipo) partes.push([{ tipo: 'comercial.tipo', item_id: id, valor: String(v.tipo) }])
          partes.push(pedidoDeTempos(v, comercial, { tipo_do_item: 'comercial', item_id: id }, exatos))
          return juntar(partes)
        },
      )
    }
    case 'texto': {
      const { texto: t } = o
      if (!t.id) return null
      const id = t.id
      return montar(
        [
          { chave: 'tipo', rotulo: 'Tipo', tipo: 'opcoes', opcoes: c.tipos_de_texto_na_tela },
          { chave: 'texto', rotulo: 'Texto', tipo: 'area', limite: c.limites.texto },
          ...camposDeTempo(),
        ],
        { tipo: t.tipo, texto: t.texto, ...tempos(t) },
        ['texto_na_tela.texto', 'item.tempos'],
        (v, exatos) => {
          const partes: (Pedido[] | null)[] = []
          if (!texto(v.texto) || !v.tipo) return null
          if (texto(v.texto) !== t.texto || v.tipo !== t.tipo)
            partes.push([{ tipo: 'texto_na_tela.texto', item_id: id, valor: JSON.stringify({ tipo: v.tipo, texto: texto(v.texto) }) }])
          partes.push(pedidoDeTempos(v, t, { tipo_do_item: 'texto_na_tela', item_id: id }, exatos))
          return juntar(partes)
        },
      )
    }
    case 'plano': {
      const { plano } = o
      if (!plano.id) return null
      const id = plano.id
      const objetos = (plano.objetos ?? []).join(', ')
      const lista = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)
      return montar(
        [
          { chave: 'ambiente', rotulo: 'Descrição do ambiente', tipo: 'texto', limite: c.limites.nome },
          { chave: 'acao', rotulo: 'Ação', tipo: 'texto', limite: c.limites.nome },
          { chave: 'objetos', rotulo: 'Objetos (separados por vírgula)', tipo: 'texto', limite: c.limites.texto },
          { chave: 'limpo', rotulo: 'Plano limpo', tipo: 'booleano' },
        ],
        { ambiente: plano.ambiente, acao: plano.acao ?? '', objetos, limpo: plano.plano_limpo ?? false },
        ['plano.descricao', 'plano.limpo'],
        (v) => {
          const partes: Pedido[] = []
          if (!texto(v.ambiente)) return null
          if (texto(v.ambiente) !== plano.ambiente || texto(v.acao) !== (plano.acao ?? '') || lista(texto(v.objetos)).join('\n') !== (plano.objetos ?? []).join('\n'))
            partes.push({
              tipo: 'plano.descricao',
              item_id: id,
              valor: JSON.stringify({ ambiente: texto(v.ambiente), acao: texto(v.acao) || null, objetos: lista(texto(v.objetos)) }),
            })
          if (v.limpo !== (plano.plano_limpo ?? false)) partes.push({ tipo: 'plano.limpo', item_id: id, valor: String(v.limpo) })
          return partes
        },
      )
    }
    case 'fala': {
      const { fala } = o
      if (!fala.id) return null
      const id = fala.id
      return montar(
        [
          { chave: 'texto', rotulo: 'Texto', tipo: 'area', limite: c.limites.texto },
          { chave: 'locutor', rotulo: 'Locutor', tipo: 'texto', limite: c.limites.nome },
        ],
        { texto: fala.texto, locutor: fala.locutor },
        ['fala.texto'],
        (v) => {
          if (!texto(v.texto)) return null
          if (texto(v.texto) === fala.texto && texto(v.locutor) === fala.locutor) return []
          return [{ tipo: 'fala.texto', item_id: id, valor: JSON.stringify({ texto: texto(v.texto), locutor: texto(v.locutor) }) }]
        },
      )
    }
  }
}

/** "Não é isto" existe para a pessoa com nome, numa aparição ou menção. */
export function podeRemover(d: Decupagem, item: ItemDoPainel): boolean {
  const o = origemDoItem(d, item)
  return !!o && (o.tipo === 'aparicao' || o.tipo === 'mencao') && !SEM_NOME.test(o.pessoa.nome)
}

export function pedidoDeRemocao(d: Decupagem, item: ItemDoPainel): Pedido | null {
  const o = origemDoItem(d, item)
  if (!o || (o.tipo !== 'aparicao' && o.tipo !== 'mencao')) return null
  return {
    tipo: 'pessoa.nao_e',
    item_id: o.pessoa.id,
    valor: 'Não identificado',
    ocorrencia: { lista: o.lista, inicio_ms: o.intervalo.inicio_ms, fim_ms: o.intervalo.fim_ms },
  }
}

/** O motivo do "não é isto": a menção não é uma aparição. */
export function motivoDaRemocao(pedido: Pedido): string {
  return pedido.ocorrencia?.lista === 'na_imagem' ? MOTIVOS['pessoa.nao_e'] : 'pessoa removida desta menção pelo editor'
}

/**
 * A correção que a rota de desfazer aceita: casável na API (em vigor e ainda na fila), e não uma decisão.
 * A pendente fica de fora: só se desfaz depois de aprovada.
 */
export function desfazivel(i: ItemDoHistorico): boolean {
  return (
    (i.estado === 'ativa' || i.estado === 'aprovada') &&
    !DECISOES.includes(i.tipo)
  )
}

/** O editor de uma aparição nova da pessoa: começa no momento atual e dura 5 s. */
export function editorDeNovaAparicao(
  pessoa: { id: string; nome: string },
  atualMs: number,
  c: CatalogoDeCorrecoes,
): Editor {
  return montar(
    [
      ...camposDeTempo(),
      { chave: 'evidencia', rotulo: 'Evidência na imagem', tipo: 'texto', limite: c.limites.nome },
    ],
    { inicio: relogio(atualMs), fim: relogio(atualMs + 5000), evidencia: '' },
    ['pessoa.acrescentar_aparicao'],
    (v) => {
      const inicio = lerTempo(texto(v.inicio))
      const fim = lerTempo(texto(v.fim))
      if (inicio === null || fim === null || inicio >= fim || !texto(v.evidencia)) return null
      return [
        {
          tipo: 'pessoa.acrescentar_aparicao',
          item_id: pessoa.id,
          valor: JSON.stringify({ inicio_ms: inicio, fim_ms: fim, evidencia: texto(v.evidencia) }),
        },
      ]
    },
  )
}

/** Quem o item corrige na API: o tipo e o id do item da Correção (a pessoa vale para todas as aparições). */
export function identidadeDoItem(d: Decupagem, item: ItemDoPainel): { tipo_do_item: string; item_id: string } | null {
  const o = origemDoItem(d, item)
  if (!o) return null
  switch (o.tipo) {
    case 'aparicao':
    case 'mencao':
      return { tipo_do_item: 'pessoa', item_id: o.pessoa.id }
    case 'pauta':
      return o.pauta.id ? { tipo_do_item: 'pauta', item_id: o.pauta.id } : null
    case 'comercial':
      return o.comercial.id ? { tipo_do_item: 'comercial', item_id: o.comercial.id } : null
    case 'texto':
      return o.texto.id ? { tipo_do_item: 'texto_na_tela', item_id: o.texto.id } : null
    case 'plano':
      return o.plano.id ? { tipo_do_item: 'plano', item_id: o.plano.id } : null
    case 'fala':
      return o.fala.id ? { tipo_do_item: 'fala', item_id: o.fala.id } : null
  }
}

/** A marca de um item corrigido: "aguardando o Curador" ou onde a correção está no índice, com a dica de quem, quando e por quê. */
export interface Marca {
  pendente: boolean
  /** Onde a correção está no índice da busca; vale quando não está pendente. */
  na_busca: EstadoNaBusca
  dica: string
}

/** O que a marca escreve de cada estado da correção no índice da busca. */
export const ROTULO_NA_BUSCA: Record<EstadoNaBusca, string> = {
  salva: 'salva',
  indexando: 'indexando',
  na_busca: 'na busca',
}

/** Há correção ainda entrando no índice: a tela volta a perguntar até ela confirmar. */
export const aindaIndexando = (historico: ItemDoHistorico[]): boolean =>
  historico.some((h) => (h.estado === 'ativa' || h.estado === 'aprovada') && h.na_busca === 'indexando')

const quando = (iso: string) => new Date(iso).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' })

/** As marcas por chave de item: só valem as correções da decupagem aberta que ainda estão de pé. */
export function marcasDosItens(
  d: Decupagem,
  itens: ItemDoPainel[],
  historico: ItemDoHistorico[],
): Record<string, Marca> {
  const vivas = historico.filter(
    (h) =>
      h.ancora.versao === d.versao_decupagem &&
      !DECISOES.includes(h.tipo) &&
      (h.estado === 'ativa' || h.estado === 'pendente'),
  )
  const marcas: Record<string, Marca> = {}
  for (const item of itens) {
    const id = identidadeDoItem(d, item)
    if (!id) continue
    const doItem = vivas.filter((h) => h.item_id === id.item_id && h.ancora.tipo_do_item === id.tipo_do_item)
    if (doItem.length === 0) continue
    // O histórico vem da mais recente à mais antiga.
    const ultima = doItem.find((h) => h.estado === 'pendente') ?? doItem[0]
    marcas[item.chave] = {
      pendente: ultima.estado === 'pendente',
      na_busca: ultima.na_busca ?? 'salva',
      dica: `${ultima.autor_email} · ${quando(ultima.criada_em)} · ${ultima.motivo}`,
    }
  }
  return marcas
}

/** O item do painel que uma correção do histórico mexeu (o primeiro, se a pessoa tem várias ocorrências); `undefined` se saiu da decupagem. */
export function itemDaCorrecao(
  d: Decupagem,
  itens: ItemDoPainel[],
  correcao: ItemDoHistorico,
): ItemDoPainel | undefined {
  return itens.find((item) => {
    const id = identidadeDoItem(d, item)
    return id?.item_id === correcao.item_id && id.tipo_do_item === correcao.ancora.tipo_do_item
  })
}
