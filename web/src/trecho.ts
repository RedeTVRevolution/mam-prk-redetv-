/** O trecho marcado com I e O e o que se diz que há nele: os campos de cada aba e os pedidos que geram. */
import type { CatalogoDeCorrecoes, Opcao } from './catalogo.ts'
import type { Pessoa } from './decupagem.ts'
import {
  camposDeTempo,
  camposDoObjeto,
  type CampoDoEditor,
  coresDaLista,
  type Editor,
  montar,
  type Pedido,
  SEM_DONO,
  texto,
  temposDosCampos,
  type Valor,
} from './catalogacao.ts'
import { type Intervalo, relogio } from './linhaDoTempo.ts'

export type AbaDoTrecho = 'pessoa' | 'objeto' | 'marca' | 'texto' | 'pauta'

/** As abas do campo único, na ordem e com a tecla do número. */
export const ABAS_DO_TRECHO: { valor: AbaDoTrecho; rotulo: string; tecla: string }[] = [
  { valor: 'pessoa', rotulo: 'Pessoa', tecla: '1' },
  { valor: 'objeto', rotulo: 'Objeto', tecla: '2' },
  { valor: 'marca', rotulo: 'Marca', tecla: '3' },
  { valor: 'texto', rotulo: 'Texto na tela', tecla: '4' },
  { valor: 'pauta', rotulo: 'Pauta', tecla: '5' },
]

/** O que prova a marca no vídeo (o vocabulário do esquema da decupagem, que o catálogo não traz). */
const EVIDENCIAS_DA_MARCA: Opcao[] = [
  { valor: 'fala', rotulo: 'Fala' },
  { valor: 'logo', rotulo: 'Logo' },
  { valor: 'texto_na_tela', rotulo: 'Texto na tela' },
  { valor: 'produto', rotulo: 'Produto' },
]

/** Onde uma pessoa só citada é citada (os valores são as listas da decupagem). */
const ONDE_E_CITADA: Opcao[] = [
  { valor: 'citada_na_fala', rotulo: 'Na fala' },
  { valor: 'citada_no_texto', rotulo: 'No texto na tela' },
]

export const MOTIVO_DO_TRECHO = 'trecho marcado pelo editor'

/** O editor da aba: os campos do tipo, mais os tempos do trecho (que as alças também ajustam). */
export function editorDoTrecho(aba: AbaDoTrecho, trecho: Intervalo, c: CatalogoDeCorrecoes, pessoas: Pessoa[]): Editor {
  const tempos = { inicio: relogio(trecho.inicio_ms), fim: relogio(trecho.fim_ms) }
  const comTempos = (
    gerar: (v: Record<string, Valor>, t: Intervalo) => Pedido[] | null,
  ): ((v: Record<string, Valor>, exatos?: Intervalo | null) => Pedido[] | null) => {
    return (v, exatos) => {
      const t = temposDosCampos(v, trecho, exatos)
      return t ? gerar(v, t) : null
    }
  }
  const acrescentar = (tipo: string, valor: object): Pedido[] => [
    { tipo, item_id: '', valor: JSON.stringify(valor) },
  ]
  const motivado = (editor: Editor): Editor => ({ ...editor, motivo: () => MOTIVO_DO_TRECHO })
  switch (aba) {
    case 'pessoa':
      return motivado(
        montar(
          [
            { chave: 'nome', rotulo: 'Nome', tipo: 'nome', catalogo: 'pessoas', limite: c.limites.nome },
            { chave: 'citada', rotulo: 'Citada (não aparece na imagem)', tipo: 'booleano' },
            {
              chave: 'destino',
              rotulo: 'Onde é citada',
              tipo: 'opcoes',
              opcoes: ONDE_E_CITADA,
              visivel: (v) => v.citada === true,
            },
            {
              chave: 'evidencia',
              rotulo: 'Evidência na imagem',
              tipo: 'texto',
              limite: c.limites.nome,
              visivel: (v) => v.citada !== true,
            },
            ...camposDeTempo(),
          ],
          { nome: '', citada: false, destino: ONDE_E_CITADA[0].valor, evidencia: '', ...tempos },
          ['pessoa.acrescentar_aparicao', 'pessoa.aparicao_para_mencao'],
          comTempos((v, t) => {
            const citada = v.citada === true
            if (!texto(v.nome) || (!citada && !texto(v.evidencia))) return null
            const aparicao = acrescentar('pessoa.acrescentar_aparicao', {
              inicio_ms: t.inicio_ms,
              fim_ms: t.fim_ms,
              // A menção nasce como aparição e troca de lista em seguida: a API não tem "menção nova".
              evidencia: citada ? MOTIVO_DO_TRECHO : texto(v.evidencia),
              nome: texto(v.nome),
            })
            if (!citada) return aparicao
            return [
              ...aparicao,
              {
                tipo: 'pessoa.aparicao_para_mencao',
                item_id: '',
                pessoa_do_nome: texto(v.nome),
                ocorrencia: { lista: 'na_imagem', inicio_ms: t.inicio_ms, fim_ms: t.fim_ms },
                valor: String(v.destino),
              },
            ]
          }),
        ),
      )
    case 'objeto':
      return motivado(
        montar(
          [
            { chave: 'categoria', rotulo: 'Categoria', tipo: 'opcoes', opcoes: c.categorias_de_objeto },
            ...camposDoObjeto(c, pessoas),
            ...camposDeTempo(),
          ],
          {
            categoria: c.categorias_de_objeto[0]?.valor ?? '',
            tipo: '',
            cor_base: [],
            cor: '',
            detalhe: '',
            marca: '',
            dono: SEM_DONO,
            relacao: c.relacoes_do_objeto[0]?.valor ?? '',
            ...tempos,
          },
          ['objeto.acrescentar'],
          comTempos((v, t) => {
            const cores = coresDaLista(v, c)
            if (!texto(v.tipo) || !v.categoria || !cores) return null
            const dono = String(v.dono ?? SEM_DONO)
            if (dono !== SEM_DONO && !v.relacao) return null
            return acrescentar('objeto.acrescentar', {
              categoria: v.categoria,
              tipo: texto(v.tipo),
              cor_base: cores,
              cor: texto(v.cor) || null,
              detalhe: texto(v.detalhe) || null,
              marca: texto(v.marca) || null,
              pessoa: dono === SEM_DONO ? null : dono,
              relacao: dono === SEM_DONO ? null : String(v.relacao),
              inicio_ms: t.inicio_ms,
              fim_ms: t.fim_ms,
            })
          }),
        ),
      )
    case 'marca': {
      const campos: CampoDoEditor[] = [
        { chave: 'marca', rotulo: 'Marca', tipo: 'nome', catalogo: 'marcas', limite: c.limites.nome },
        { chave: 'tipo', rotulo: 'Tipo', tipo: 'opcoes', opcoes: c.tipos_de_comercial },
        { chave: 'evidencias', rotulo: 'Evidências', tipo: 'multiplas', opcoes: EVIDENCIAS_DA_MARCA },
        ...camposDeTempo(),
      ]
      return motivado(
        montar(
          campos,
          { marca: '', tipo: c.tipos_de_comercial[0]?.valor ?? '', evidencias: [], ...tempos },
          ['comercial.acrescentar'],
          comTempos((v, t) => {
            const evidencias = EVIDENCIAS_DA_MARCA.map((e) => e.valor).filter((e) => (v.evidencias as string[]).includes(e))
            if (!texto(v.marca) || !v.tipo || evidencias.length === 0) return null
            return acrescentar('comercial.acrescentar', {
              marca: texto(v.marca),
              tipo: v.tipo,
              inicio_ms: t.inicio_ms,
              fim_ms: t.fim_ms,
              evidencias,
            })
          }),
        ),
      )
    }
    case 'texto':
      return motivado(
        montar(
          [
            { chave: 'tipo', rotulo: 'Tipo', tipo: 'opcoes', opcoes: c.tipos_de_texto_na_tela },
            { chave: 'texto', rotulo: 'Texto', tipo: 'area', limite: c.limites.texto },
            ...camposDeTempo(),
          ],
          { tipo: c.tipos_de_texto_na_tela[0]?.valor ?? '', texto: '', ...tempos },
          ['texto_na_tela.acrescentar'],
          comTempos((v, t) =>
            texto(v.texto) && v.tipo
              ? acrescentar('texto_na_tela.acrescentar', {
                  inicio_ms: t.inicio_ms,
                  fim_ms: t.fim_ms,
                  tipo: v.tipo,
                  texto: texto(v.texto),
                })
              : null,
          ),
        ),
      )
    case 'pauta':
      return motivado(
        montar(
          [
            { chave: 'titulo', rotulo: 'Título', tipo: 'texto', limite: c.limites.nome },
            { chave: 'tom', rotulo: 'Tom', tipo: 'opcoes', opcoes: c.tons_da_pauta },
            { chave: 'resumo', rotulo: 'Resumo (opcional)', tipo: 'area', limite: c.limites.texto },
            ...camposDeTempo(),
          ],
          { titulo: '', tom: c.tons_da_pauta[0]?.valor ?? '', resumo: '', ...tempos },
          ['pauta.acrescentar'],
          comTempos((v, t) =>
            texto(v.titulo) && v.tom
              ? acrescentar('pauta.acrescentar', {
                  titulo: texto(v.titulo),
                  tom: v.tom,
                  ...(texto(v.resumo) ? { resumo: texto(v.resumo) } : {}),
                  inicio_ms: t.inicio_ms,
                  fim_ms: t.fim_ms,
                })
              : null,
          ),
        ),
      )
  }
}
