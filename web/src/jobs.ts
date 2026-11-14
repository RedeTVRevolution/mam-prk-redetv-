import { ESTADOS_DO_JOB } from './cores.ts'

// O que a API mostra de um Job e os filtros do acervo, que viajam na URL e na chamada.

/** Uma etapa já iniciada do Job; `fim` e `resultado` só depois que ela acaba. */
export interface EtapaDoJob {
  nome: string
  inicio: string
  fim: string | null
  resultado: 'concluida' | 'falhou' | null
}

/** Quantos vídeos a rota de andamento aceita por pedido (`LIMITE_DO_ANDAMENTO` em `api/jobs.py`). */
export const MAXIMO_DO_ANDAMENTO = 200

export interface Job {
  id: string
  nome: string
  estado: string
  codigo_falha: string | null
  /** A etapa em andamento; vazia entre uma etapa e a seguinte. */
  etapa_atual?: string | null
  /** Posição do primeiro pedido de etapa esperando GPU; só o detalhe, calculada na leitura. */
  posicao_na_fila_gpu?: number | null
  /** Onde o Job está no índice da busca; `pendente` até a indexação terminar. */
  indexacao?: { estado: string; em: string } | null
  duracao_s?: number | null
  /** Cortes de câmera, em ms; só o detalhe do Job traz. */
  cortes_ms?: number[] | null
  /** Timecode do primeiro quadro do arquivo (`HH:MM:SS:FF`, ou `;FF` no drop-frame). */
  timecode_origem?: string | null
  taxa_de_quadros?: number | null
  /** URL assinada, de curta validade, do quadro de capa; só a listagem a traz. */
  capa_url?: string | null
  programa?: string | null
  data_exibicao?: string | null
  enviado_por?: { tipo: 'pessoa' | 'sistema'; nome: string | null }
  /** As etapas iniciadas, da primeira à última. */
  etapas?: EtapaDoJob[]
  reprocessamentos?: number
  /** Início da passada atual; ausente em Job anterior ao campo. */
  inicio_da_passada?: string | null
  reprocessavel_ate: string
  criado_em: string
  atualizado_em?: string
}

export interface JobCriado extends Job {
  url_de_upload: string
}

// As etapas que só rodam depois do `concluido`, na ordem; a indexação é sempre a última.
// Espelha `ETAPAS_DEPOIS_DO_CONCLUIDO` de `api/ciclo_de_vida.py`: mude as duas juntas.
const ETAPAS_DEPOIS_DO_CONCLUIDO = [
  'identificacao',
  'quadros_chave',
  'inventario_de_objetos',
  'indexacao',
]
// ponytail: teto fixo, acima do pior caso de uma etapa, que é o inventário de objetos: espera
// por GPU, Florence (11100 s) e o inventário em CPU (3900 s), uns 4 h 40 (timeouts do
// `validacao.workflow.yaml` e `espera_gpu_minutos` do infra). Um Workflows que morreu entre
// etapas deixa o Job assim; passado o teto, o selo solta e o "Reprocessar…" volta. Se esses
// prazos subirem, suba o teto.
const TETO_DO_FINALIZANDO_MS = 6 * 60 * 60 * 1000

/**
 * O Job fica `concluido` ao fim da análise, mas as etapas seguintes ainda rodam. Entre uma
 * etapa e a seguinte o `etapa_atual` fica vazio, então vale também a indexação `pendente`
 * (posta no `concluido`) ou uma etapa de depois do `concluido` já iniciada (uma correção no
 * meio reindexa e tira o `pendente`). Acaba quando a etapa da indexação ganha `fim`, que o
 * Workflows grava mesmo quando ela falha, ou quando o último sinal passa do teto.
 */
export function finalizando(job: Job, agora: number = Date.now()): boolean {
  if (job.estado !== 'concluido') return false
  const etapas = job.etapas ?? []
  // O `em` de um `indexado` vem também de uma correção, que não diz nada das etapas.
  const pendente = job.indexacao?.estado === 'pendente'
  const sinais = [pendente ? job.indexacao?.em : undefined, ...etapas.map((e) => e.inicio)]
    .map((t) => (t ? Date.parse(t) : NaN))
    .filter((t) => !Number.isNaN(t))
  if (sinais.length > 0 && agora - Math.max(...sinais) > TETO_DO_FINALIZANDO_MS) return false
  if (job.etapa_atual) return true
  if (etapas.some((e) => e.nome === 'indexacao' && e.fim)) return false
  return pendente || etapas.some((e) => ETAPAS_DEPOIS_DO_CONCLUIDO.includes(e.nome))
}

export type Ordem = 'enviado' | 'exibicao'

export interface FiltrosDoAcervo {
  q: string
  /** Os programas marcados; vazio é tudo marcado (nada vai ao endereço nem à API). */
  programas: string[]
  de: string
  ate: string
  estado: string[]
  ordem: Ordem
}

export const SEM_FILTROS: FiltrosDoAcervo = {
  q: '',
  programas: [],
  de: '',
  ate: '',
  estado: [],
  ordem: 'enviado',
}

/** Uma página do acervo; `proximo` é o cursor da seguinte, ausente na última. */
export interface PaginaDoAcervo {
  jobs: Job[]
  proximo: string | null
}

export const POR_PAGINA = 50

export function haFiltro(f: FiltrosDoAcervo): boolean {
  return Boolean(f.q || f.programas.length || f.de || f.ate || f.estado.length)
}

/** Os filtros na query da URL do app (`/acervo?q=&programa=&de=&ate=&estado=&ordem=`). */
export function filtrosParaBusca(f: FiltrosDoAcervo): string {
  const p = new URLSearchParams()
  if (f.q) p.set('q', f.q)
  for (const programa of f.programas) p.append('programa', programa)
  if (f.de) p.set('de', f.de)
  if (f.ate) p.set('ate', f.ate)
  for (const e of f.estado) p.append('estado', e)
  if (f.ordem !== SEM_FILTROS.ordem) p.set('ordem', f.ordem)
  const texto = p.toString()
  return texto ? `?${texto}` : ''
}

const DATA = /^\d{4}-\d{2}-\d{2}$/

export function filtrosDaBusca(busca: string): FiltrosDoAcervo {
  const p = new URLSearchParams(busca)
  const data = (nome: string) => {
    const valor = p.get(nome) ?? ''
    return DATA.test(valor) ? valor : ''
  }
  return {
    q: p.get('q') ?? '',
    programas: [...new Set(p.getAll('programa').filter(Boolean))],
    de: data('de'),
    ate: data('ate'),
    // Estado desconhecido num link editado à mão sai do filtro, em vez de fazer a API recusar.
    estado: [...new Set(p.getAll('estado'))].filter((e) => Object.hasOwn(ESTADOS_DO_JOB, e)),
    ordem: p.get('ordem') === 'exibicao' ? 'exibicao' : 'enviado',
  }
}

/** A data de exibição (`AAAA-MM-DD`) como `DD/MM/AAAA`; sem data, um travessão. */
export function dataDeExibicao(data: string | null | undefined): string {
  if (!data) return '—'
  const [ano, mes, dia] = data.split('-')
  return `${dia}/${mes}/${ano}`
}

/** A query de `GET /v1/jobs` para estes filtros. */
export function filtrosParaApi(f: FiltrosDoAcervo, cursor: string | null): string {
  const p = new URLSearchParams({ limite: String(POR_PAGINA), ordem: f.ordem })
  if (f.q) p.set('q', f.q)
  for (const programa of f.programas) p.append('programa', programa)
  if (f.de) p.set('exibicao_de', f.de)
  if (f.ate) p.set('exibicao_ate', f.ate)
  for (const e of f.estado) p.append('estado', e)
  if (cursor) p.set('cursor', cursor)
  return p.toString()
}

/** O instante como `DD/MM/AAAA HH:MM`, em São Paulo (o dia dos filtros por período). */
export function dataEHora(iso: string): string {
  const d = new Date(iso)
  return `${DATA_EM_SAO_PAULO.format(d)} ${HORA_EM_SAO_PAULO.format(d)}`
}

// Formatadores feitos uma vez: o `toLocale…String` com fuso monta um a cada chamada, e as listas chamam por linha.
const DATA_EM_SAO_PAULO = new Intl.DateTimeFormat('pt-BR', { timeZone: 'America/Sao_Paulo' })
const HORA_EM_SAO_PAULO = new Intl.DateTimeFormat('pt-BR', { timeZone: 'America/Sao_Paulo', hour: '2-digit', minute: '2-digit' })
