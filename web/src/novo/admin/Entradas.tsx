import {
  IconAlertTriangle,
  IconBan,
  IconCircleCheck,
  IconClock,
  IconInbox,
  IconLoader2,
  IconMovie,
  IconPlayerPlay,
  IconProgress,
  IconRefresh,
  IconRotateClockwise,
  IconX,
  type Icon,
} from '@tabler/icons-react'
import { useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query'
import { cn } from 'cn'
import { useRef, useState, type KeyboardEvent } from 'react'
import { codigoDoErro, ConflitoNaApi, PedidoInvalido, SessaoExpirada } from '../../api.ts'
import { useAtalhos, type Atalho } from '../../atalhos.ts'
import { ESTADOS_DO_JOB, type EstadoDoJob } from '../../cores.ts'
import {
  casaComOsFiltrosDoCliente,
  emAndamento,
  haFiltroDeEntradas,
  passouDoPeriodo,
  porSistema,
  SEM_FILTROS_DAS_ENTRADAS,
  sistemaDoFiltro,
  tempoDaEntradaMs,
  type FiltrosDasEntradas,
} from '../../entradas.ts'
import { ETAPAS_ESCOLHIVEIS, etapaDeReprocesso, nomeDaEtapa, ORDEM, partidaDaEtapa } from '../../etapas.ts'
import { falhaDaAcao, type Falha } from '../../falhaDaAcao.ts'
import { fraseDaFalha } from '../../falhas.ts'
import { dataEHora, MAXIMO_DO_ANDAMENTO, type EtapaDoJob, type Job, type PaginaDoAcervo } from '../../jobs.ts'
import { relogio } from '../../linhaDoTempo.ts'
import { enderecoDasEntradas, navegar } from '../../rotas.ts'
import { urlSegura } from '../../urlSegura.ts'
import { AVISO_DO_REPROCESSAMENTO, prazoDeReprocessamentoVencido } from '../comum/regras.ts'
import { useApi } from '../consultas.ts'
import { Button } from '../ui/button.tsx'
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip.tsx'
import { Aba, Aviso, CABECALHO, CAMPO, CELULA, Carregando, Erro, Folga, LINHA_CLICAVEL, Selo, TABELA, TopoDaAba, Vazio } from './comum.tsx'
import { useColunasVisiveis, useLinhasVirtuais, useListaPorCursor } from './listas.ts'

const ESTADOS = Object.keys(ESTADOS_DO_JOB) as EstadoDoJob[]
// Em que ponto cada coluna aparece; `null`, sempre.
const COLUNAS = ['sm', null, 'md', 'sm', null] as const
const ATALHOS: Atalho[] = [{ tecla: 'Enter', acao: 'Na tabela: mostrar ou esconder as etapas da linha', grupo: 'Entradas' }]

const ICONE_DO_ESTADO: Record<EstadoDoJob, { Icone: Icon; tom: 'ok' | 'andamento' | 'falha' | 'neutro' }> = {
  aguardando_upload: { Icone: IconClock, tom: 'andamento' },
  validando: { Icone: IconProgress, tom: 'andamento' },
  analisando: { Icone: IconProgress, tom: 'andamento' },
  concluido: { Icone: IconCircleCheck, tom: 'ok' },
  falhou: { Icone: IconAlertTriangle, tom: 'falha' },
  cancelado: { Icone: IconBan, tom: 'neutro' },
}

/** O que a linha tem aberto embaixo: a confirmação de reprocessar o que falhou ou a escolha da etapa. */
type Aberto = { id: string; tipo: 'falha' | 'etapa' }

type Passo = { nome: string; ms: number; resultado: 'concluida' | 'falhou' | 'rodando' | 'parou' | 'pendente' }

const COR_DO_PASSO: Record<Passo['resultado'], string> = {
  concluida: 'bg-ok',
  falhou: 'bg-destructive',
  rodando: 'bg-andamento animate-pulse',
  parou: 'bg-subtle',
  pendente: 'bg-input',
}

function irPara(filtros: FiltrosDasEntradas) {
  navegar(enderecoDasEntradas(filtros), { substituir: true })
}

function duracaoMs(e: EtapaDoJob, agora: number): number {
  return Math.max((e.fim ? Date.parse(e.fim) : agora) - Date.parse(e.inicio), 0)
}

/** As 8 etapas na ordem em que rodam, com o tempo de cada uma. */
function passosDo(job: Job, agora: number): Passo[] {
  const andando = emAndamento(job)
  return ORDEM.map((nome) => {
    const e = job.etapas?.find((x) => x.nome === nome)
    if (!e) return { nome, ms: 0, resultado: 'pendente' }
    return { nome, ms: duracaoMs(e, agora), resultado: e.resultado ?? (andando ? 'rodando' : 'parou') }
  })
}

function fraseDoPasso(p: Passo): string {
  if (p.resultado === 'pendente') return `${nomeDaEtapa(p.nome)}: ainda não rodou`
  if (p.resultado === 'rodando') return `${nomeDaEtapa(p.nome)}: rodando há ${relogio(p.ms)}`
  if (p.resultado === 'parou') return `${nomeDaEtapa(p.nome)}: parou em ${relogio(p.ms)}`
  return `${nomeDaEtapa(p.nome)}: ${relogio(p.ms)}, ${p.resultado === 'falhou' ? 'falhou' : 'concluída'}`
}

/** A régua: as etapas lado a lado, cada uma na largura do tempo que levou (a que não rodou fica fina). */
function ReguaDeEtapas({ job, agora }: { job: Job; agora: number }) {
  const passos = passosDo(job, agora)
  return (
    <div role="img" aria-label={`Etapas: ${passos.map(fraseDoPasso).join('; ')}`} className="flex h-2 gap-px overflow-hidden rounded-xs">
      {passos.map((p) => (
        <Tooltip key={p.nome}>
          <TooltipTrigger asChild>
            <span className={cn('min-w-1', COR_DO_PASSO[p.resultado])} style={{ flexGrow: Math.max(p.ms, 30_000) }} />
          </TooltipTrigger>
          <TooltipContent>{fraseDoPasso(p)}</TooltipContent>
        </Tooltip>
      ))}
    </div>
  )
}

function resultadoDaEtapa(etapa: EtapaDoJob): string {
  if (etapa.resultado === 'concluida') return 'Concluída'
  if (etapa.resultado === 'falhou') return 'Falhou'
  return 'Em andamento'
}

function EtapasDoJob({ job, agora }: { job: Job; agora: number }) {
  const etapas = job.etapas ?? []
  if (etapas.length === 0) return <p className="text-muted-foreground">Nenhuma etapa registrada ainda.</p>
  return (
    <div className="grid gap-2">
      {/* No celular a régua não cabe na linha e desce para cá. */}
      <div className="md:hidden">
        <ReguaDeEtapas job={job} agora={agora} />
      </div>
      <table aria-label={`Etapas de ${job.nome}`} className="w-full max-w-2xl text-xs tabular-nums">
        <thead>
          <tr className="text-left text-muted-foreground">
            <th className="py-1 pr-2 font-medium">Etapa</th>
            <th className="py-1 pr-2 font-medium">Início</th>
            <th className="hidden py-1 pr-2 font-medium sm:table-cell">Fim</th>
            <th className="py-1 pr-2 font-medium">Duração</th>
            <th className="py-1 font-medium">Resultado</th>
          </tr>
        </thead>
        <tbody>
          {etapas.map((e) => (
            <tr key={e.nome}>
              <td className="py-0.5 pr-2">{nomeDaEtapa(e.nome)}</td>
              <td className="py-0.5 pr-2">{dataEHora(e.inicio)}</td>
              <td className="hidden py-0.5 pr-2 sm:table-cell">{e.fim ? dataEHora(e.fim) : '—'}</td>
              <td className="py-0.5 pr-2">{relogio(duracaoMs(e, agora))}</td>
              <td className={cn('py-0.5', e.resultado === 'falhou' && 'text-destructive')}>{resultadoDaEtapa(e)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function FalhaDaLinha({ job, etapaFalha }: { job: Job; etapaFalha: string | null }) {
  if (job.codigo_falha) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="truncate text-xs text-destructive">{fraseDaFalha(job.codigo_falha)}</span>
        </TooltipTrigger>
        <TooltipContent>Código para o suporte: {job.codigo_falha}</TooltipContent>
      </Tooltip>
    )
  }
  if (etapaFalha && job.estado === 'concluido') {
    return <span className="truncate text-xs text-destructive">{`A etapa ${nomeDaEtapa(etapaFalha)} falhou; o vídeo segue concluído.`}</span>
  }
  return null
}

function EstadoDaLinha({ job }: { job: Job }) {
  const estado = ESTADOS_DO_JOB[job.estado as EstadoDoJob]
  const icone = ICONE_DO_ESTADO[job.estado as EstadoDoJob]
  const etapa = job.etapa_atual ? <Selo tom="andamento" Icone={IconProgress}>{nomeDaEtapa(job.etapa_atual)}</Selo> : null
  // A etapa no lugar do estado enquanto roda; o vídeo concluído continua concluído enquanto uma etapa de depois roda.
  if (etapa && job.estado !== 'concluido') return etapa
  return (
    <>
      <Selo tom={icone?.tom ?? 'neutro'} Icone={icone?.Icone}>
        {estado?.rotulo ?? job.estado}
      </Selo>
      {etapa}
    </>
  )
}

function Miniatura({ job }: { job: Job }) {
  const capa = urlSegura(job.capa_url)
  if (!capa) {
    return (
      <span className="grid aspect-video w-[76px] place-items-center rounded-xs bg-input text-subtle">
        <IconMovie size={16} stroke={1.5} aria-hidden />
      </span>
    )
  }
  return <img src={capa} alt="" loading="lazy" decoding="async" className="aspect-video w-[76px] rounded-xs bg-input object-cover" />
}

function ConfirmarReprocesso({ job, etapa, aoConfirmar, aoCancelar }: { job: Job; etapa: string; aoConfirmar: (motivo: string) => Promise<void>; aoCancelar: () => void }) {
  const [motivo, setMotivo] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [falha, setFalha] = useState<Falha | null>(null)

  async function confirmar() {
    setEnviando(true)
    setFalha(null)
    try {
      await aoConfirmar(motivo.trim())
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, `Não foi possível reprocessar ${job.nome}. Tente de novo.`))
      setEnviando(false)
    }
  }

  return (
    <div className="grid max-w-xl gap-2 py-2" onKeyDown={(e) => e.key === 'Escape' && !enviando && aoCancelar()}>
      <p>{`Reprocessar a partir ${partidaDaEtapa(etapa)}? As etapas já concluídas não são refeitas.`}</p>
      <label className="grid gap-1 text-xs text-muted-foreground">
        Motivo (opcional)
        <input className={CAMPO} maxLength={500} value={motivo} onChange={(e) => setMotivo(e.currentTarget.value)} autoFocus />
      </label>
      {falha && <Erro mensagem={falha.mensagem} codigo={falha.codigo} />}
      <div className="flex gap-2">
        <Button type="button" size="sm" disabled={enviando} onClick={() => void confirmar()}>
          {enviando && <IconLoader2 className="animate-spin" aria-hidden />}
          Reprocessar
        </Button>
        <Button type="button" size="sm" variant="secondary" disabled={enviando} onClick={aoCancelar}>
          Cancelar
        </Button>
      </div>
    </div>
  )
}

/** A escolha da etapa e do motivo, na própria linha: o Job que a API devolve vai a `aoReprocessar`. */
function ReprocessarEtapa({ job, aoReprocessar, aoCancelar }: { job: Job; aoReprocessar: (novo: Job, etapa: string) => Promise<void>; aoCancelar: () => void }) {
  const api = useApi()
  const [etapa, setEtapa] = useState<string>(ETAPAS_ESCOLHIVEIS[0].valor)
  const [motivo, setMotivo] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [falha, setFalha] = useState<{ mensagem: string; codigo: string | null } | null>(null)

  async function confirmar() {
    setEnviando(true)
    setFalha(null)
    try {
      await aoReprocessar(await api.job(job.id).reprocessar(etapa, motivo.trim()), etapa)
    } catch (e) {
      if (e instanceof SessaoExpirada) return
      setFalha(
        e instanceof ConflitoNaApi || e instanceof PedidoInvalido
          ? { mensagem: e.message, codigo: null }
          : { mensagem: 'Não foi possível reprocessar. Tente de novo em instantes.', codigo: codigoDoErro(e) },
      )
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="grid max-w-xl gap-3 py-2" onKeyDown={(e) => e.key === 'Escape' && !enviando && aoCancelar()}>
      <fieldset className="grid gap-1.5">
        <legend className="mb-1 text-sm font-medium">Reprocessar a partir de</legend>
        {ETAPAS_ESCOLHIVEIS.map((e) => (
          <label key={e.valor} className="flex items-start gap-2">
            <input type="radio" name={`etapa-${job.id}`} className="mt-0.5 size-4 shrink-0 accent-primary" checked={etapa === e.valor} onChange={() => setEtapa(e.valor)} />
            <span className="grid">
              <span>{nomeDaEtapa(e.valor)}</span>
              <span className="text-xs text-muted-foreground">{e.refaz}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <label className="grid gap-1 text-xs text-muted-foreground">
        Motivo (fica na auditoria)
        <textarea required rows={2} maxLength={500} className={cn(CAMPO, 'h-auto py-1')} value={motivo} onChange={(e) => setMotivo(e.currentTarget.value)} />
      </label>
      <p>
        {etapa === 'analise'
          ? 'Reprocessar a partir da análise? A Decupagem fica indisponível até a nova análise terminar, e as etapas seguintes rodam de novo.'
          : `Reprocessar a partir da etapa ${nomeDaEtapa(etapa)}? Ela e as etapas seguintes rodam de novo; a Decupagem continua disponível.`}
      </p>
      {falha && <Erro mensagem={falha.mensagem} codigo={falha.codigo ?? '—'} />}
      <div className="flex justify-end gap-2">
        <Button type="button" size="sm" variant="secondary" disabled={enviando} onClick={aoCancelar}>
          Cancelar
        </Button>
        <Button type="button" size="sm" disabled={enviando || motivo.trim() === ''} onClick={() => void confirmar()}>
          {enviando && <IconLoader2 className="animate-spin" aria-hidden />}
          Reprocessar
        </Button>
      </div>
    </div>
  )
}

/** `/admin/entradas`: todos os vídeos que entraram, de pessoas e de sistemas, e o reprocessamento. */
export default function Entradas({
  filtros,
  podeReprocessar,
  podeEscolherEtapa,
  podeVerSistemas,
  intervaloMs = 15_000,
}: {
  filtros: FiltrosDasEntradas
  /** `video.reprocessar`: o botão "Reprocessar" das falhas de etapa. */
  podeReprocessar: boolean
  /** `video.reprocessar_etapa`: o "Reprocessar…" dos vídeos concluídos. */
  podeEscolherEtapa: boolean
  /** `chaves.gerir`: os sistemas do filtro vêm das chaves; sem ela, só os das linhas. */
  podeVerSistemas: boolean
  intervaloMs?: number
}) {
  const api = useApi()
  const consultas = useQueryClient()
  const [abertas, setAbertas] = useState<string[]>([])
  const [pedido, setPedido] = useState<Aberto | null>(null)
  const [agoraDoPedido, setAgoraDoPedido] = useState(Date.now)
  const [aviso, setAviso] = useState<string | null>(null)
  const rolagem = useRef<HTMLDivElement>(null)
  useAtalhos(ATALHOS)

  // Só sistema e estado vão à API: trocar o resto não recarrega a lista.
  const chave = ['admin', 'entradas', sistemaDoFiltro(filtros.por), filtros.estado]
  const lista = useListaPorCursor(chave, (cursor) => api.entradas(filtros, cursor))
  const chaves = useQuery({ queryKey: ['admin', 'chaves'], queryFn: () => api.chaves.listar(), enabled: podeVerSistemas })
  const jobs = lista.data?.pages.flatMap((p) => p.jobs) ?? []
  // O relógio da tela anda com a lista: cada atualização dela grava a hora.
  const agora = lista.dataUpdatedAt

  // Sem capa na resposta, fica a da lista: o andamento e o reprocessamento não trazem capa_url.
  const trocar = (troca: (j: Job) => Job[]) =>
    consultas.setQueryData<InfiniteData<PaginaDoAcervo>>(chave, (d) => d && { ...d, pages: d.pages.map((p) => ({ ...p, jobs: p.jobs.flatMap((j) => troca(j).map((n) => ({ ...n, capa_url: n.capa_url ?? j.capa_url }))) })) })

  // Só as linhas em andamento são consultadas de novo, num pedido só, e só com a aba à vista
  // (o TanStack para o intervalo com a aba escondida).
  const emCurso = jobs.filter(emAndamento).map((j) => j.id).slice(0, MAXIMO_DO_ANDAMENTO)
  const andamento = useQuery({
    queryKey: [...chave, 'andamento'],
    enabled: emCurso.length > 0,
    refetchInterval: intervaloMs,
    queryFn: async () => {
      const ids = emCurso
      const novos = new Map((await api.andamento(ids)).map((n) => [n.id, n]))
      const pedidos = new Set(ids)
      // Quem a rota omite (foi para a lixeira ou sumiu) sai da lista.
      trocar((j) => (!pedidos.has(j.id) ? [j] : novos.has(j.id) ? [novos.get(j.id)!] : []))
      return ids
    },
  })

  const sistemasConhecidos = [
    ...new Set([
      ...(chaves.data ?? []).map((c) => c.sistema),
      ...jobs.flatMap((j) => (j.enviado_por?.tipo === 'sistema' && j.enviado_por.nome ? [j.enviado_por.nome] : [])),
      ...(sistemaDoFiltro(filtros.por) ? [sistemaDoFiltro(filtros.por)!] : []),
    ]),
  ].sort((a, b) => a.localeCompare(b, 'pt-BR'))

  const visiveis = jobs.filter((j) => casaComOsFiltrosDoCliente(j, filtros))
  const haMais = lista.hasNextPage && !passouDoPeriodo(jobs, filtros)
  const { tabela, itens, antes, depois, medir } = useLinhasVirtuais(visiveis.length, rolagem, (i) => visiveis[i]?.id ?? String(i))
  const colunas = useColunasVisiveis(COLUNAS)
  const pronta = lista.data !== undefined
  const emAndamentoAgora = jobs.filter(emAndamento).length

  async function trocarJob(novo: Job, etapa: string) {
    // Um GET da lista no ar (a volta à aba, o "Carregar mais") traria a linha de antes e a desfaria.
    // Só aqui: no andamento, cancelar a cada rodada impediria a lista longa de terminar.
    await consultas.cancelQueries({ queryKey: chave, exact: true })
    trocar((j) => [j.id === novo.id ? novo : j])
    setPedido(null)
    setAviso(`${novo.nome} voltou a ser processado a partir ${partidaDaEtapa(etapa)}.`)
  }

  const alternar = (id: string) => setAbertas((atuais) => (atuais.includes(id) ? atuais.filter((a) => a !== id) : [...atuais, id]))
  const pedir = (job: Job, tipo: Aberto['tipo']) => {
    const atual = Date.now()
    setAgoraDoPedido(atual)
    if (prazoDeReprocessamentoVencido(job, atual)) {
      setAviso(AVISO_DO_REPROCESSAMENTO)
      setPedido(null)
      return
    }
    setAviso(null)
    const id = job.id
    setPedido(pedido?.id === id && pedido.tipo === tipo ? null : { id, tipo })
  }
  const mudar = (parte: Partial<FiltrosDasEntradas>) => irPara({ ...filtros, ...parte })
  const alternarEstado = (e: string) => mudar({ estado: filtros.estado.includes(e) ? filtros.estado.filter((x) => x !== e) : [...filtros.estado, e] })

  return (
    <Aba ref={rolagem}>
      <TopoDaAba titulo="Entradas" contagem={pronta ? `${visiveis.length} na lista, ${emAndamentoAgora} em andamento` : undefined}>
        <select aria-label="Enviado por" className={cn(CAMPO, 'w-full sm:w-48')} value={filtros.por} onChange={(e) => mudar({ por: e.currentTarget.value })}>
          <option value="">Todos</option>
          <option value="pessoas">Pessoas</option>
          {sistemasConhecidos.map((s) => (
            <option key={s} value={porSistema(s)}>
              {s}
            </option>
          ))}
        </select>
        <input type="date" aria-label="Enviado de" className={CAMPO} value={filtros.de} onChange={(e) => mudar({ de: e.currentTarget.value })} />
        <input type="date" aria-label="Enviado até" className={CAMPO} value={filtros.ate} onChange={(e) => mudar({ ate: e.currentTarget.value })} />
        <div role="group" aria-label="Estado" className="flex flex-wrap gap-1">
          {ESTADOS.map((e) => {
            const marcado = filtros.estado.includes(e)
            return (
              <button
                key={e}
                type="button"
                aria-pressed={marcado}
                onClick={() => alternarEstado(e)}
                className={cn('h-7 rounded-sm border px-2 text-xs transition-colors', marcado ? 'border-primary bg-selected text-foreground' : 'border-strong text-muted-foreground hover:bg-card')}
              >
                {ESTADOS_DO_JOB[e].rotulo}
              </button>
            )
          })}
        </div>
        {haFiltroDeEntradas(filtros) && (
          <Button type="button" variant="ghost" size="sm" onClick={() => irPara(SEM_FILTROS_DAS_ENTRADAS)}>
            <IconX stroke={1.75} aria-hidden /> Limpar filtros
          </Button>
        )}
      </TopoDaAba>
      <Aviso>{aviso}</Aviso>
      {lista.isFetchNextPageError ? (
        <Erro mensagem="Não foi possível carregar mais vídeos." codigo={codigoDoErro(lista.error)} aoTentar={() => void lista.fetchNextPage()} />
      ) : (
        andamento.isError && <Erro mensagem="Não foi possível atualizar a lista; tentando de novo." codigo={codigoDoErro(andamento.error)} />
      )}
      {lista.isPending && <Carregando rotulo="Carregando as entradas" />}
      {lista.isError && !pronta && <Erro mensagem="Não foi possível carregar as entradas. Tente de novo." codigo={codigoDoErro(lista.error)} aoTentar={() => void lista.refetch()} />}
      {pronta && visiveis.length === 0 && (
        <Vazio Icone={IconInbox}>
          {!haFiltroDeEntradas(filtros)
            ? 'Nenhum vídeo entrou ainda.'
            : haMais
              ? 'Nenhum vídeo com esses filtros entre os já carregados. Carregue mais para procurar nos mais antigos.'
              : 'Nenhum vídeo com esses filtros.'}
        </Vazio>
      )}
      {pronta && visiveis.length > 0 && (
        <table ref={tabela} aria-label="Entradas" className={TABELA}>
          <thead>
            <tr>
              <th className={cn(CABECALHO, 'hidden w-[92px] sm:table-cell')}>
                <span className="sr-only">Miniatura</span>
              </th>
              <th className={CABECALHO}>Envio</th>
              <th className={cn(CABECALHO, 'hidden w-[26%] md:table-cell')}>Etapas</th>
              <th className={cn(CABECALHO, 'hidden w-20 text-right sm:table-cell')}>Tempo</th>
              <th className={cn(CABECALHO, 'w-[120px] sm:w-[196px]')}>
                <span className="sr-only">Ações</span>
              </th>
            </tr>
          </thead>
          <Folga altura={antes} colunas={colunas} />
          {itens.map((item) => {
            const job = visiveis[item.index]!
            const aberta = abertas.includes(job.id)
            const doPedido = pedido?.id === job.id ? pedido.tipo : null
            const partida = etapaDeReprocesso(job)
            const prazoVencido = prazoDeReprocessamentoVencido(job, Math.max(agora, agoraDoPedido))
            const falhaDoArquivo = job.estado === 'falhou' && partida === null
            const interrompido = job.codigo_falha === 'processamento_interrompido'
            const aoTeclar = (e: KeyboardEvent<HTMLTableRowElement>) => {
              if (e.target !== e.currentTarget || e.key !== 'Enter') return
              e.preventDefault()
              alternar(job.id)
            }
            return (
              <tbody key={item.key} data-index={item.index} ref={medir}>
                <tr tabIndex={0} aria-expanded={aberta} onClick={() => alternar(job.id)} onKeyDown={aoTeclar} className={LINHA_CLICAVEL}>
                  <td className={cn(CELULA, 'hidden sm:table-cell')}>
                    <Miniatura job={job} />
                  </td>
                  <td className={cn(CELULA, 'py-1.5')}>
                    <p className="truncate font-medium" title={job.nome}>
                      {job.nome}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {`${job.programa ?? 'Sem programa'}, por ${job.enviado_por?.nome ?? '—'} em ${dataEHora(job.criado_em)}`}
                    </p>
                    <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                      <EstadoDaLinha job={job} />
                      <FalhaDaLinha job={job} etapaFalha={job.estado === 'concluido' ? partida : null} />
                    </div>
                  </td>
                  <td className={cn(CELULA, 'hidden md:table-cell')}>
                    <ReguaDeEtapas job={job} agora={agora} />
                  </td>
                  <td className={cn(CELULA, 'hidden text-right font-mono text-xs tabular-nums sm:table-cell')}>{relogio(tempoDaEntradaMs(job, agora))}</td>
                  <td className={CELULA} onClick={(e) => e.stopPropagation()}>
                    <div className="flex flex-wrap justify-end gap-1.5">
                      {falhaDoArquivo && <span className="text-right text-xs text-muted-foreground">Envie o arquivo de novo</span>}
                      {podeReprocessar && partida && (
                        <Button
                          type="button"
                          size="sm"
                          variant={interrompido ? 'default' : 'secondary'}
                          disabled={prazoVencido}
                          aria-describedby={prazoVencido ? `prazo-${job.id}` : undefined}
                          aria-label={`${interrompido ? 'Retomar' : 'Reprocessar'} ${job.nome}`}
                          onClick={() => pedir(job, 'falha')}
                        >
                          {interrompido ? <IconPlayerPlay aria-hidden /> : <IconRotateClockwise aria-hidden />}
                          {interrompido ? 'Retomar' : 'Reprocessar'}
                        </Button>
                      )}
                      {podeEscolherEtapa && job.estado === 'concluido' && !emAndamento(job) && (
                        <Button type="button" size="sm" variant="secondary" disabled={prazoVencido} aria-describedby={prazoVencido ? `prazo-${job.id}` : undefined} aria-label={`Reprocessar ${job.nome} a partir de uma etapa`} onClick={() => pedir(job, 'etapa')}>
                          <IconRefresh aria-hidden />
                          Reprocessar…
                        </Button>
                      )}
                      {prazoVencido && ((podeReprocessar && partida) || (podeEscolherEtapa && job.estado === 'concluido' && !emAndamento(job))) && (
                        <p id={`prazo-${job.id}`} className="text-xs text-muted-foreground">{AVISO_DO_REPROCESSAMENTO}</p>
                      )}
                    </div>
                  </td>
                </tr>
                {aberta && (
                  <tr className="bg-card">
                    <td colSpan={colunas} className="border-b px-2 py-2">
                      <EtapasDoJob job={job} agora={agora} />
                    </td>
                  </tr>
                )}
                {doPedido === 'falha' && partida && (
                  <tr>
                    <td colSpan={colunas} className="border-b px-2">
                      <ConfirmarReprocesso
                        job={job}
                        etapa={partida}
                        aoCancelar={() => setPedido(null)}
                        aoConfirmar={async (motivo) => trocarJob(await api.job(job.id).reprocessarOQueFalhou(motivo), partida)}
                      />
                    </td>
                  </tr>
                )}
                {doPedido === 'etapa' && (
                  <tr>
                    <td colSpan={colunas} className="border-b px-2">
                      <ReprocessarEtapa job={job} aoCancelar={() => setPedido(null)} aoReprocessar={trocarJob} />
                    </td>
                  </tr>
                )}
              </tbody>
            )
          })}
          <Folga altura={depois} colunas={colunas} />
        </table>
      )}
      {pronta && haMais && (
        <div className="flex justify-center">
          <Button type="button" variant="secondary" size="sm" disabled={lista.isFetchingNextPage} onClick={() => void lista.fetchNextPage()}>
            Carregar mais
          </Button>
        </div>
      )}
    </Aba>
  )
}
