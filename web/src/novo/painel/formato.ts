import type { NumerosDeVideos, RelatorioDeRevisao } from '../../painelDaDiretoria.ts'
import { duracaoLegivel } from '../../tempoDeTela.ts'

// Os textos e formatos do painel da diretoria, os mesmos da interface antiga (PainelDaDiretoria.tsx).

export const numero = (n: number) => n.toLocaleString('pt-BR')

export const tempoMedio = (n: NumerosDeVideos) => (n.tempo_medio_s === null ? '—' : duracaoLegivel(n.tempo_medio_s * 1000))

/** `quem_tipo` sistema aparece com o nome da chave e o rótulo "(sistema)"; pessoa sem e-mail, com o uid. */
export const nomeDeQuem = (q: { quem_tipo: string; quem_id: string; email?: string | null }) =>
  q.quem_tipo === 'sistema' ? `${q.quem_id} (sistema)` : (q.email ?? q.quem_id)

export const quantos = (n: number | null) => (n === null ? '—' : numero(n))

export const nomeDoPrograma = (programa: string | null) => programa ?? 'Sem programa'

export const chaveDeQuem = (q: { quem_tipo: string; quem_id: string }) => `${q.quem_tipo}:${q.quem_id}`

export function revisaoVazia(r: RelatorioDeRevisao) {
  return r.correcoes.por_dia.length === 0 && r.taxa_de_correcao.por_tipo.length === 0 && r.tempo_de_revisao.por_pessoa.length === 0
}

export const NOTA_DO_DIA = 'O dia é o de São Paulo; os números se atualizam a cada 10 minutos.'
