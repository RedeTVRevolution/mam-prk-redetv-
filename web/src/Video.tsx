import {
  ActionIcon,
  Alert,
  AspectRatio,
  Badge,
  Box,
  Center,
  Chip,
  Drawer,
  Grid,
  Group,
  Button,
  Loader,
  Menu,
  Modal,
  NavLink,
  Paper,
  Progress,
  Select,
  ScrollArea,
  SegmentedControl,
  Slider,
  Stack,
  Switch,
  Text,
  TextInput,
  Textarea,
  Tooltip,
  UnstyledButton,
  type MantineColor,
} from '@mantine/core'
import {
  IconDotsVertical,
  IconDownload,
  IconHistory,
  IconPencil,
  IconPlus,
} from '@tabler/icons-react'
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type RefObject,
} from 'react'
import { chamarApi, SessaoExpirada } from './api.ts'
import type { Autenticador } from './auth/autenticador.ts'
import {
  comoSelect,
  ContextoDoCatalogo,
  pessoaDoModelo,
  rotuloDe,
  useCatalogo,
  type CatalogoDeCorrecoes,
} from './catalogo.ts'
import { CORES, CORES_DE_OCORRENCIA } from './tema.ts'

export interface JobAberto {
  id: string
  nome: string
  estado: string
  codigo_falha: string | null
}

interface Intervalo {
  inicio_ms: number
  fim_ms: number
}

type Aparicao = Intervalo & {
  evidencia: string
  papel?: string | null
  visual?: string | null
}

interface Pessoa {
  id: string
  nome: string
  origem?: 'modelo' | 'revisao'
  /** 1.2: de onde veio o nome; falta em 1.1 e em pessoa acrescentada pela revisão. */
  fontes_do_nome?: string[]
  na_imagem: Aparicao[]
  citada_na_fala: Intervalo[]
  citada_no_texto: (Intervalo & { texto: string })[]
}

type ListaDePessoa = 'na_imagem' | 'citada_na_fala' | 'citada_no_texto'

/** O que o Editor pede sobre uma aparição ou menção (ou acrescentar uma aparição). */
type AcaoDeOcorrencia =
  | {
      tipo: 'nao_e' | 'aparicao_para_mencao' | 'mencao_para_aparicao' | 'tempos'
      pessoa: Pessoa
      lista: ListaDePessoa
      inicio_ms: number
      fim_ms: number
    }
  | { tipo: 'acrescentar'; pessoa: Pessoa | null }

interface Pauta extends Intervalo {
  id: string
  titulo: string
  resumo?: string
  tom?: string | null
  origem?: 'modelo' | 'revisao'
}

interface Plano extends Intervalo {
  id: string
  ambiente: string
  acao?: string | null
  objetos?: string[]
  plano_limpo?: boolean
  origem?: 'modelo' | 'revisao'
}

interface Fala extends Intervalo {
  id?: string
  locutor: string
  texto: string
  origem?: 'modelo' | 'revisao'
}

/** O trecho (plano ou fala) que o Editor está corrigindo. */
type Trecho = { tipo: 'plano'; plano: Plano } | { tipo: 'fala'; fala: Fala }

interface Comercial extends Intervalo {
  id?: string
  marca: string
  tipo: string
  /** 1.2; decupagens 1.1 trazem só `evidencia` (texto). */
  evidencias?: Evidencia[]
  evidencia?: string
  origem?: 'modelo' | 'revisao'
  acrescentado?: boolean
}

const EVIDENCIAS = ['fala', 'logo', 'texto_na_tela', 'produto'] as const
type Evidencia = (typeof EVIDENCIAS)[number]

/** O campo do esquema 1.2 que o Editor corrige no modal `CorrigirCampo`. */
type CampoAberto =
  | { modo: 'tom'; pauta: Pauta }
  | { modo: 'fontes'; pessoa: Pessoa }
  | { modo: 'papel'; pessoa: Pessoa; aparicao: Aparicao }
  | { modo: 'texto'; texto: TextoNaTela; id: string }
  | { modo: 'novo_texto' }

interface TextoNaTela extends Intervalo {
  id?: string
  origem?: 'modelo' | 'revisao'
  acrescentado?: boolean
  tipo: string
  texto: string
}

export interface Decupagem {
  versao_decupagem?: string
  video?: { duracao_ms: number }
  pautas: Pauta[]
  pessoas: Pessoa[]
  planos: Plano[]
  comerciais: Comercial[]
  transcricao: Fala[]
  /** 1.2; falta nas decupagens 1.1. */
  textos_na_tela?: TextoNaTela[]
}

interface Reproducao {
  url: string
  expira_em: string
}

/** O que a correção `item.tempos` precisa para achar a ocorrência no servidor. */
type Alvo =
  | { tipo: 'pauta'; id: string }
  | { tipo: 'comercial'; id: string }
  | { tipo: 'pessoa'; id: string; lista: ListaDePessoa }

interface Ocorrencia extends Intervalo {
  chave: string
  /** Só as ocorrências de tipos com correção de tempo têm alvo. */
  alvo?: Alvo
}

/** A ocorrência selecionada na linha do tempo, com o intervalo de antes da correção. */
interface Selecao {
  /** A decupagem em que a ocorrência foi selecionada: a chave é um índice e só vale nela. */
  decupagem: Decupagem
  chave: string
  alvo: Alvo
  original: Intervalo
}

/** Quanto as setas movem uma alça: 100 ms, ou 1 s com Shift. */
const PASSO_DA_ALCA_MS = 100
const PASSO_GRANDE_DA_ALCA_MS = 1000

interface Faixa {
  nome: string
  cor: MantineColor
  ocorrencias: Ocorrencia[]
}

// Menor largura de uma ocorrência na linha do tempo, para não sumir.
const LARGURA_MINIMA_MS = 1500
const LARGURA_DO_ROTULO = 120

function tempo(ms: number): string {
  const total = Math.floor(ms / 1000)
  const mm = String(Math.floor(total / 60)).padStart(2, '0')
  const ss = String(total % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

/** "mm:ss" em milissegundos; `null` se não for um tempo. */
function lerTempo(texto: string): number | null {
  const achado = /^(\d{1,3}):([0-5]\d)$/.exec(texto.trim())
  return achado ? (Number(achado[1]) * 60 + Number(achado[2])) * 1000 : null
}

/** O campo em mm:ss, em ms: o valor original, com os milissegundos, se o Editor não o mudou. */
function tempoDoCampo(texto: string, originalMs: number): number | null {
  const ms = lerTempo(texto)
  return ms !== null && ms === lerTempo(tempo(originalMs)) ? originalMs : ms
}

function faixasDe(d: Decupagem, catalogo: CatalogoDeCorrecoes): Faixa[] {
  const de = <T extends Intervalo>(
    prefixo: string,
    lista: T[],
    alvo?: (x: T) => Alvo | undefined,
  ): Ocorrencia[] =>
    lista.map((x, i) => ({
      chave: `${prefixo}-${i}`,
      inicio_ms: x.inicio_ms,
      fim_ms: x.fim_ms,
      alvo: alvo?.(x),
    }))
  const daPessoa = (lista: ListaDePessoa) =>
    d.pessoas.flatMap((p) =>
      p[lista].map((x) => ({
        ...x,
        alvo: pessoaDoModelo(catalogo, p) ? { pessoa: p.id, lista } : null,
      })),
    )
  const alvoDaPessoa = (x: { alvo: { pessoa: string; lista: ListaDePessoa } | null }) =>
    x.alvo ? ({ tipo: 'pessoa', id: x.alvo.pessoa, lista: x.alvo.lista } as const) : undefined
  return [
    {
      nome: 'Pautas',
      cor: CORES_DE_OCORRENCIA.pauta.cor,
      ocorrencias: de('pauta', d.pautas, (p) => ({ tipo: 'pauta', id: p.id })),
    },
    {
      nome: 'Aparições',
      cor: CORES_DE_OCORRENCIA.aparicao.cor,
      ocorrencias: de('img', daPessoa('na_imagem'), alvoDaPessoa),
    },
    {
      nome: 'Menções',
      cor: CORES_DE_OCORRENCIA.mencao.cor,
      ocorrencias: de(
        'mencao',
        [...daPessoa('citada_na_fala'), ...daPessoa('citada_no_texto')],
        alvoDaPessoa,
      ),
    },
    {
      nome: 'Comerciais',
      cor: CORES_DE_OCORRENCIA.comercial.cor,
      ocorrencias: de('com', d.comerciais, (c) =>
        c.id && !c.acrescentado ? { tipo: 'comercial', id: c.id } : undefined,
      ),
    },
    {
      nome: 'Planos',
      // Fora do mapa de tipos: os planos saem da linha do tempo no redesenho do Visualizador.
      cor: 'dark.3',
      ocorrencias: de('plano', d.planos),
    },
    {
      nome: 'Fala',
      cor: CORES_DE_OCORRENCIA.fala.cor,
      ocorrencias: de('fala', d.transcricao),
    },
    {
      nome: 'Texto na tela',
      cor: CORES_DE_OCORRENCIA.texto_na_tela.cor,
      ocorrencias: de('texto', d.textos_na_tela ?? []),
    },
  ]
}

function maiorFim(faixas: Faixa[]): number {
  return Math.max(0, ...faixas.flatMap((f) => f.ocorrencias.map((o) => o.fim_ms)))
}

type Borda = 'inicio' | 'fim'

/** Os comandos das alças da linha do tempo; só existem para quem tem `decupagem.editar`. */
interface AlcasDaLinha {
  selecionada: string | null
  /** Até onde a alça de fim vai: a duração do vídeo na decupagem, que é o que a API confere. */
  limiteMs: number
  aoSelecionar: (o: Ocorrencia) => void
  aoMover: (borda: Borda, ms: number) => void
  aoSoltar: () => void
}

/** Alça de início ou de fim da ocorrência selecionada: arrasta com o ponteiro ou move com as setas. */
function AlcaDoTempo({
  borda,
  ms,
  minMs,
  maxMs,
  duracaoMs,
  trilha,
  alcas,
}: {
  borda: Borda
  ms: number
  minMs: number
  maxMs: number
  duracaoMs: number
  trilha: RefObject<HTMLDivElement | null>
  alcas: AlcasDaLinha
}) {
  const arrastando = useRef(false)
  const limitar = (valor: number) => Math.round(Math.min(maxMs, Math.max(minMs, valor)))
  const mover = (valor: number) => alcas.aoMover(borda, limitar(valor))
  // Soltar, cancelar o gesto ou perder a captura encerram o arraste: sem isso, a alça
  // seguiria o ponteiro sem botão pressionado.
  const soltar = () => {
    if (!arrastando.current) return
    arrastando.current = false
    alcas.aoSoltar()
  }
  return (
    <Box
      role="slider"
      tabIndex={0}
      aria-label={borda === 'inicio' ? 'Início da ocorrência' : 'Fim da ocorrência'}
      aria-valuemin={minMs}
      aria-valuemax={maxMs}
      aria-valuenow={ms}
      aria-valuetext={tempo(ms)}
      pos="absolute"
      top={-3}
      w={8}
      h={20}
      bg="white"
      style={{
        left: `${(ms / duracaoMs) * 100}%`,
        transform: 'translateX(-50%)',
        borderRadius: 2,
        cursor: 'ew-resize',
        touchAction: 'none',
        zIndex: 2,
      }}
      onPointerDown={(e: PointerEvent<HTMLDivElement>) => {
        arrastando.current = true
        e.currentTarget.setPointerCapture?.(e.pointerId)
      }}
      onPointerMove={(e: PointerEvent<HTMLDivElement>) => {
        const caixa = trilha.current?.getBoundingClientRect()
        if (!arrastando.current || !caixa || caixa.width === 0) return
        mover(((e.clientX - caixa.left) / caixa.width) * duracaoMs)
      }}
      onPointerUp={soltar}
      onPointerCancel={soltar}
      onLostPointerCapture={soltar}
      onKeyDown={(e: KeyboardEvent<HTMLDivElement>) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          alcas.aoSoltar()
          return
        }
        const sentido = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
        if (sentido === 0) return
        e.preventDefault()
        mover(ms + sentido * (e.shiftKey ? PASSO_GRANDE_DA_ALCA_MS : PASSO_DA_ALCA_MS))
      }}
    />
  )
}

/** Uma faixa da linha do tempo: ocorrências na cor da faixa e vãos transparentes. */
function FaixaDoTempo({
  faixa,
  duracaoMs,
  saltar,
  alcas,
}: {
  faixa: Faixa
  duracaoMs: number
  saltar: (ms: number) => void
  alcas?: AlcasDaLinha
}) {
  const trilha = useRef<HTMLDivElement>(null)
  const selecionada = faixa.ocorrencias.find((o) => o.chave === alcas?.selecionada)
  const ordenadas = [...faixa.ocorrencias].sort((a, b) => a.inicio_ms - b.inicio_ms)
  const secoes = []
  // Uma faixa é uma fileira só: o trecho que se sobrepõe ao anterior não é desenhado de
  // novo. Cada ocorrência fica no seu tempo, sem empurrar as seguintes.
  let cursor = 0
  for (const o of ordenadas) {
    // A largura mínima cresce para a esquerda quando a ocorrência encosta no fim.
    const fim = Math.min(Math.max(o.fim_ms, o.inicio_ms + LARGURA_MINIMA_MS), duracaoMs)
    const inicio = Math.max(cursor, Math.min(o.inicio_ms, fim - LARGURA_MINIMA_MS))
    if (fim <= inicio) continue
    if (inicio > cursor) {
      secoes.push(
        <Progress.Section
          key={`vao-${o.chave}`}
          value={((inicio - cursor) / duracaoMs) * 100}
          color="transparent"
        />,
      )
    }
    secoes.push(
      <Progress.Section
        key={o.chave}
        value={((fim - inicio) / duracaoMs) * 100}
        color={faixa.cor}
        role="button"
        tabIndex={0}
        aria-label={`${faixa.nome} ${tempo(o.inicio_ms)}`}
        aria-pressed={alcas && o.alvo ? o.chave === alcas.selecionada : undefined}
        style={{
          cursor: 'pointer',
          outline: o.chave === alcas?.selecionada ? '2px solid white' : undefined,
        }}
        onClick={() => {
          saltar(o.inicio_ms)
          if (o.alvo) alcas?.aoSelecionar(o)
        }}
        onKeyDown={(e: KeyboardEvent<HTMLDivElement>) => {
          if (e.key !== 'Enter' && e.key !== ' ') return
          e.preventDefault()
          saltar(o.inicio_ms)
          if (o.alvo) alcas?.aoSelecionar(o)
        }}
      />,
    )
    cursor = fim
  }
  return (
    <Group gap="sm" wrap="nowrap">
      <Text size="xs" w={LARGURA_DO_ROTULO} ta="right" c="dimmed">
        {faixa.nome}
      </Text>
      <Box ref={trilha} pos="relative" flex={1}>
        <Progress.Root size={14} radius="xs" bg="dark.6">
          {secoes}
        </Progress.Root>
        {alcas && selecionada && (
          <>
            <AlcaDoTempo
              borda="inicio"
              ms={selecionada.inicio_ms}
              minMs={0}
              maxMs={selecionada.fim_ms}
              duracaoMs={duracaoMs}
              trilha={trilha}
              alcas={alcas}
            />
            <AlcaDoTempo
              borda="fim"
              ms={selecionada.fim_ms}
              minMs={selecionada.inicio_ms}
              maxMs={Math.min(duracaoMs, alcas.limiteMs)}
              duracaoMs={duracaoMs}
              trilha={trilha}
              alcas={alcas}
            />
          </>
        )}
      </Box>
    </Group>
  )
}

const ABAS = ['Pessoas', 'Pautas', 'Marcas', 'Planos', 'Fala', 'Texto na tela'] as const
type Aba = (typeof ABAS)[number]

const dentro = (atualMs: number, i: Intervalo) => atualMs >= i.inicio_ms && atualMs < i.fim_ms

type Carga =
  | { tipo: 'carregando' }
  | { tipo: 'erro' }
  | {
      tipo: 'pronta'
      reproducao: Reproducao
      decupagem: Decupagem
      catalogo: CatalogoDeCorrecoes
    }

export default function Video({
  autenticador,
  job,
  aoSessaoExpirada,
  podeEditar = false,
  podeAprovar = false,
}: {
  autenticador: Autenticador
  job: JobAberto
  aoSessaoExpirada: () => void
  podeEditar?: boolean
  podeAprovar?: boolean
}) {
  const player = useRef<HTMLVideoElement>(null)
  const [carga, setCarga] = useState<Carga>({ tipo: 'carregando' })
  const concluido = job.estado === 'concluido'
  const [corrigindo, setCorrigindo] = useState<Pessoa | null>(null)
  const [ocorrenciaAberta, setOcorrenciaAberta] = useState<AcaoDeOcorrencia | null>(null)
  const [corrigindoPauta, setCorrigindoPauta] = useState<Pauta | null>(null)
  const [trechoAberto, setTrechoAberto] = useState<Trecho | null>(null)
  const [comercialAberto, setComercialAberto] = useState<Comercial | 'novo' | null>(null)
  const [campoAberto, setCampoAberto] = useState<CampoAberto | null>(null)
  const [historicoAberto, setHistoricoAberto] = useState(false)
  const [filaAberta, setFilaAberta] = useState(false)
  const [fila, setFila] = useState<ItemDaFila[]>([])
  const [recargaDaFila, setRecargaDaFila] = useState(0)
  // Itens com correção pendente de aprovação (`chaveDoItem`), da decupagem aberta.
  const [pendentes, setPendentes] = useState<Set<string>>(new Set())
  // O pai recria o callback a cada render; o efeito não deve recarregar por isso.
  const sessaoExpirada = useRef(aoSessaoExpirada)
  useEffect(() => {
    sessaoExpirada.current = aoSessaoExpirada
  })

  useEffect(() => {
    if (!concluido) return
    let ativo = true
    Promise.all([
      chamarApi<Reproducao>(autenticador, `/v1/jobs/${job.id}/reproducao`),
      chamarApi<Decupagem>(autenticador, `/v1/jobs/${job.id}/decupagem`),
      chamarApi<CatalogoDeCorrecoes>(autenticador, '/v1/correcoes/catalogo'),
    ]).then(
      ([reproducao, decupagem, catalogo]) => {
        if (ativo) setCarga({ tipo: 'pronta', reproducao, decupagem, catalogo })
      },
      (erro: unknown) => {
        if (!ativo) return
        if (erro instanceof SessaoExpirada) sessaoExpirada.current()
        else setCarga({ tipo: 'erro' })
      },
    )
    return () => {
      ativo = false
    }
  }, [autenticador, job.id, concluido])

  // A fila de revisão só existe para quem edita; falhar aqui não derruba a tela.
  useEffect(() => {
    if (!concluido || !podeEditar) return
    let ativo = true
    chamarApi<ItemDaFila[]>(autenticador, `/v1/jobs/${job.id}/fila`).then(
      (itens) => {
        if (ativo) setFila(itens)
      },
      (erro: unknown) => {
        if (ativo && erro instanceof SessaoExpirada) sessaoExpirada.current()
      },
    )
    return () => {
      ativo = false
    }
  }, [autenticador, job.id, concluido, podeEditar, recargaDaFila])

  // As pendentes saem da decupagem entregue: o selo vem do histórico, que é recarregado a
  // cada nova decupagem (toda correção, aprovação ou recusa recarrega o painel).
  const decupagemAtual = carga.tipo === 'pronta' ? carga.decupagem : null
  useEffect(() => {
    if (!podeEditar || !decupagemAtual) return
    let ativo = true
    chamarApi<ItemDoHistorico[]>(autenticador, `/v1/jobs/${job.id}/correcoes`).then(
      (itens) => {
        if (!ativo) return
        setPendentes(
          new Set(
            itens
              .filter(
                (i) =>
                  i.estado === 'pendente' && i.ancora.versao === decupagemAtual.versao_decupagem,
              )
              .map((i) => chaveDoItem(i.ancora.tipo_do_item, i.item_id)),
          ),
        )
      },
      (erro: unknown) => {
        if (ativo && erro instanceof SessaoExpirada) sessaoExpirada.current()
      },
    )
    return () => {
      ativo = false
    }
  }, [autenticador, job.id, podeEditar, decupagemAtual])

  // Depois de uma correção, só o painel recarrega: o player segue no mesmo link e ponto.
  const recarregarDecupagem = useCallback(() => {
    chamarApi<Decupagem>(autenticador, `/v1/jobs/${job.id}/decupagem`).then(
      (decupagem) => setCarga((c) => (c.tipo === 'pronta' ? { ...c, decupagem } : c)),
      (erro: unknown) => {
        if (erro instanceof SessaoExpirada) sessaoExpirada.current()
        else setCarga({ tipo: 'erro' })
      },
    )
  }, [autenticador, job.id])

  const retomarEm = useRef<number | null>(null)
  // O link assinado expira em minutos: se o player falhar depois disso, pede outro e
  // continua do mesmo ponto.
  const renovarLink = useCallback(() => {
    if (carga.tipo !== 'pronta') return
    if (Date.parse(carga.reproducao.expira_em) > Date.now()) return
    const instante = player.current?.currentTime ?? 0
    chamarApi<Reproducao>(autenticador, `/v1/jobs/${job.id}/reproducao`).then(
      (reproducao) => {
        retomarEm.current = instante
        setCarga((atual) => (atual.tipo === 'pronta' ? { ...atual, reproducao } : atual))
      },
      (erro: unknown) => {
        if (erro instanceof SessaoExpirada) sessaoExpirada.current()
        else setCarga({ tipo: 'erro' })
      },
    )
  }, [autenticador, carga, job.id])
  const retomar = useCallback(() => {
    if (player.current && retomarEm.current !== null) {
      player.current.currentTime = retomarEm.current
      retomarEm.current = null
    }
  }, [])

  const saltar = useCallback((inicioMs: number) => {
    if (player.current) player.current.currentTime = inicioMs / 1000
  }, [])

  const [atualMs, setAtualMs] = useState(0)
  const [duracaoDoPlayerMs, setDuracaoDoPlayerMs] = useState<number | null>(null)
  const [aba, setAba] = useState<Aba>('Pessoas')
  // Alças da linha do tempo: a ocorrência selecionada, o intervalo arrastado (`null` = sem
  // mudança) e se o modal de confirmação está aberto.
  const [selecao, setSelecao] = useState<Selecao | null>(null)
  const [arrastado, setArrastado] = useState<Intervalo | null>(null)
  const [confirmandoTempos, setConfirmandoTempos] = useState(false)

  if (!concluido) {
    return job.estado === 'falhou' ? (
      <Alert color="red" variant="light" role="alert">
        {`O vídeo falhou: ${job.codigo_falha ?? 'sem código'}`}
      </Alert>
    ) : (
      <Alert color="gray" variant="light" role="alert">
        O vídeo ainda não foi decupado.
      </Alert>
    )
  }
  if (carga.tipo === 'carregando') {
    return (
      <Center h="50vh">
        <Loader role="status" aria-label="Carregando o vídeo" />
      </Center>
    )
  }
  if (carga.tipo === 'erro') {
    return (
      <Alert color="red" variant="light" role="alert">
        Não foi possível carregar o vídeo.
      </Alert>
    )
  }

  const { decupagem, reproducao, catalogo } = carga
  // Depois de recarregar a decupagem, a seleção antiga não vale mais (os índices podem ter
  // mudado). O modal aberto segue com ela, para mostrar o antes e depois que enviou.
  const selecaoAtual = selecao?.decupagem === decupagem ? selecao : null
  const faixas = faixasDe(decupagem, catalogo).map((f) =>
    selecaoAtual && arrastado
      ? {
          ...f,
          ocorrencias: f.ocorrencias.map((o) =>
            o.chave === selecaoAtual.chave ? { ...o, ...arrastado } : o,
          ),
        }
      : f,
  )
  const alcas: AlcasDaLinha | undefined = podeEditar
    ? {
        selecionada: selecaoAtual?.chave ?? null,
        limiteMs: decupagem.video?.duracao_ms ?? Infinity,
        aoSelecionar: (o) => {
          if (!o.alvo || o.chave === selecaoAtual?.chave) return
          setArrastado(null)
          setSelecao({
            decupagem,
            chave: o.chave,
            alvo: o.alvo,
            original: { inicio_ms: o.inicio_ms, fim_ms: o.fim_ms },
          })
        },
        aoMover: (borda, ms) => {
          if (!selecaoAtual) return
          const { original } = selecaoAtual
          setArrastado((a) => ({
            ...(a ?? original),
            [borda === 'inicio' ? 'inicio_ms' : 'fim_ms']: ms,
          }))
          saltar(ms)
        },
        aoSoltar: () => {
          if (!selecaoAtual) return
          if (
            arrastado &&
            (arrastado.inicio_ms !== selecaoAtual.original.inicio_ms ||
              arrastado.fim_ms !== selecaoAtual.original.fim_ms)
          )
            setConfirmandoTempos(true)
          else setArrastado(null)
        },
      }
    : undefined
  const duracaoMs = Math.max(duracaoDoPlayerMs ?? maiorFim(faixas), 1)
  const quadro = (i: Intervalo) => `${reproducao.url}#t=${i.inicio_ms / 1000 + 1}`

  return (
    <ContextoDoCatalogo.Provider value={catalogo}>
      <Grid gap="sm">
        <Grid.Col span={{ base: 12, lg: 8 }}>
          <Stack gap="sm">
            <Group justify="space-between">
              <Text fw={700}>{job.nome}</Text>
              <Text ff="monospace" size="xl" style={{ fontVariantNumeric: 'tabular-nums' }}>
                {`${tempo(atualMs)} / ${tempo(duracaoMs)}`}
              </Text>
            </Group>
            <AspectRatio ratio={16 / 9}>
              <video
                ref={player}
                src={reproducao.url}
                controls
                onError={renovarLink}
                onLoadedMetadata={(e) => {
                  retomar()
                  // Sem duração conhecida (NaN, ou Infinity num stream), fica a da decupagem.
                  const duracao = e.currentTarget.duration
                  setDuracaoDoPlayerMs(Number.isFinite(duracao) ? duracao * 1000 : null)
                }}
                onTimeUpdate={(e) => setAtualMs(e.currentTarget.currentTime * 1000)}
                aria-label="Player"
                style={{ background: '#000' }}
              />
            </AspectRatio>
            <Paper p="sm" withBorder>
              <Stack gap={6}>
                <Group gap="sm" wrap="nowrap">
                  <Box w={LARGURA_DO_ROTULO} />
                  <Slider
                    flex={1}
                    min={0}
                    max={duracaoMs}
                    step={1000}
                    value={atualMs}
                    onChange={saltar}
                    size="xs"
                    label={tempo}
                  />
                </Group>
                {faixas.map((faixa) => (
                  <FaixaDoTempo
                    key={faixa.nome}
                    faixa={faixa}
                    duracaoMs={duracaoMs}
                    saltar={saltar}
                    alcas={alcas}
                  />
                ))}
              </Stack>
            </Paper>
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, lg: 4 }}>
          <Paper withBorder p="sm" h="calc(100vh - 76px)" aria-label="Decupagem">
            <Stack h="100%" gap="sm">
              <Group justify="space-between">
                <SegmentedControl
                  size="xs"
                  data={[...ABAS]}
                  value={aba}
                  onChange={(v) => setAba(v as Aba)}
                />
                <Group gap="xs">
                  {podeEditar && fila.length > 0 && (
                    <Badge
                      component="button"
                      type="button"
                      color="orange"
                      variant="light"
                      style={{ cursor: 'pointer' }}
                      onClick={() => setFilaAberta(true)}
                    >
                      {`${fila.length} na fila`}
                    </Badge>
                  )}
                  {podeEditar && (
                    <Tooltip label="Histórico de correções">
                      <ActionIcon
                        variant="default"
                        aria-label="Histórico"
                        onClick={() => setHistoricoAberto(true)}
                      >
                        <IconHistory />
                      </ActionIcon>
                    </Tooltip>
                  )}
                  <BaixarJson nome={job.nome} decupagem={decupagem} />
                </Group>
              </Group>
              <ScrollArea flex={1}>
                {aba === 'Pessoas' && (
                  <AbaPessoas
                    decupagem={decupagem}
                    quadro={quadro}
                    saltar={saltar}
                    pendentes={pendentes}
                    aoCorrigir={podeEditar ? setCorrigindo : undefined}
                    aoOcorrencia={podeEditar ? setOcorrenciaAberta : undefined}
                    aoCampo={podeEditar ? setCampoAberto : undefined}
                  />
                )}
                {aba === 'Pautas' &&
                  decupagem.pautas.map((p, i) => (
                    <Group key={`pauta-${i}`} gap={4} wrap="nowrap">
                      <NavLink
                        flex={1}
                        label={
                          <Group gap={6} wrap="nowrap">
                            <Text size="sm">{p.titulo}</Text>
                            {p.tom && (
                              <Badge size="xs" color="gray" variant="outline">
                                {rotuloDe(catalogo.tons_da_pauta, p.tom)}
                              </Badge>
                            )}
                            {p.origem === 'revisao' && (
                              <Badge size="xs" color="teal" variant="light">
                                revisado
                              </Badge>
                            )}
                            {pendentes.has(chaveDoItem('pauta', p.id)) && <SeloAguardando />}
                          </Group>
                        }
                        description={`${tempo(p.inicio_ms)}–${tempo(p.fim_ms)}`}
                        active={dentro(atualMs, p)}
                        onClick={() => saltar(p.inicio_ms)}
                      />
                      {podeEditar && 'tom' in p && (
                        <ActionIcon
                          variant="subtle"
                          color="gray"
                          size="sm"
                          aria-label={`Corrigir tom da pauta ${p.titulo}`}
                          onClick={() => setCampoAberto({ modo: 'tom', pauta: p })}
                        >
                          <IconPencil size={14} />
                        </ActionIcon>
                      )}
                      {podeEditar && (
                        <ActionIcon
                          variant="subtle"
                          color="gray"
                          size="sm"
                          aria-label={`Corrigir pauta ${p.titulo}`}
                          onClick={() => setCorrigindoPauta(p)}
                        >
                          <IconPencil size={14} />
                        </ActionIcon>
                      )}
                    </Group>
                  ))}
                {aba === 'Marcas' && podeEditar && (
                  <Button
                    type="button"
                    variant="light"
                    size="xs"
                    mb={4}
                    onClick={() => setComercialAberto('novo')}
                  >
                    Acrescentar comercial
                  </Button>
                )}
                {aba === 'Marcas' &&
                  decupagem.comerciais.map((c, i) => (
                    <Group key={`com-${i}`} gap={4} wrap="nowrap">
                      <NavLink
                        flex={1}
                        label={
                          <Group gap={6} wrap="nowrap">
                            <Text size="sm">{c.marca}</Text>
                            {(c.evidencias ?? (c.evidencia ? [c.evidencia] : [])).map((e) => (
                              <Badge key={e} size="xs" color="gray" variant="outline">
                                {e}
                              </Badge>
                            ))}
                            {c.origem === 'revisao' && (
                              <Badge size="xs" color="teal" variant="light">
                                revisado
                              </Badge>
                            )}
                            {pendentes.has(chaveDoItem('comercial', c.id)) && <SeloAguardando />}
                          </Group>
                        }
                        description={`${c.tipo} · ${tempo(c.inicio_ms)}`}
                        onClick={() => saltar(c.inicio_ms)}
                      />
                      {podeEditar && c.id && !c.acrescentado && (
                        <ActionIcon
                          variant="subtle"
                          color="gray"
                          size="sm"
                          aria-label={`Corrigir comercial ${c.marca}`}
                          onClick={() => setComercialAberto(c)}
                        >
                          <IconPencil size={14} />
                        </ActionIcon>
                      )}
                    </Group>
                  ))}
                {aba === 'Planos' &&
                  decupagem.planos.map((p) => (
                    <Group key={p.id} gap={4} wrap="nowrap">
                      <NavLink
                        flex={1}
                        label={
                          <Group gap={6} wrap="nowrap">
                            <Text size="sm">{p.acao ?? p.ambiente}</Text>
                            {p.plano_limpo && (
                              <Badge size="xs" color="gray" variant="light">
                                limpo
                              </Badge>
                            )}
                            {p.origem === 'revisao' && (
                              <Badge size="xs" color="teal" variant="light">
                                revisado
                              </Badge>
                            )}
                            {pendentes.has(chaveDoItem('plano', p.id)) && <SeloAguardando />}
                          </Group>
                        }
                        description={
                          <>
                            {`${p.ambiente} · ${tempo(p.inicio_ms)}`}
                            {p.objetos && p.objetos.length > 0 && (
                              <Text span size="xs" display="block">
                                {p.objetos.join(', ')}
                              </Text>
                            )}
                          </>
                        }
                        onClick={() => saltar(p.inicio_ms)}
                      />
                      {podeEditar && (
                        <ActionIcon
                          variant="subtle"
                          color="gray"
                          size="sm"
                          aria-label={`Corrigir plano ${p.ambiente} ${tempo(p.inicio_ms)}`}
                          onClick={() => setTrechoAberto({ tipo: 'plano', plano: p })}
                        >
                          <IconPencil size={14} />
                        </ActionIcon>
                      )}
                    </Group>
                  ))}
                {aba === 'Fala' &&
                  decupagem.transcricao.map((f, i) => (
                    <Group key={`fala-${i}`} gap={4} wrap="nowrap" align="flex-start">
                      <UnstyledButton
                        flex={1}
                        aria-current={dentro(atualMs, f) || undefined}
                        onClick={() => saltar(f.inicio_ms)}
                      >
                        {/* Item atual: barra de 3 px na cor de foco e fundo um pouco mais claro. */}
                        <Paper
                          p={6}
                          bg={dentro(atualMs, f) ? 'dark.5' : 'transparent'}
                          style={{
                            borderLeft: `3px solid ${dentro(atualMs, f) ? CORES.foco : 'transparent'}`,
                          }}
                        >
                          <Group gap={6} wrap="nowrap">
                            <Text size="xs" ff="monospace" c="dimmed">
                              {`${tempo(f.inicio_ms)} ${f.locutor.toUpperCase()}`}
                            </Text>
                            {f.origem === 'revisao' && (
                              <Badge size="xs" color="teal" variant="light">
                                revisado
                              </Badge>
                            )}
                            {pendentes.has(chaveDoItem('fala', f.id)) && <SeloAguardando />}
                          </Group>
                          <Text size="sm">{f.texto}</Text>
                        </Paper>
                      </UnstyledButton>
                      {podeEditar && f.id && (
                        <ActionIcon
                          variant="subtle"
                          color="gray"
                          size="sm"
                          mt={6}
                          aria-label={`Corrigir fala ${tempo(f.inicio_ms)}`}
                          onClick={() => setTrechoAberto({ tipo: 'fala', fala: f })}
                        >
                          <IconPencil size={14} />
                        </ActionIcon>
                      )}
                    </Group>
                  ))}
                {aba === 'Texto na tela' && podeEditar && (
                  <Button
                    type="button"
                    variant="light"
                    size="xs"
                    mb={4}
                    onClick={() => setCampoAberto({ modo: 'novo_texto' })}
                  >
                    Acrescentar texto na tela
                  </Button>
                )}
                {aba === 'Texto na tela' &&
                  (decupagem.textos_na_tela ?? []).map((t, i) => {
                    // O id (`txt000`) é a posição no modelo e vem da API; o acrescentado não tem.
                    const id = t.id
                    return (
                      <Group key={`texto-${i}`} gap={4} wrap="nowrap">
                        <NavLink
                          flex={1}
                          label={
                            <Group gap={6} wrap="nowrap">
                              <Text size="sm">{t.texto}</Text>
                              {t.origem === 'revisao' && (
                                <Badge size="xs" color="teal" variant="light">
                                  revisado
                                </Badge>
                              )}
                              {id && pendentes.has(chaveDoItem('texto_na_tela', id)) && (
                                <SeloAguardando />
                              )}
                            </Group>
                          }
                          description={`${tempo(t.inicio_ms)} · ${t.tipo}`}
                          active={dentro(atualMs, t)}
                          onClick={() => saltar(t.inicio_ms)}
                        />
                        {podeEditar && id && !t.acrescentado && (
                          <ActionIcon
                            variant="subtle"
                            color="gray"
                            size="sm"
                            aria-label={`Corrigir texto na tela ${t.texto}`}
                            onClick={() => setCampoAberto({ modo: 'texto', texto: t, id })}
                          >
                            <IconPencil size={14} />
                          </ActionIcon>
                        )}
                      </Group>
                    )
                  })}
              </ScrollArea>
            </Stack>
          </Paper>
        </Grid.Col>
        {podeEditar && (
          <FilaDeRevisao
            aberta={filaAberta}
            itens={fila}
            autenticador={autenticador}
            jobId={job.id}
            aoFechar={() => setFilaAberta(false)}
            aoResolver={() => {
              setRecargaDaFila((n) => n + 1)
              recarregarDecupagem()
            }}
            aoSessaoExpirada={() => sessaoExpirada.current()}
          />
        )}
        {podeEditar && (
          <HistoricoDeCorrecoes
            aberto={historicoAberto}
            autenticador={autenticador}
            jobId={job.id}
            aoFechar={() => setHistoricoAberto(false)}
            podeAprovar={podeAprovar}
            aoMudar={recarregarDecupagem}
            aoSessaoExpirada={() => sessaoExpirada.current()}
          />
        )}
        <CorrigirPessoa
          key={corrigindo?.id ?? 'fechado'}
          pessoa={corrigindo}
          versao={decupagem.versao_decupagem ?? ''}
          autenticador={autenticador}
          jobId={job.id}
          aoFechar={() => setCorrigindo(null)}
          aoSalvar={() => {
            setCorrigindo(null)
            recarregarDecupagem()
          }}
          aoVersaoDesatualizada={recarregarDecupagem}
          aoSessaoExpirada={() => sessaoExpirada.current()}
        />
        <CorrigirOcorrencia
          key={ocorrenciaAberta ? JSON.stringify(ocorrenciaAberta) : 'fechada'}
          acao={ocorrenciaAberta}
          pessoas={decupagem.pessoas.filter((p) => pessoaDoModelo(catalogo, p))}
          versao={decupagem.versao_decupagem ?? ''}
          autenticador={autenticador}
          jobId={job.id}
          aoFechar={() => setOcorrenciaAberta(null)}
          aoSalvar={() => {
            setOcorrenciaAberta(null)
            recarregarDecupagem()
          }}
          aoVersaoDesatualizada={recarregarDecupagem}
          aoSessaoExpirada={() => sessaoExpirada.current()}
        />
        <CorrigirPauta
          key={corrigindoPauta?.id ?? 'fechada'}
          pauta={corrigindoPauta}
          versao={decupagem.versao_decupagem ?? ''}
          autenticador={autenticador}
          jobId={job.id}
          aoFechar={() => setCorrigindoPauta(null)}
          aoSalvar={() => {
            setCorrigindoPauta(null)
            recarregarDecupagem()
          }}
          aoVersaoDesatualizada={recarregarDecupagem}
          aoSessaoExpirada={() => sessaoExpirada.current()}
        />
        <CorrigirTempos
          key={confirmandoTempos ? 'tempos-aberto' : 'tempos-fechado'}
          selecao={confirmandoTempos ? selecao : null}
          depois={arrastado}
          versao={decupagem.versao_decupagem ?? ''}
          autenticador={autenticador}
          jobId={job.id}
          aoFechar={() => {
            // Cancelar devolve a ocorrência ao intervalo anterior.
            setConfirmandoTempos(false)
            setArrastado(null)
          }}
          aoSalvar={() => {
            // O intervalo arrastado fica na linha do tempo até a decupagem recarregada chegar;
            // aí a seleção antiga deixa de valer e as alças somem.
            setConfirmandoTempos(false)
            recarregarDecupagem()
          }}
          aoVersaoDesatualizada={recarregarDecupagem}
          aoSessaoExpirada={() => sessaoExpirada.current()}
        />
        <CorrigirTrecho
          key={
            trechoAberto
              ? trechoAberto.tipo === 'plano'
                ? trechoAberto.plano.id
                : trechoAberto.fala.id
              : 'fechado'
          }
          trecho={trechoAberto}
          versao={decupagem.versao_decupagem ?? ''}
          autenticador={autenticador}
          jobId={job.id}
          aoFechar={() => setTrechoAberto(null)}
          aoSalvar={() => {
            setTrechoAberto(null)
            recarregarDecupagem()
          }}
          aoVersaoDesatualizada={recarregarDecupagem}
          aoSessaoExpirada={() => sessaoExpirada.current()}
        />
        <CorrigirCampo
          key={campoAberto ? JSON.stringify(campoAberto) : 'fechado'}
          campo={campoAberto}
          versao={decupagem.versao_decupagem ?? ''}
          autenticador={autenticador}
          jobId={job.id}
          aoFechar={() => setCampoAberto(null)}
          aoSalvar={() => {
            setCampoAberto(null)
            recarregarDecupagem()
          }}
          aoVersaoDesatualizada={recarregarDecupagem}
          aoSessaoExpirada={() => sessaoExpirada.current()}
        />
        <CorrigirComercial
          key={comercialAberto === 'novo' ? 'novo' : (comercialAberto?.id ?? 'fechado')}
          comercial={comercialAberto}
          versao={decupagem.versao_decupagem ?? ''}
          autenticador={autenticador}
          jobId={job.id}
          aoFechar={() => setComercialAberto(null)}
          aoSalvar={() => {
            setComercialAberto(null)
            recarregarDecupagem()
          }}
          aoVersaoDesatualizada={recarregarDecupagem}
          aoSessaoExpirada={() => sessaoExpirada.current()}
        />
      </Grid>
    </ContextoDoCatalogo.Provider>
  )
}

/** Chave dos itens com correção pendente: o item é achado pelo tipo e pelo id. */
const chaveDoItem = (tipoDoItem: string, id?: string) => `${tipoDoItem}:${id ?? ''}`

/** O item tem correção de Editor esperando o Curador: ela ainda não está na decupagem. */
function SeloAguardando() {
  return (
    <Badge size="xs" color="yellow" variant="light">
      aguardando Curador
    </Badge>
  )
}

/** Nome da pessoa, com o selo de revisão e, para quem edita, o botão de corrigir. */
function NomeDaPessoa({
  pessoa,
  fw,
  aguardando,
  aoCorrigir,
}: {
  pessoa: Pessoa
  fw?: number
  aguardando?: boolean
  aoCorrigir?: (p: Pessoa) => void
}) {
  return (
    <Group gap={6} wrap="nowrap">
      <Text size="sm" fw={fw}>
        {pessoa.nome}
      </Text>
      {pessoa.origem === 'revisao' && (
        <Badge size="xs" color="teal" variant="light">
          revisado
        </Badge>
      )}
      {aguardando && <SeloAguardando />}
      {aoCorrigir && (
        <ActionIcon
          variant="subtle"
          color="gray"
          size="sm"
          aria-label={`Corrigir ${pessoa.nome}`}
          onClick={() => aoCorrigir(pessoa)}
        >
          <IconPencil size={14} />
        </ActionIcon>
      )}
    </Group>
  )
}

/** Modal da Ilha de edição: novo nome e motivo; a API confere a permissão e a versão. */
function CorrigirPessoa({
  pessoa,
  versao,
  autenticador,
  jobId,
  aoFechar,
  aoSalvar,
  aoVersaoDesatualizada,
  aoSessaoExpirada,
}: {
  pessoa: Pessoa | null
  versao: string
  autenticador: Autenticador
  jobId: string
  aoFechar: () => void
  aoSalvar: () => void
  aoVersaoDesatualizada: () => void
  aoSessaoExpirada: () => void
}) {
  const catalogo = useCatalogo()
  const [nome, setNome] = useState(pessoa?.nome ?? '')
  const [motivo, setMotivo] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [salvando, setSalvando] = useState(false)

  async function salvar() {
    if (!pessoa) return
    setSalvando(true)
    setErro(null)
    try {
      await chamarApi(autenticador, `/v1/jobs/${jobId}/correcoes`, {
        metodo: 'POST',
        corpo: {
          tipo: 'pessoa.renomear',
          item_id: pessoa.id,
          valor: nome,
          motivo,
          versao,
        },
      })
      aoSalvar()
    } catch (e) {
      if (e instanceof SessaoExpirada) aoSessaoExpirada()
      else if (e instanceof Error && e.message.startsWith('Falha 409')) {
        // Recarrega o painel: a versão nova chega ao modal e o Editor pode salvar de novo.
        aoVersaoDesatualizada()
        setErro('A decupagem mudou e foi recarregada. Confira e salve de novo.')
      } else setErro('Não foi possível salvar a correção.')
      setSalvando(false)
    }
  }

  return (
    <Modal opened={pessoa !== null} onClose={aoFechar} title="Corrigir pessoa" centered>
      <Stack gap="sm">
        <TextInput
          label="Nome"
          value={nome}
          maxLength={catalogo.limites.nome}
          onChange={(e) => setNome(e.currentTarget.value)}
        />
        <Textarea
          label="Motivo"
          value={motivo}
          maxLength={catalogo.limites.motivo}
          rows={3}
          onChange={(e) => setMotivo(e.currentTarget.value)}
        />
        {erro && (
          <Alert color="red" variant="light" role="alert">
            {erro}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button type="button" variant="default" onClick={aoFechar}>
            Cancelar
          </Button>
          <Button
            type="button"
            loading={salvando}
            disabled={!nome.trim() || !motivo.trim()}
            onClick={() => void salvar()}
          >
            Salvar
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

/** Menu das ações de uma aparição ou menção da pessoa. */
function MenuDaOcorrencia({
  pessoa,
  lista,
  ocorrencia,
  aoEscolher,
}: {
  pessoa: Pessoa
  lista: ListaDePessoa
  ocorrencia: Intervalo
  aoEscolher: (a: AcaoDeOcorrencia) => void
}) {
  const escolher = (tipo: 'nao_e' | 'aparicao_para_mencao' | 'mencao_para_aparicao' | 'tempos') =>
    aoEscolher({
      tipo,
      pessoa,
      lista,
      inicio_ms: ocorrencia.inicio_ms,
      fim_ms: ocorrencia.fim_ms,
    })
  return (
    <Menu withinPortal position="bottom-end">
      <Menu.Target>
        <ActionIcon
          variant="subtle"
          color="gray"
          size="xs"
          aria-label={`Ações de ${pessoa.nome} em ${tempo(ocorrencia.inicio_ms)}`}
        >
          <IconDotsVertical size={12} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Item onClick={() => escolher('nao_e')}>Não é esta pessoa</Menu.Item>
        {lista === 'na_imagem' ? (
          <Menu.Item onClick={() => escolher('aparicao_para_mencao')}>
            Só é citada (não aparece)
          </Menu.Item>
        ) : (
          <Menu.Item onClick={() => escolher('mencao_para_aparicao')}>Aparece na imagem</Menu.Item>
        )}
        <Menu.Item onClick={() => escolher('tempos')}>Corrigir tempos</Menu.Item>
      </Menu.Dropdown>
    </Menu>
  )
}

const NOVA_PESSOA = '__nova__'

/** Modal das correções de aparição e menção: cada ação pede só o que a API exige, mais o motivo. */
function CorrigirOcorrencia({
  acao,
  pessoas,
  versao,
  autenticador,
  jobId,
  aoFechar,
  aoSalvar,
  aoVersaoDesatualizada,
  aoSessaoExpirada,
}: {
  acao: AcaoDeOcorrencia | null
  pessoas: Pessoa[]
  versao: string
  autenticador: Autenticador
  jobId: string
  aoFechar: () => void
  aoSalvar: () => void
  aoVersaoDesatualizada: () => void
  aoSessaoExpirada: () => void
}) {
  const catalogo = useCatalogo()
  const [destino, setDestino] = useState<string>('citada_na_fala')
  const [evidencia, setEvidencia] = useState('')
  const [pessoaId, setPessoaId] = useState(
    acao?.tipo === 'acrescentar' ? (acao.pessoa?.id ?? NOVA_PESSOA) : '',
  )
  const [nome, setNome] = useState('')
  const [inicio, setInicio] = useState(acao && acao.tipo === 'tempos' ? tempo(acao.inicio_ms) : '')
  const [fim, setFim] = useState(acao && acao.tipo === 'tempos' ? tempo(acao.fim_ms) : '')
  const [motivo, setMotivo] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [salvando, setSalvando] = useState(false)

  const inicioMs = acao?.tipo === 'tempos' ? tempoDoCampo(inicio, acao.inicio_ms) : lerTempo(inicio)
  const fimMs = acao?.tipo === 'tempos' ? tempoDoCampo(fim, acao.fim_ms) : lerTempo(fim)
  const temposValidos = inicioMs !== null && fimMs !== null && inicioMs <= fimMs
  const pessoaNova = pessoaId === NOVA_PESSOA

  const TITULOS = {
    nao_e: 'Não é esta pessoa',
    aparicao_para_mencao: 'Só é citada',
    mencao_para_aparicao: 'Aparece na imagem',
    tempos: 'Corrigir tempos',
    acrescentar: 'Acrescentar aparição',
  } as const

  function pedido(): Record<string, unknown> | null {
    if (!acao) return null
    if (acao.tipo === 'acrescentar') {
      if (!temposValidos || !evidencia.trim() || (pessoaNova && !nome.trim())) return null
      return {
        tipo: 'pessoa.acrescentar_aparicao',
        item_id: pessoaNova ? '' : pessoaId,
        valor: JSON.stringify({
          inicio_ms: inicioMs,
          fim_ms: fimMs,
          evidencia: evidencia.trim(),
          ...(pessoaNova ? { nome: nome.trim() } : {}),
        }),
      }
    }
    const ocorrencia = {
      lista: acao.lista,
      inicio_ms: acao.inicio_ms,
      fim_ms: acao.fim_ms,
    }
    const base = { item_id: acao.pessoa.id, ocorrencia }
    switch (acao.tipo) {
      case 'nao_e':
        return { ...base, tipo: 'pessoa.nao_e', valor: 'Não identificado' }
      case 'aparicao_para_mencao':
        return { ...base, tipo: 'pessoa.aparicao_para_mencao', valor: destino }
      case 'mencao_para_aparicao':
        return evidencia.trim()
          ? {
              ...base,
              tipo: 'pessoa.mencao_para_aparicao',
              valor: evidencia.trim(),
            }
          : null
      case 'tempos':
        return temposValidos && (inicioMs !== acao.inicio_ms || fimMs !== acao.fim_ms)
          ? {
              ...base,
              tipo: 'item.tempos',
              tipo_do_item: 'pessoa',
              valor: `${inicioMs}-${fimMs}`,
            }
          : null
    }
  }

  const corpo = pedido()

  async function salvar() {
    if (!corpo) return
    setSalvando(true)
    setErro(null)
    try {
      await chamarApi(autenticador, `/v1/jobs/${jobId}/correcoes`, {
        metodo: 'POST',
        corpo: { ...corpo, motivo, versao },
      })
      aoSalvar()
    } catch (e) {
      if (e instanceof SessaoExpirada) aoSessaoExpirada()
      else if (e instanceof Error && e.message.startsWith('Falha 409')) {
        aoVersaoDesatualizada()
        setErro('A decupagem mudou e foi recarregada. Confira e salve de novo.')
      } else if (e instanceof Error && e.message.startsWith('Falha 422')) {
        setErro(
          acao?.tipo === 'acrescentar' || acao?.tipo === 'tempos'
            ? 'Confira os campos: os tempos ficam dentro da duração do vídeo.'
            : 'A ocorrência não foi encontrada. Recarregue a página e confira.',
        )
      } else setErro('Não foi possível salvar a correção.')
      setSalvando(false)
    }
  }

  return (
    <Modal
      opened={acao !== null}
      onClose={aoFechar}
      title={acao ? TITULOS[acao.tipo] : ''}
      centered
    >
      <Stack gap="sm">
        {acao && acao.tipo !== 'acrescentar' && (
          <Text size="sm">
            {`${acao.pessoa.nome}, ${tempo(acao.inicio_ms)}–${tempo(acao.fim_ms)}`}
          </Text>
        )}
        {acao?.tipo === 'nao_e' && (
          <Text size="sm" c="dimmed">
            O trecho passa para uma pessoa “não identificado”.
          </Text>
        )}
        {acao?.tipo === 'aparicao_para_mencao' && (
          <Select
            label="Citada"
            allowDeselect={false}
            data={[
              { value: 'citada_na_fala', label: 'Na fala' },
              { value: 'citada_no_texto', label: 'No texto' },
            ]}
            value={destino}
            onChange={(v) => setDestino(v ?? 'citada_na_fala')}
          />
        )}
        {acao?.tipo === 'acrescentar' && (
          <Select
            label="Pessoa"
            allowDeselect={false}
            data={[
              { value: NOVA_PESSOA, label: 'Nova pessoa' },
              ...pessoas.map((p) => ({ value: p.id, label: p.nome })),
            ]}
            value={pessoaId}
            onChange={(v) => setPessoaId(v ?? NOVA_PESSOA)}
          />
        )}
        {acao?.tipo === 'acrescentar' && pessoaNova && (
          <TextInput
            label="Nome"
            value={nome}
            maxLength={catalogo.limites.nome}
            onChange={(e) => setNome(e.currentTarget.value)}
          />
        )}
        {(acao?.tipo === 'acrescentar' || acao?.tipo === 'tempos') && (
          <Group grow align="flex-start">
            <TextInput
              label="Início (mm:ss)"
              value={inicio}
              error={inicio && lerTempo(inicio) === null ? 'Use mm:ss' : undefined}
              onChange={(e) => setInicio(e.currentTarget.value)}
            />
            <TextInput
              label="Fim (mm:ss)"
              value={fim}
              error={fim && lerTempo(fim) === null ? 'Use mm:ss' : undefined}
              onChange={(e) => setFim(e.currentTarget.value)}
            />
          </Group>
        )}
        {(acao?.tipo === 'acrescentar' || acao?.tipo === 'mencao_para_aparicao') && (
          <TextInput
            label="Evidência"
            description="O que mostra a pessoa na imagem"
            value={evidencia}
            maxLength={catalogo.limites.nome}
            onChange={(e) => setEvidencia(e.currentTarget.value)}
          />
        )}
        <Textarea
          label="Motivo"
          value={motivo}
          maxLength={catalogo.limites.motivo}
          rows={3}
          onChange={(e) => setMotivo(e.currentTarget.value)}
        />
        {erro && (
          <Alert color="red" variant="light" role="alert">
            {erro}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button type="button" variant="default" onClick={aoFechar}>
            Cancelar
          </Button>
          <Button
            type="button"
            loading={salvando}
            disabled={!corpo || !motivo.trim()}
            onClick={() => void salvar()}
          >
            Salvar
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

/** "mm:ss.mmm": o modal dos tempos arrastados mostra os milissegundos. */
function tempoPreciso(ms: number): string {
  return `${tempo(ms)}.${String(ms % 1000).padStart(3, '0')}`
}

/** Modal das alças: mostra antes e depois e pede o motivo; salvar grava um `item.tempos`. */
function CorrigirTempos({
  selecao,
  depois,
  versao,
  autenticador,
  jobId,
  aoFechar,
  aoSalvar,
  aoVersaoDesatualizada,
  aoSessaoExpirada,
}: {
  selecao: Selecao | null
  depois: Intervalo | null
  versao: string
  autenticador: Autenticador
  jobId: string
  aoFechar: () => void
  aoSalvar: () => void
  aoVersaoDesatualizada: () => void
  aoSessaoExpirada: () => void
}) {
  const catalogo = useCatalogo()
  const [motivo, setMotivo] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [salvando, setSalvando] = useState(false)

  const aberto = selecao !== null && depois !== null

  async function salvar() {
    if (!selecao || !depois) return
    const { alvo, original } = selecao
    const base = { tipo: 'item.tempos', item_id: alvo.id, motivo, versao }
    const valor = `${depois.inicio_ms}-${depois.fim_ms}`
    const corpo =
      alvo.tipo === 'pessoa'
        ? {
            ...base,
            tipo_do_item: 'pessoa',
            ocorrencia: { lista: alvo.lista, ...original },
            valor,
          }
        : alvo.tipo === 'comercial'
          ? { ...base, tipo_do_item: 'comercial', valor }
          : { ...base, valor }
    setSalvando(true)
    setErro(null)
    try {
      await chamarApi(autenticador, `/v1/jobs/${jobId}/correcoes`, {
        metodo: 'POST',
        corpo,
      })
      aoSalvar()
    } catch (e) {
      if (e instanceof SessaoExpirada) aoSessaoExpirada()
      else if (e instanceof Error && e.message.startsWith('Falha 409')) {
        aoVersaoDesatualizada()
        setErro('A decupagem mudou e foi recarregada. Cancele e arraste de novo.')
      } else if (e instanceof Error && e.message.startsWith('Falha 422')) {
        setErro(
          'Confira os tempos: ficam dentro da duração do vídeo e a ocorrência precisa existir.',
        )
      } else setErro('Não foi possível salvar a correção.')
      setSalvando(false)
    }
  }

  return (
    <Modal opened={aberto} onClose={aoFechar} title="Corrigir tempos" centered>
      {selecao && depois && (
        <Stack gap="sm">
          <Text size="sm">{`Antes: ${tempoPreciso(selecao.original.inicio_ms)}–${tempoPreciso(selecao.original.fim_ms)}`}</Text>
          <Text size="sm" fw={700}>
            {`Depois: ${tempoPreciso(depois.inicio_ms)}–${tempoPreciso(depois.fim_ms)}`}
          </Text>
          <Textarea
            label="Motivo"
            value={motivo}
            maxLength={catalogo.limites.motivo}
            rows={3}
            onChange={(e) => setMotivo(e.currentTarget.value)}
          />
          {erro && (
            <Alert color="red" variant="light" role="alert">
              {erro}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button type="button" variant="default" onClick={aoFechar}>
              Cancelar
            </Button>
            <Button
              type="button"
              loading={salvando}
              disabled={!motivo.trim()}
              onClick={() => void salvar()}
            >
              Salvar
            </Button>
          </Group>
        </Stack>
      )}
    </Modal>
  )
}

/** Modal da pauta: título, resumo, início e fim (mm:ss) e motivo. Cada campo mudado vira uma correção. */
function CorrigirPauta({
  pauta,
  versao,
  autenticador,
  jobId,
  aoFechar,
  aoSalvar,
  aoVersaoDesatualizada,
  aoSessaoExpirada,
}: {
  pauta: Pauta | null
  versao: string
  autenticador: Autenticador
  jobId: string
  aoFechar: () => void
  aoSalvar: () => void
  aoVersaoDesatualizada: () => void
  aoSessaoExpirada: () => void
}) {
  const catalogo = useCatalogo()
  const [titulo, setTitulo] = useState(pauta?.titulo ?? '')
  const [resumo, setResumo] = useState(pauta?.resumo ?? '')
  const [inicio, setInicio] = useState(pauta ? tempo(pauta.inicio_ms) : '')
  const [fim, setFim] = useState(pauta ? tempo(pauta.fim_ms) : '')
  const [motivo, setMotivo] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [salvando, setSalvando] = useState(false)
  // O que já foi gravado neste modal (tipo → valor): numa falha no meio, não reenviar.
  const [gravadas, setGravadas] = useState<Record<string, string>>({})

  const inicioMs = pauta ? tempoDoCampo(inicio, pauta.inicio_ms) : null
  const fimMs = pauta ? tempoDoCampo(fim, pauta.fim_ms) : null
  const temposValidos = inicioMs !== null && fimMs !== null && inicioMs <= fimMs
  const temposMudaram = pauta !== null && (inicioMs !== pauta.inicio_ms || fimMs !== pauta.fim_ms)
  const resumoApagado = !resumo.trim() && !!pauta?.resumo
  const candidatas: { tipo: ItemDoHistorico['tipo']; valor: string }[] = []
  if (pauta && titulo.trim() !== pauta.titulo)
    candidatas.push({ tipo: 'pauta.titulo', valor: titulo })
  if (pauta && !resumoApagado && resumo.trim() !== (pauta.resumo ?? ''))
    candidatas.push({ tipo: 'pauta.resumo', valor: resumo })
  if (temposMudaram && temposValidos)
    candidatas.push({ tipo: 'item.tempos', valor: `${inicioMs}-${fimMs}` })
  const mudancas = candidatas.filter((m) => gravadas[m.tipo] !== m.valor)

  async function salvar() {
    if (!pauta) return
    setSalvando(true)
    setErro(null)
    const feitas = { ...gravadas }
    try {
      for (const m of mudancas) {
        await chamarApi(autenticador, `/v1/jobs/${jobId}/correcoes`, {
          metodo: 'POST',
          corpo: { ...m, item_id: pauta.id, motivo, versao },
        })
        feitas[m.tipo] = m.valor
      }
      aoSalvar()
    } catch (e) {
      setGravadas(feitas)
      if (e instanceof SessaoExpirada) aoSessaoExpirada()
      else if (e instanceof Error && e.message.startsWith('Falha 409')) {
        aoVersaoDesatualizada()
        setErro('A decupagem mudou e foi recarregada. Confira e salve de novo.')
      } else if (e instanceof Error && e.message.startsWith('Falha 422')) {
        setErro('Confira os campos: os tempos ficam dentro da duração do vídeo.')
      } else setErro('Não foi possível salvar a correção.')
      setSalvando(false)
    }
  }

  // Fechar depois de gravar parte dos campos recarrega a decupagem, como o salvar.
  function fechar() {
    if (Object.keys(gravadas).length > 0) aoSalvar()
    else aoFechar()
  }

  return (
    <Modal opened={pauta !== null} onClose={fechar} title="Corrigir pauta" centered>
      <Stack gap="sm">
        <TextInput
          label="Título"
          value={titulo}
          maxLength={catalogo.limites.nome}
          onChange={(e) => setTitulo(e.currentTarget.value)}
        />
        <Textarea
          label="Resumo"
          value={resumo}
          maxLength={catalogo.limites.texto}
          rows={4}
          error={resumoApagado ? 'O resumo não pode ficar vazio' : undefined}
          onChange={(e) => setResumo(e.currentTarget.value)}
        />
        <Group grow align="flex-start">
          <TextInput
            label="Início (mm:ss)"
            value={inicio}
            error={lerTempo(inicio) === null ? 'Use mm:ss' : undefined}
            onChange={(e) => setInicio(e.currentTarget.value)}
          />
          <TextInput
            label="Fim (mm:ss)"
            value={fim}
            error={lerTempo(fim) === null ? 'Use mm:ss' : undefined}
            onChange={(e) => setFim(e.currentTarget.value)}
          />
        </Group>
        {inicioMs !== null && fimMs !== null && inicioMs > fimMs && (
          <Text size="xs" c="red">
            O início não pode vir depois do fim.
          </Text>
        )}
        <Textarea
          label="Motivo"
          value={motivo}
          maxLength={catalogo.limites.motivo}
          rows={3}
          onChange={(e) => setMotivo(e.currentTarget.value)}
        />
        {erro && (
          <Alert color="red" variant="light" role="alert">
            {erro}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button type="button" variant="default" onClick={fechar}>
            Cancelar
          </Button>
          <Button
            type="button"
            loading={salvando}
            disabled={
              !titulo.trim() ||
              !motivo.trim() ||
              (temposMudaram && !temposValidos) ||
              resumoApagado ||
              mudancas.length === 0
            }
            onClick={() => void salvar()}
          >
            Salvar
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

const TITULOS_DO_CAMPO = {
  tom: 'Corrigir tom da pauta',
  fontes: 'Corrigir fontes do nome',
  papel: 'Corrigir papel na cena e visual',
  texto: 'Corrigir texto na tela',
  novo_texto: 'Acrescentar texto na tela',
} as const

/** Modal dos campos do esquema 1.2: um pedido por modal, com o motivo. */
function CorrigirCampo({
  campo,
  versao,
  autenticador,
  jobId,
  aoFechar,
  aoSalvar,
  aoVersaoDesatualizada,
  aoSessaoExpirada,
}: {
  campo: CampoAberto | null
  versao: string
  autenticador: Autenticador
  jobId: string
  aoFechar: () => void
  aoSalvar: () => void
  aoVersaoDesatualizada: () => void
  aoSessaoExpirada: () => void
}) {
  const catalogo = useCatalogo()
  const [tom, setTom] = useState<string | null>(
    campo?.modo === 'tom' &&
      campo.pauta.tom &&
      catalogo.tons_da_pauta.some((o) => o.valor === campo.pauta.tom)
      ? campo.pauta.tom
      : null,
  )
  const [fontes, setFontes] = useState<string[]>(
    campo?.modo === 'fontes' ? (campo.pessoa.fontes_do_nome ?? []) : [],
  )
  const [papel, setPapel] = useState(campo?.modo === 'papel' ? (campo.aparicao.papel ?? '') : '')
  const [visual, setVisual] = useState(campo?.modo === 'papel' ? (campo.aparicao.visual ?? '') : '')
  const [tipoDoTexto, setTipoDoTexto] = useState<string | null>(
    campo?.modo === 'texto' ? campo.texto.tipo : null,
  )
  const [texto, setTexto] = useState(campo?.modo === 'texto' ? campo.texto.texto : '')
  const [inicio, setInicio] = useState('')
  const [fim, setFim] = useState('')
  const [motivo, setMotivo] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [salvando, setSalvando] = useState(false)

  const inicioMs = lerTempo(inicio)
  const fimMs = lerTempo(fim)

  function pedido(): Record<string, unknown> | null {
    switch (campo?.modo) {
      case 'tom':
        return tom ? { tipo: 'pauta.tom', item_id: campo.pauta.id, valor: tom } : null
      case 'fontes':
        return {
          tipo: 'pessoa.fontes_do_nome',
          item_id: campo.pessoa.id,
          // Na ordem do esquema, não na ordem dos cliques.
          valor: JSON.stringify(
            catalogo.fontes_do_nome.map((o) => o.valor).filter((f) => fontes.includes(f)),
          ),
        }
      case 'papel':
        return {
          tipo: 'aparicao.papel_visual',
          item_id: campo.pessoa.id,
          ocorrencia: {
            lista: 'na_imagem',
            inicio_ms: campo.aparicao.inicio_ms,
            fim_ms: campo.aparicao.fim_ms,
          },
          valor: JSON.stringify({
            papel: papel.trim() || null,
            visual: visual.trim() || null,
          }),
        }
      case 'texto':
        return tipoDoTexto && texto.trim()
          ? {
              tipo: 'texto_na_tela.texto',
              item_id: campo.id,
              valor: JSON.stringify({ tipo: tipoDoTexto, texto: texto.trim() }),
            }
          : null
      case 'novo_texto':
        return tipoDoTexto &&
          texto.trim() &&
          inicioMs !== null &&
          fimMs !== null &&
          inicioMs <= fimMs
          ? {
              tipo: 'texto_na_tela.acrescentar',
              item_id: '',
              valor: JSON.stringify({
                inicio_ms: inicioMs,
                fim_ms: fimMs,
                tipo: tipoDoTexto,
                texto: texto.trim(),
              }),
            }
          : null
      default:
        return null
    }
  }

  const corpo = pedido()

  async function salvar() {
    if (!corpo) return
    setSalvando(true)
    setErro(null)
    try {
      await chamarApi(autenticador, `/v1/jobs/${jobId}/correcoes`, {
        metodo: 'POST',
        corpo: { ...corpo, motivo, versao },
      })
      aoSalvar()
    } catch (e) {
      if (e instanceof SessaoExpirada) aoSessaoExpirada()
      else if (e instanceof Error && e.message.startsWith('Falha 409')) {
        aoVersaoDesatualizada()
        setErro('A decupagem mudou e foi recarregada. Confira e salve de novo.')
      } else if (e instanceof Error && e.message.startsWith('Falha 422')) {
        setErro('Confira os campos: o valor não foi aceito.')
      } else setErro('Não foi possível salvar a correção.')
      setSalvando(false)
    }
  }

  const tipoDeTexto = (
    <Select
      label="Tipo"
      data={comoSelect(catalogo.tipos_de_texto_na_tela)}
      value={tipoDoTexto}
      allowDeselect={false}
      onChange={setTipoDoTexto}
    />
  )

  return (
    <Modal
      opened={campo !== null}
      onClose={aoFechar}
      title={campo ? TITULOS_DO_CAMPO[campo.modo] : ''}
      centered
    >
      <Stack gap="sm">
        {campo?.modo === 'tom' && (
          <Select
            label="Tom"
            data={comoSelect(catalogo.tons_da_pauta)}
            value={tom}
            allowDeselect={false}
            onChange={setTom}
          />
        )}
        {campo?.modo === 'fontes' && (
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Fontes do nome
            </Text>
            <Chip.Group multiple value={fontes} onChange={setFontes}>
              <Group gap={6}>
                {catalogo.fontes_do_nome.map(({ valor, rotulo }) => (
                  <Chip key={valor} value={valor} size="xs">
                    {rotulo}
                  </Chip>
                ))}
              </Group>
            </Chip.Group>
          </Stack>
        )}
        {campo?.modo === 'papel' && (
          <>
            <TextInput
              label="Papel na cena"
              value={papel}
              maxLength={catalogo.limites.nome}
              onChange={(e) => setPapel(e.currentTarget.value)}
            />
            <TextInput
              label="Visual"
              value={visual}
              maxLength={catalogo.limites.nome}
              onChange={(e) => setVisual(e.currentTarget.value)}
            />
          </>
        )}
        {(campo?.modo === 'texto' || campo?.modo === 'novo_texto') && (
          <>
            {tipoDeTexto}
            <Textarea
              label="Texto"
              value={texto}
              maxLength={catalogo.limites.texto}
              rows={3}
              onChange={(e) => setTexto(e.currentTarget.value)}
            />
          </>
        )}
        {campo?.modo === 'novo_texto' && (
          <Group grow align="flex-start">
            <TextInput
              label="Início (mm:ss)"
              value={inicio}
              error={inicio !== '' && inicioMs === null ? 'Use mm:ss' : undefined}
              onChange={(e) => setInicio(e.currentTarget.value)}
            />
            <TextInput
              label="Fim (mm:ss)"
              value={fim}
              error={fim !== '' && fimMs === null ? 'Use mm:ss' : undefined}
              onChange={(e) => setFim(e.currentTarget.value)}
            />
          </Group>
        )}
        <Textarea
          label="Motivo"
          value={motivo}
          maxLength={catalogo.limites.motivo}
          rows={3}
          onChange={(e) => setMotivo(e.currentTarget.value)}
        />
        {erro && (
          <Alert color="red" variant="light" role="alert">
            {erro}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button type="button" variant="default" onClick={aoFechar}>
            Cancelar
          </Button>
          <Button
            type="button"
            loading={salvando}
            disabled={!corpo || !motivo.trim()}
            onClick={() => void salvar()}
          >
            Salvar
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

/** Modal do plano (descrição e plano limpo) ou da fala (texto e locutor): os tempos não mudam. */
function CorrigirTrecho({
  trecho,
  versao,
  autenticador,
  jobId,
  aoFechar,
  aoSalvar,
  aoVersaoDesatualizada,
  aoSessaoExpirada,
}: {
  trecho: Trecho | null
  versao: string
  autenticador: Autenticador
  jobId: string
  aoFechar: () => void
  aoSalvar: () => void
  aoVersaoDesatualizada: () => void
  aoSessaoExpirada: () => void
}) {
  const catalogo = useCatalogo()
  const plano = trecho?.tipo === 'plano' ? trecho.plano : null
  const fala = trecho?.tipo === 'fala' ? trecho.fala : null
  const [ambiente, setAmbiente] = useState(plano?.ambiente ?? '')
  const [acao, setAcao] = useState(plano?.acao ?? '')
  const [objetos, setObjetos] = useState((plano?.objetos ?? []).join(', '))
  const [limpo, setLimpo] = useState(plano?.plano_limpo ?? false)
  const [texto, setTexto] = useState(fala?.texto ?? '')
  const [locutor, setLocutor] = useState(fala?.locutor ?? '')
  const [motivo, setMotivo] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [salvando, setSalvando] = useState(false)
  // O que já foi gravado neste modal (tipo → valor): numa falha no meio, não reenviar.
  const [gravadas, setGravadas] = useState<Record<string, string>>({})

  const listaDeObjetos = objetos
    .split(',')
    .map((o) => o.trim())
    .filter(Boolean)
  const candidatas: { tipo: ItemDoHistorico['tipo']; valor: string }[] = []
  if (plano) {
    const mudouDescricao =
      ambiente.trim() !== plano.ambiente ||
      acao.trim() !== (plano.acao ?? '') ||
      listaDeObjetos.join('\n') !== (plano.objetos ?? []).join('\n')
    if (mudouDescricao)
      candidatas.push({
        tipo: 'plano.descricao',
        valor: JSON.stringify({
          ambiente,
          acao: acao.trim() || null,
          objetos: listaDeObjetos,
        }),
      })
    if (limpo !== (plano.plano_limpo ?? false))
      candidatas.push({ tipo: 'plano.limpo', valor: String(limpo) })
  }
  if (fala && (texto.trim() !== fala.texto || locutor.trim() !== fala.locutor))
    candidatas.push({
      tipo: 'fala.texto',
      valor: JSON.stringify({ texto, locutor }),
    })
  const mudancas = candidatas.filter((m) => gravadas[m.tipo] !== m.valor)
  const itemId = plano?.id ?? fala?.id ?? ''

  async function salvar() {
    setSalvando(true)
    setErro(null)
    const feitas = { ...gravadas }
    try {
      for (const m of mudancas) {
        await chamarApi(autenticador, `/v1/jobs/${jobId}/correcoes`, {
          metodo: 'POST',
          corpo: { ...m, item_id: itemId, motivo, versao },
        })
        feitas[m.tipo] = m.valor
      }
      aoSalvar()
    } catch (e) {
      setGravadas(feitas)
      if (e instanceof SessaoExpirada) aoSessaoExpirada()
      else if (e instanceof Error && e.message.startsWith('Falha 409')) {
        aoVersaoDesatualizada()
        setErro('A decupagem mudou e foi recarregada. Confira e salve de novo.')
      } else if (e instanceof Error && e.message.startsWith('Falha 422')) {
        setErro('Confira os campos: o trecho não foi encontrado ou há valor inválido.')
      } else setErro('Não foi possível salvar a correção.')
      setSalvando(false)
    }
  }

  // Fechar depois de gravar parte dos campos recarrega a decupagem, como o salvar.
  function fechar() {
    if (Object.keys(gravadas).length > 0) aoSalvar()
    else aoFechar()
  }

  return (
    <Modal
      opened={trecho !== null}
      onClose={fechar}
      title={plano ? 'Corrigir plano' : 'Corrigir fala'}
      centered
    >
      <Stack gap="sm">
        {plano && (
          <>
            <TextInput
              label="Ambiente"
              value={ambiente}
              maxLength={catalogo.limites.nome}
              onChange={(e) => setAmbiente(e.currentTarget.value)}
            />
            <Textarea
              label="Ação"
              value={acao}
              maxLength={catalogo.limites.texto}
              rows={3}
              onChange={(e) => setAcao(e.currentTarget.value)}
            />
            <TextInput
              label="Objetos (separados por vírgula)"
              value={objetos}
              onChange={(e) => setObjetos(e.currentTarget.value)}
            />
            <Switch
              label="Plano limpo"
              checked={limpo}
              onChange={(e) => setLimpo(e.currentTarget.checked)}
            />
          </>
        )}
        {fala && (
          <>
            <TextInput
              label="Locutor"
              value={locutor}
              maxLength={catalogo.limites.nome}
              onChange={(e) => setLocutor(e.currentTarget.value)}
            />
            <Textarea
              label="Texto"
              value={texto}
              maxLength={catalogo.limites.texto}
              rows={4}
              onChange={(e) => setTexto(e.currentTarget.value)}
            />
          </>
        )}
        <Textarea
          label="Motivo"
          value={motivo}
          maxLength={catalogo.limites.motivo}
          rows={3}
          onChange={(e) => setMotivo(e.currentTarget.value)}
        />
        {erro && (
          <Alert color="red" variant="light" role="alert">
            {erro}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button type="button" variant="default" onClick={fechar}>
            Cancelar
          </Button>
          <Button
            type="button"
            loading={salvando}
            disabled={
              !motivo.trim() ||
              (plano !== null && !ambiente.trim()) ||
              (fala !== null && (!texto.trim() || !locutor.trim())) ||
              mudancas.length === 0
            }
            onClick={() => void salvar()}
          >
            Salvar
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

/** Modal do comercial: corrige marca, tipo e tempos de um comercial ou acrescenta um novo (`'novo'`). */
function CorrigirComercial({
  comercial,
  versao,
  autenticador,
  jobId,
  aoFechar,
  aoSalvar,
  aoVersaoDesatualizada,
  aoSessaoExpirada,
}: {
  comercial: Comercial | 'novo' | null
  versao: string
  autenticador: Autenticador
  jobId: string
  aoFechar: () => void
  aoSalvar: () => void
  aoVersaoDesatualizada: () => void
  aoSessaoExpirada: () => void
}) {
  const catalogo = useCatalogo()
  const novo = comercial === 'novo'
  const atual = comercial !== null && !novo ? comercial : null
  const [marca, setMarca] = useState(atual?.marca ?? '')
  const [tipo, setTipo] = useState<string | null>(atual?.tipo ?? null)
  const [inicio, setInicio] = useState(atual ? tempo(atual.inicio_ms) : '')
  const [fim, setFim] = useState(atual ? tempo(atual.fim_ms) : '')
  const [evidencias, setEvidencias] = useState<string[]>([])
  const [motivo, setMotivo] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [salvando, setSalvando] = useState(false)
  // O que já foi gravado neste modal (tipo → valor): numa falha no meio, não reenviar.
  const [gravadas, setGravadas] = useState<Record<string, string>>({})

  const inicioMs = atual ? tempoDoCampo(inicio, atual.inicio_ms) : lerTempo(inicio)
  const fimMs = atual ? tempoDoCampo(fim, atual.fim_ms) : lerTempo(fim)
  const temposValidos = inicioMs !== null && fimMs !== null && inicioMs <= fimMs
  const candidatas: {
    tipo: ItemDoHistorico['tipo']
    valor: string
    tipo_do_item?: string
  }[] = []
  if (atual) {
    if (marca.trim() !== atual.marca) candidatas.push({ tipo: 'comercial.marca', valor: marca })
    if (tipo && tipo !== atual.tipo) candidatas.push({ tipo: 'comercial.tipo', valor: tipo })
    if (temposValidos && (inicioMs !== atual.inicio_ms || fimMs !== atual.fim_ms))
      candidatas.push({
        tipo: 'item.tempos',
        tipo_do_item: 'comercial',
        valor: `${inicioMs}-${fimMs}`,
      })
  } else if (novo && marca.trim() && tipo && evidencias.length > 0 && temposValidos) {
    candidatas.push({
      tipo: 'comercial.acrescentar',
      valor: JSON.stringify({
        marca: marca.trim(),
        tipo,
        inicio_ms: inicioMs,
        fim_ms: fimMs,
        // Na ordem do esquema, não na ordem dos cliques.
        evidencias: EVIDENCIAS.filter((e) => evidencias.includes(e)),
      }),
    })
  }
  const mudancas = candidatas.filter((m) => gravadas[m.tipo] !== m.valor)
  const temposMudaram = atual !== null && (inicioMs !== atual.inicio_ms || fimMs !== atual.fim_ms)

  async function salvar() {
    setSalvando(true)
    setErro(null)
    const feitas = { ...gravadas }
    try {
      for (const m of mudancas) {
        await chamarApi(autenticador, `/v1/jobs/${jobId}/correcoes`, {
          metodo: 'POST',
          corpo: { ...m, item_id: atual?.id ?? '', motivo, versao },
        })
        feitas[m.tipo] = m.valor
      }
      aoSalvar()
    } catch (e) {
      setGravadas(feitas)
      if (e instanceof SessaoExpirada) aoSessaoExpirada()
      else if (e instanceof Error && e.message.startsWith('Falha 409')) {
        aoVersaoDesatualizada()
        setErro('A decupagem mudou e foi recarregada. Confira e salve de novo.')
      } else if (e instanceof Error && e.message.startsWith('Falha 422')) {
        setErro('Confira os campos: os tempos ficam dentro da duração do vídeo.')
      } else setErro('Não foi possível salvar a correção.')
      setSalvando(false)
    }
  }

  // Fechar depois de gravar parte dos campos recarrega a decupagem, como o salvar.
  function fechar() {
    if (Object.keys(gravadas).length > 0) aoSalvar()
    else aoFechar()
  }

  return (
    <Modal
      opened={comercial !== null}
      onClose={fechar}
      title={novo ? 'Acrescentar comercial' : 'Corrigir comercial'}
      centered
    >
      <Stack gap="sm">
        <TextInput
          label="Marca"
          value={marca}
          maxLength={catalogo.limites.nome}
          onChange={(e) => setMarca(e.currentTarget.value)}
        />
        <Select
          label="Tipo"
          data={comoSelect(catalogo.tipos_de_comercial)}
          value={tipo}
          allowDeselect={false}
          onChange={setTipo}
        />
        <Group grow align="flex-start">
          <TextInput
            label="Início (mm:ss)"
            value={inicio}
            error={lerTempo(inicio) === null && inicio !== '' ? 'Use mm:ss' : undefined}
            onChange={(e) => setInicio(e.currentTarget.value)}
          />
          <TextInput
            label="Fim (mm:ss)"
            value={fim}
            error={lerTempo(fim) === null && fim !== '' ? 'Use mm:ss' : undefined}
            onChange={(e) => setFim(e.currentTarget.value)}
          />
        </Group>
        {inicioMs !== null && fimMs !== null && inicioMs > fimMs && (
          <Text size="xs" c="red">
            O início não pode vir depois do fim.
          </Text>
        )}
        {novo && (
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Evidências
            </Text>
            <Chip.Group multiple value={evidencias} onChange={setEvidencias}>
              <Group gap={6}>
                {EVIDENCIAS.map((e) => (
                  <Chip key={e} value={e} size="xs">
                    {e}
                  </Chip>
                ))}
              </Group>
            </Chip.Group>
          </Stack>
        )}
        <Textarea
          label="Motivo"
          value={motivo}
          maxLength={catalogo.limites.motivo}
          rows={3}
          onChange={(e) => setMotivo(e.currentTarget.value)}
        />
        {erro && (
          <Alert color="red" variant="light" role="alert">
            {erro}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button type="button" variant="default" onClick={fechar}>
            Cancelar
          </Button>
          <Button
            type="button"
            loading={salvando}
            disabled={
              !marca.trim() ||
              !motivo.trim() ||
              (temposMudaram && !temposValidos) ||
              mudancas.length === 0
            }
            onClick={() => void salvar()}
          >
            Salvar
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

interface ItemDoHistorico {
  id: string
  tipo:
    | 'pessoa.renomear'
    | 'pauta.titulo'
    | 'pauta.resumo'
    | 'item.tempos'
    | 'comercial.marca'
    | 'comercial.tipo'
    | 'comercial.acrescentar'
    | 'pessoa.nao_e'
    | 'pessoa.aparicao_para_mencao'
    | 'pessoa.mencao_para_aparicao'
    | 'pessoa.acrescentar_aparicao'
    | 'plano.descricao'
    | 'plano.limpo'
    | 'fala.texto'
    | 'pauta.tom'
    | 'pessoa.fontes_do_nome'
    | 'aparicao.papel_visual'
    | 'texto_na_tela.texto'
    | 'texto_na_tela.acrescentar'
    | 'desfazer'
    | 'descartar'
    | 'aprovar'
    | 'recusar'
  item_id: string
  ancora: { versao: string; tipo_do_item: string }
  autor_email: string
  criada_em: string
  motivo: string
  antes: string
  depois: string
  antes_legivel: string
  depois_legivel: string
  estado: 'ativa' | 'desfeita' | 'reaplicada' | 'descartada' | 'pendente' | 'aprovada' | 'recusada'
  reaplica?: string | null
  desfaz?: string | null
  aprova?: string | null
  recusa?: string | null
}

/** Data da correção que a reaplicação refaz, para ligar uma à outra na gaveta. */
const quandoDaOriginal = (itens: ItemDoHistorico[], id: string) => {
  const original = itens.find((o) => o.id === id)
  return original ? quando(original.criada_em) : id
}

const quando = (iso: string) =>
  new Date(iso).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' })

/** Gaveta com as correções da mais recente à mais antiga; desfazer, aprovar e recusar acrescentam, nada se apaga. */
function HistoricoDeCorrecoes({
  aberto,
  autenticador,
  jobId,
  aoFechar,
  podeAprovar,
  aoMudar,
  aoSessaoExpirada,
}: {
  aberto: boolean
  autenticador: Autenticador
  jobId: string
  aoFechar: () => void
  podeAprovar: boolean
  aoMudar: () => void
  aoSessaoExpirada: () => void
}) {
  const catalogo = useCatalogo()
  const [itens, setItens] = useState<ItemDoHistorico[] | null>(null)
  const [falhou, setFalhou] = useState(false)
  // O que o modal de motivo está pedindo: desfazer uma correção ou recusar uma pendente.
  const [decidindo, setDecidindo] = useState<{
    acao: 'desfazer' | 'recusar'
    item: ItemDoHistorico
  } | null>(null)
  const [aprovando, setAprovando] = useState<string | null>(null)
  const [erroDaLista, setErroDaLista] = useState<string | null>(null)
  const [motivo, setMotivo] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  const [recarga, setRecarga] = useState(0)
  const sessaoExpirada = useRef(aoSessaoExpirada)
  useEffect(() => {
    sessaoExpirada.current = aoSessaoExpirada
  })

  useEffect(() => {
    if (!aberto) return
    let ativo = true
    chamarApi<ItemDoHistorico[]>(autenticador, `/v1/jobs/${jobId}/correcoes`).then(
      (lista) => {
        if (!ativo) return
        setItens(lista)
        setFalhou(false)
      },
      (e: unknown) => {
        if (!ativo) return
        if (e instanceof SessaoExpirada) sessaoExpirada.current()
        else setFalhou(true)
      },
    )
    return () => {
      ativo = false
    }
  }, [aberto, autenticador, jobId, recarga])

  const carregar = () => setRecarga((n) => n + 1)

  function fecharModal() {
    setDecidindo(null)
    setMotivo('')
    setErro(null)
  }

  async function confirmar() {
    if (!decidindo) return
    const { acao, item } = decidindo
    setEnviando(true)
    setErro(null)
    try {
      await chamarApi(
        autenticador,
        `/v1/jobs/${jobId}/correcoes/${item.id}/${acao === 'desfazer' ? 'desfazer' : 'recusar'}`,
        {
          metodo: 'POST',
          corpo: { motivo },
        },
      )
      fecharModal()
      carregar()
      aoMudar()
    } catch (e) {
      if (e instanceof SessaoExpirada) aoSessaoExpirada()
      else if (e instanceof Error && e.message.startsWith('Falha 409')) {
        // Outra pessoa pode ter decidido antes: a decupagem também mudou.
        setErro(
          acao === 'desfazer'
            ? 'Essa correção já foi desfeita, saiu da fila ou não casa com a versão atual. O histórico foi recarregado.'
            : 'Essa correção não está mais pendente. O histórico foi recarregado.',
        )
        carregar()
        aoMudar()
      } else
        setErro(
          acao === 'desfazer'
            ? 'Não foi possível desfazer a correção.'
            : 'Não foi possível recusar a correção.',
        )
    }
    setEnviando(false)
  }

  async function aprovar(item: ItemDoHistorico) {
    setAprovando(item.id)
    setErroDaLista(null)
    try {
      await chamarApi(autenticador, `/v1/jobs/${jobId}/correcoes/${item.id}/aprovar`, {
        metodo: 'POST',
      })
    } catch (e) {
      if (e instanceof SessaoExpirada) aoSessaoExpirada()
      else if (e instanceof Error && e.message.startsWith('Falha 409'))
        setErroDaLista('Essa correção não está mais pendente. O histórico foi recarregado.')
      else setErroDaLista('Não foi possível aprovar a correção.')
    }
    carregar()
    aoMudar()
    setAprovando(null)
  }

  return (
    <>
      <Drawer opened={aberto} onClose={aoFechar} position="right" title="Histórico">
        <Stack gap="sm">
          {falhou && (
            <Alert color="red" variant="light" role="alert">
              Não foi possível carregar o histórico.
            </Alert>
          )}
          {erroDaLista && (
            <Alert color="red" variant="light" role="alert">
              {erroDaLista}
            </Alert>
          )}
          {itens?.length === 0 && <Text size="sm">Nenhuma correção ainda.</Text>}
          {itens?.map((i) => (
            <Paper key={i.id} withBorder p="sm">
              <Stack gap={4}>
                <Group justify="space-between">
                  <Text size="xs" fw={700}>
                    {rotuloDe(catalogo.tipos, i.tipo)}
                  </Text>
                  {i.estado !== 'ativa' && (
                    <Badge size="xs" color="gray" variant="light">
                      {i.estado}
                    </Badge>
                  )}
                </Group>
                <Text size="xs" c="dimmed">
                  {i.autor_email}
                </Text>
                <Text size="xs" c="dimmed">
                  {quando(i.criada_em)}
                </Text>
                <Group gap={4} wrap="nowrap">
                  <Text size="xs" c="dimmed">
                    Antes:
                  </Text>
                  <Text size="sm">{i.antes_legivel}</Text>
                </Group>
                <Group gap={4} wrap="nowrap">
                  <Text size="xs" c="dimmed">
                    Depois:
                  </Text>
                  <Text size="sm" fw={600}>
                    {i.depois_legivel}
                  </Text>
                </Group>
                <Text size="sm">{i.motivo}</Text>
                {i.reaplica && (
                  <Text size="xs" c="dimmed">
                    {`Reaplica a correção de ${quandoDaOriginal(itens, i.reaplica)}`}
                  </Text>
                )}
                {(i.estado === 'ativa' || i.estado === 'aprovada') &&
                  !['desfazer', 'descartar', 'aprovar', 'recusar'].includes(i.tipo) && (
                    <Group justify="flex-end">
                      <Button
                        size="xs"
                        variant="default"
                        onClick={() => setDecidindo({ acao: 'desfazer', item: i })}
                      >
                        Desfazer
                      </Button>
                    </Group>
                  )}
                {i.estado === 'pendente' && podeAprovar && (
                  <Group justify="flex-end">
                    <Button
                      size="xs"
                      variant="default"
                      onClick={() => setDecidindo({ acao: 'recusar', item: i })}
                    >
                      Recusar
                    </Button>
                    <Button size="xs" loading={aprovando === i.id} onClick={() => void aprovar(i)}>
                      Aprovar
                    </Button>
                  </Group>
                )}
              </Stack>
            </Paper>
          ))}
        </Stack>
      </Drawer>
      <Modal
        opened={decidindo !== null}
        onClose={fecharModal}
        title={decidindo?.acao === 'recusar' ? 'Recusar correção' : 'Desfazer correção'}
        centered
      >
        <Stack gap="sm">
          <Textarea
            label="Motivo"
            value={motivo}
            maxLength={catalogo.limites.motivo}
            rows={3}
            onChange={(e) => setMotivo(e.currentTarget.value)}
          />
          {erro && (
            <Alert color="red" variant="light" role="alert">
              {erro}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button type="button" variant="default" onClick={fecharModal}>
              Cancelar
            </Button>
            <Button
              type="button"
              loading={enviando}
              disabled={!motivo.trim()}
              onClick={() => void confirmar()}
            >
              Confirmar
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  )
}

interface ItemDaFila {
  id: string
  tipo: ItemDoHistorico['tipo']
  autor_email: string
  criada_em: string
  motivo: string
  antes: string
  depois: string
  antes_legivel: string
  depois_legivel: string
  candidatos: {
    item_id: string
    nome: string
    inicio_ms: number
    fim_ms: number
  }[]
}

/** Gaveta das correções que não casaram após um reprocessamento: reaplicar num candidato ou descartar. */
function FilaDeRevisao({
  aberta,
  itens,
  autenticador,
  jobId,
  aoFechar,
  aoResolver,
  aoSessaoExpirada,
}: {
  aberta: boolean
  itens: ItemDaFila[]
  autenticador: Autenticador
  jobId: string
  aoFechar: () => void
  aoResolver: () => void
  aoSessaoExpirada: () => void
}) {
  // Fica no painel: o item resolvido some da lista ao recarregar a fila.
  const [aviso, setAviso] = useState<string | null>(null)
  return (
    <Drawer
      opened={aberta}
      onClose={() => {
        setAviso(null)
        aoFechar()
      }}
      position="right"
      title="Fila de revisão"
    >
      <Stack gap="sm">
        {aviso && (
          <Alert color="yellow" variant="light" role="alert">
            {aviso}
          </Alert>
        )}
        {itens.length === 0 && <Text size="sm">Nada na fila.</Text>}
        {itens.map((i) => (
          <ItemDaFilaDeRevisao
            key={i.id}
            item={i}
            autenticador={autenticador}
            jobId={jobId}
            aoResolver={(mensagem) => {
              setAviso(mensagem ?? null)
              aoResolver()
            }}
            aoSessaoExpirada={aoSessaoExpirada}
          />
        ))}
      </Stack>
    </Drawer>
  )
}

function ItemDaFilaDeRevisao({
  item,
  autenticador,
  jobId,
  aoResolver,
  aoSessaoExpirada,
}: {
  item: ItemDaFila
  autenticador: Autenticador
  jobId: string
  /** `aviso`, se houver, sobrevive à recarga da fila. */
  aoResolver: (aviso?: string) => void
  aoSessaoExpirada: () => void
}) {
  const catalogo = useCatalogo()
  const [candidato, setCandidato] = useState<string | null>(null)
  const [motivo, setMotivo] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  async function resolver(acao: 'reaplicar' | 'descartar') {
    setEnviando(true)
    setErro(null)
    try {
      await chamarApi(autenticador, `/v1/jobs/${jobId}/fila/${item.id}/${acao}`, {
        metodo: 'POST',
        corpo: acao === 'reaplicar' ? { item_id: candidato, motivo } : { motivo },
      })
      aoResolver()
    } catch (e) {
      if (e instanceof SessaoExpirada) aoSessaoExpirada()
      else if (e instanceof Error && e.message.startsWith('Falha 409')) {
        // Outro Editor resolveu antes: a fila e a decupagem mudaram.
        aoResolver('Essa correção não está mais na fila. A fila foi recarregada.')
      } else setErro('Não foi possível resolver a correção.')
    }
    setEnviando(false)
  }

  return (
    <Paper withBorder p="sm">
      <Stack gap={4}>
        <Text size="xs" c="dimmed">
          {item.autor_email}
        </Text>
        <Text size="xs" c="dimmed">
          {quando(item.criada_em)}
        </Text>
        <Group gap={4} wrap="nowrap">
          <Text size="xs" c="dimmed">
            Antes:
          </Text>
          <Text size="sm">{item.antes_legivel}</Text>
        </Group>
        <Group gap={4} wrap="nowrap">
          <Text size="xs" c="dimmed">
            Depois:
          </Text>
          <Text size="sm" fw={600}>
            {item.depois_legivel}
          </Text>
        </Group>
        <Text size="sm">{item.motivo}</Text>
        <Select
          label="Candidato"
          placeholder={item.candidatos.length ? 'Escolha o item' : 'Sem candidatos'}
          data={item.candidatos.map((c) => ({
            value: c.item_id,
            label: `${c.nome} (${tempo(c.inicio_ms)}–${tempo(c.fim_ms)})`,
          }))}
          value={candidato}
          onChange={setCandidato}
        />
        <Textarea
          label="Motivo"
          value={motivo}
          maxLength={catalogo.limites.motivo}
          rows={2}
          onChange={(e) => setMotivo(e.currentTarget.value)}
        />
        {erro && (
          <Alert color="red" variant="light" role="alert">
            {erro}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button
            size="xs"
            variant="default"
            loading={enviando}
            disabled={!motivo.trim()}
            onClick={() => void resolver('descartar')}
          >
            Descartar
          </Button>
          <Button
            size="xs"
            loading={enviando}
            disabled={!motivo.trim() || !candidato}
            onClick={() => void resolver('reaplicar')}
          >
            Reaplicar
          </Button>
        </Group>
      </Stack>
    </Paper>
  )
}

function FontesDoNome({
  pessoa,
  aoCorrigir,
}: {
  pessoa: Pessoa
  aoCorrigir?: (c: CampoAberto) => void
}) {
  const catalogo = useCatalogo()
  // Só se corrige o que o modelo trouxe: sem a chave (1.1 ou pessoa da revisão) não há o que trocar.
  const corrigivel = aoCorrigir && pessoaDoModelo(catalogo, pessoa) && 'fontes_do_nome' in pessoa
  if (!pessoa.fontes_do_nome?.length && !corrigivel) return null
  return (
    <Group gap={4} wrap="nowrap" aria-label={`Fontes do nome de ${pessoa.nome}`}>
      {(pessoa.fontes_do_nome ?? []).map((f) => (
        <Badge key={f} size="xs" color="blue" variant="outline">
          {rotuloDe(catalogo.fontes_do_nome, f)}
        </Badge>
      ))}
      {corrigivel && (
        <ActionIcon
          variant="subtle"
          color="gray"
          size="sm"
          aria-label={`Corrigir fontes do nome de ${pessoa.nome}`}
          onClick={() => aoCorrigir({ modo: 'fontes', pessoa })}
        >
          <IconPencil size={14} />
        </ActionIcon>
      )}
    </Group>
  )
}

/** Separa quem aparece de quem só é citado (menção não é aparição). */
function AbaPessoas({
  decupagem,
  quadro,
  saltar,
  pendentes,
  aoCorrigir,
  aoOcorrencia,
  aoCampo,
}: {
  decupagem: Decupagem
  quadro: (i: Intervalo) => string
  saltar: (ms: number) => void
  pendentes: Set<string>
  aoCorrigir?: (p: Pessoa) => void
  aoOcorrencia?: (a: AcaoDeOcorrencia) => void
  aoCampo?: (c: CampoAberto) => void
}) {
  const catalogo = useCatalogo()
  const aparecem = decupagem.pessoas.filter((p) => p.na_imagem.length > 0)
  const citadas = decupagem.pessoas.filter(
    (p) => p.citada_na_fala.length > 0 || p.citada_no_texto.length > 0,
  )
  return (
    <Stack gap="md">
      <Stack gap="xs">
        <Group justify="space-between">
          <Text size="xs" fw={700} tt="uppercase" c="blue.4">
            Aparecem na imagem
          </Text>
          {aoOcorrencia && (
            <Button
              size="compact-xs"
              variant="default"
              leftSection={<IconPlus size={12} />}
              onClick={() => aoOcorrencia({ tipo: 'acrescentar', pessoa: null })}
            >
              Acrescentar aparição
            </Button>
          )}
        </Group>
        {aparecem.map((p) => (
          <Stack key={p.id} gap={4}>
            <NomeDaPessoa
              pessoa={p}
              fw={600}
              aguardando={pendentes.has(chaveDoItem('pessoa', p.id))}
              aoCorrigir={aoCorrigir}
            />
            <FontesDoNome pessoa={p} aoCorrigir={aoCampo} />
            {aoOcorrencia && pessoaDoModelo(catalogo, p) && (
              <Button
                size="compact-xs"
                variant="subtle"
                w="fit-content"
                aria-label={`Acrescentar aparição de ${p.nome}`}
                onClick={() => aoOcorrencia({ tipo: 'acrescentar', pessoa: p })}
              >
                Acrescentar aparição
              </Button>
            )}
            <ScrollArea type="never">
              <Group gap={6} wrap="nowrap">
                {p.na_imagem.map((a, i) => (
                  <Box key={i}>
                    <UnstyledButton onClick={() => saltar(a.inicio_ms)}>
                      <video
                        src={quadro(a)}
                        muted
                        preload="metadata"
                        style={{
                          width: 92,
                          aspectRatio: '16 / 9',
                          objectFit: 'cover',
                          borderRadius: 4,
                          display: 'block',
                        }}
                      />
                      <Text size="10px" c="dimmed">
                        {`${tempo(a.inicio_ms)} · ${a.evidencia}`}
                      </Text>
                    </UnstyledButton>
                    {(a.papel || a.visual) && (
                      <Text size="10px" c="dimmed">
                        {[a.papel, a.visual].filter(Boolean).join(' · ')}
                      </Text>
                    )}
                    {aoCampo && pessoaDoModelo(catalogo, p) && ('papel' in a || 'visual' in a) && (
                      <ActionIcon
                        variant="subtle"
                        color="gray"
                        size="sm"
                        aria-label={`Corrigir papel na cena e visual de ${p.nome} ${tempo(a.inicio_ms)}`}
                        onClick={() => aoCampo({ modo: 'papel', pessoa: p, aparicao: a })}
                      >
                        <IconPencil size={14} />
                      </ActionIcon>
                    )}
                    {aoOcorrencia && pessoaDoModelo(catalogo, p) && (
                      <MenuDaOcorrencia
                        pessoa={p}
                        lista="na_imagem"
                        ocorrencia={a}
                        aoEscolher={aoOcorrencia}
                      />
                    )}
                  </Box>
                ))}
              </Group>
            </ScrollArea>
          </Stack>
        ))}
      </Stack>
      <Stack gap="xs">
        <Text size="xs" fw={700} tt="uppercase" c="orange.4">
          Só citadas (não contam como tempo de tela)
        </Text>
        {citadas.map((p) => (
          <Stack key={p.id} gap={4}>
            <NomeDaPessoa
              pessoa={p}
              aguardando={pendentes.has(chaveDoItem('pessoa', p.id))}
              aoCorrigir={aoCorrigir}
            />
            {p.na_imagem.length === 0 && <FontesDoNome pessoa={p} aoCorrigir={aoCampo} />}
            {aoOcorrencia && pessoaDoModelo(catalogo, p) && p.na_imagem.length === 0 && (
              <Button
                size="compact-xs"
                variant="subtle"
                w="fit-content"
                aria-label={`Acrescentar aparição de ${p.nome}`}
                onClick={() => aoOcorrencia({ tipo: 'acrescentar', pessoa: p })}
              >
                Acrescentar aparição
              </Button>
            )}
            <Group gap={6}>
              {p.citada_na_fala.map((m, i) => (
                <Group key={`fala-${i}`} gap={2} wrap="nowrap">
                  <Badge
                    component="button"
                    type="button"
                    variant="light"
                    color="orange"
                    style={{ cursor: 'pointer' }}
                    onClick={() => saltar(m.inicio_ms)}
                  >
                    {`fala ${tempo(m.inicio_ms)}`}
                  </Badge>
                  {aoOcorrencia && pessoaDoModelo(catalogo, p) && (
                    <MenuDaOcorrencia
                      pessoa={p}
                      lista="citada_na_fala"
                      ocorrencia={m}
                      aoEscolher={aoOcorrencia}
                    />
                  )}
                </Group>
              ))}
              {p.citada_no_texto.map((m, i) => (
                <Group key={`texto-${i}`} gap={2} wrap="nowrap">
                  <Tooltip label={m.texto}>
                    <Badge
                      component="button"
                      type="button"
                      variant="outline"
                      color="orange"
                      style={{ cursor: 'pointer' }}
                      onClick={() => saltar(m.inicio_ms)}
                    >
                      {`texto ${tempo(m.inicio_ms)}`}
                    </Badge>
                  </Tooltip>
                  {aoOcorrencia && pessoaDoModelo(catalogo, p) && (
                    <MenuDaOcorrencia
                      pessoa={p}
                      lista="citada_no_texto"
                      ocorrencia={m}
                      aoEscolher={aoOcorrencia}
                    />
                  )}
                </Group>
              ))}
            </Group>
          </Stack>
        ))}
      </Stack>
    </Stack>
  )
}

function BaixarJson({ nome, decupagem }: { nome: string; decupagem: Decupagem }) {
  function baixar() {
    const blob = new Blob([JSON.stringify(decupagem, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const ancora = document.createElement('a')
    ancora.href = url
    ancora.download = `${nome.replace(/\.mp4$/i, '')}.decupagem.json`
    ancora.click()
    // Revogar na hora pode cancelar o download em alguns navegadores.
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }
  return (
    <Tooltip label="Baixar decupagem (JSON)">
      <ActionIcon variant="default" aria-label="Baixar decupagem (JSON)" onClick={baixar}>
        <IconDownload />
      </ActionIcon>
    </Tooltip>
  )
}
