import { baixarDecupagem } from './baixar.ts'
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
  useMemo,
  useReducer,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
  type RefObject,
} from 'react'
import {
  type ClienteDaApi,
  type ClienteDoJob,
  ConflitoNaApi,
  PedidoInvalido,
  SessaoExpirada,
} from './api.ts'
import {
  comoSelect,
  ContextoDoCatalogo,
  pessoaDoModelo,
  rotuloDe,
  useCatalogo,
  type CatalogoDeCorrecoes,
} from './catalogo.ts'
import {
  faixasComArrasto,
  faixasDe,
  LINHA_LIVRE,
  lerTempo,
  limitesDasAlcas,
  maiorFim,
  percentualDoTempo,
  reduzirLinha,
  secoesDaFaixa,
  selecaoValida,
  teclaDaAlca,
  tempo,
  tempoDoCampo,
  tempoDoPonteiro,
  tempoPreciso,
  type Borda,
  type Faixa,
  type Intervalo,
  type ListaDePessoa,
  type LimitesDaAlca,
  type Ocorrencia,
  type Selecao,
} from './linhaDoTempo.ts'
import { CORES, CORES_DE_OBJETO } from './tema.ts'

export interface JobAberto {
  id: string
  nome: string
  estado: string
  codigo_falha: string | null
}

type Aparicao = Intervalo & {
  evidencia: string
  papel?: string | null
  visual?: string | null
  /** O JPEG do meio da aparição, relativo à pasta do Job (`quadros/aparicao-0-1.jpg`). */
  quadro?: string | null
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
  /** O JPEG do meio do plano. */
  quadro?: string | null
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

export type CorBase = keyof typeof CORES_DE_OBJETO

export type CategoriaDeObjeto = 'roupa' | 'calcado' | 'acessorio' | 'na_mao' | 'em_cena' | 'veiculo' | 'outro'
export type RelacaoDoObjeto = 'veste' | 'calca' | 'usa' | 'segura'

/** 1.3: roupa, calçado, acessório ou objeto em cena, com a cor e o dono. */
export interface Objeto {
  id: string
  categoria: CategoriaDeObjeto
  tipo: string
  cor_base: CorBase[]
  /** O tom em palavras ("vermelho vivo"). */
  cor?: string | null
  detalhe?: string | null
  marca?: string | null
  /** O id de uma pessoa da mesma decupagem; `null` para objeto em cena. */
  pessoa?: string | null
  relacao?: RelacaoDoObjeto | null
  /** O JPEG da primeira ocorrência. */
  quadro?: string | null
  ocorrencias: Intervalo[]
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
  /** 1.3; falta nas decupagens anteriores. */
  objetos?: Objeto[]
}

export interface Reproducao {
  url: string
  expira_em: string
}

const LARGURA_DO_ROTULO = 120

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
  limites,
  duracaoMs,
  trilha,
  alcas,
}: {
  borda: Borda
  ms: number
  limites: LimitesDaAlca
  duracaoMs: number
  trilha: RefObject<HTMLDivElement | null>
  alcas: AlcasDaLinha
}) {
  const arrastando = useRef(false)
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
      aria-valuemin={limites.minMs}
      aria-valuemax={limites.maxMs}
      aria-valuenow={ms}
      aria-valuetext={tempo(ms)}
      pos="absolute"
      top={-3}
      w={8}
      h={20}
      bg="white"
      style={{
        left: `${percentualDoTempo(ms, duracaoMs)}%`,
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
        if (!arrastando.current || !caixa) return
        const novo = tempoDoPonteiro(
          e.clientX,
          { esquerda: caixa.left, largura: caixa.width },
          duracaoMs,
          limites,
        )
        if (novo !== null) alcas.aoMover(borda, novo)
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
        const novo = teclaDaAlca(e.key, e.shiftKey, ms, limites)
        if (novo === null) return
        e.preventDefault()
        alcas.aoMover(borda, novo)
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
  const limites =
    alcas && selecionada ? limitesDasAlcas(selecionada, duracaoMs, alcas.limiteMs) : null
  const secoes = secoesDaFaixa(faixa.ocorrencias, duracaoMs).map((secao) => {
    const o = secao.ocorrencia
    if (!o) return <Progress.Section key={secao.chave} value={secao.percentual} color="transparent" />
    return (
      <Progress.Section
        key={o.chave}
        value={secao.percentual}
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
      />
    )
  })
  return (
    <Group gap="sm" wrap="nowrap">
      <Text size="xs" w={LARGURA_DO_ROTULO} ta="right" c="dimmed">
        {faixa.nome}
      </Text>
      <Box ref={trilha} pos="relative" flex={1}>
        <Progress.Root size={14} radius="xs" bg="dark.6">
          {secoes}
        </Progress.Root>
        {alcas && selecionada && limites && (
          <>
            <AlcaDoTempo
              borda="inicio"
              ms={selecionada.inicio_ms}
              limites={limites.inicio}
              duracaoMs={duracaoMs}
              trilha={trilha}
              alcas={alcas}
            />
            <AlcaDoTempo
              borda="fim"
              ms={selecionada.fim_ms}
              limites={limites.fim}
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
  api: apiDaApp,
  job,
  podeEditar = false,
  podeAprovar = false,
  inicioEmS = null,
}: {
  api: ClienteDaApi
  job: JobAberto
  podeEditar?: boolean
  podeAprovar?: boolean
  /** Instante inicial, em segundos (o `?t=` do endereço). */
  inicioEmS?: number | null
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
  const api = useMemo(() => apiDaApp.job(job.id), [apiDaApp, job.id])

  useEffect(() => {
    if (!concluido) return
    let ativo = true
    Promise.all([api.reproducao(), api.decupagem(), api.catalogo()]).then(
      ([reproducao, decupagem, catalogo]) => {
        if (ativo) setCarga({ tipo: 'pronta', reproducao, decupagem, catalogo })
      },
      (erro: unknown) => {
        if (!ativo) return
        if (!(erro instanceof SessaoExpirada)) setCarga({ tipo: 'erro' })
      },
    )
    return () => {
      ativo = false
    }
  }, [api, concluido])

  // A fila de revisão só existe para quem edita; falhar aqui não derruba a tela.
  useEffect(() => {
    if (!concluido || !podeEditar) return
    let ativo = true
    api.fila().then(
      (itens) => {
        if (ativo) setFila(itens)
      },
      () => {},
    )
    return () => {
      ativo = false
    }
  }, [api, concluido, podeEditar, recargaDaFila])

  // As pendentes saem da decupagem entregue: o selo vem do histórico, que é recarregado a
  // cada nova decupagem (toda correção, aprovação ou recusa recarrega o painel).
  const decupagemAtual = carga.tipo === 'pronta' ? carga.decupagem : null
  useEffect(() => {
    if (!podeEditar || !decupagemAtual) return
    let ativo = true
    api.historico().then(
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
      () => {},
    )
    return () => {
      ativo = false
    }
  }, [api, podeEditar, decupagemAtual])

  // Depois de uma correção, só o painel recarrega: o player segue no mesmo link e ponto.
  const recarregarDecupagem = useCallback(() => {
    api.decupagem().then(
      (decupagem) => setCarga((c) => (c.tipo === 'pronta' ? { ...c, decupagem } : c)),
      (erro: unknown) => {
        if (!(erro instanceof SessaoExpirada)) setCarga({ tipo: 'erro' })
      },
    )
  }, [api])

  const retomarEm = useRef<number | null>(inicioEmS ?? null)
  // O link assinado expira em minutos: se o player falhar depois disso, pede outro e
  // continua do mesmo ponto.
  const renovarLink = useCallback(() => {
    if (carga.tipo !== 'pronta') return
    if (Date.parse(carga.reproducao.expira_em) > Date.now()) return
    const instante = player.current?.currentTime ?? 0
    api.reproducao().then(
      (reproducao) => {
        retomarEm.current = instante
        setCarga((atual) => (atual.tipo === 'pronta' ? { ...atual, reproducao } : atual))
      },
      (erro: unknown) => {
        if (!(erro instanceof SessaoExpirada)) setCarga({ tipo: 'erro' })
      },
    )
  }, [api, carga])
  const retomar = useCallback(() => {
    if (player.current && retomarEm.current !== null) {
      player.current.currentTime = retomarEm.current
      retomarEm.current = null
    }
  }, [])

  const saltar = useCallback((inicioMs: number) => {
    if (player.current) player.current.currentTime = inicioMs / 1000
  }, [])

  // O mesmo vídeo com outro `?t=` (o endereço mudou, a tela não remontou): salta para lá.
  const inicioAnterior = useRef(inicioEmS)
  useEffect(() => {
    if (inicioEmS === inicioAnterior.current) return
    inicioAnterior.current = inicioEmS
    if (inicioEmS === null) return
    if (player.current && player.current.readyState > 0) player.current.currentTime = inicioEmS
    else retomarEm.current = inicioEmS
  }, [inicioEmS])

  const [atualMs, setAtualMs] = useState(0)
  const [duracaoDoPlayerMs, setDuracaoDoPlayerMs] = useState<number | null>(null)
  const [aba, setAba] = useState<Aba>('Pessoas')
  // Alças da linha do tempo: a seleção, o intervalo arrastado e o modal de confirmação.
  const [linha, despachar] = useReducer(reduzirLinha, LINHA_LIVRE)
  const { arrastado, confirmando: confirmandoTempos } = linha

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
  // O modal aberto segue com a seleção antiga, para mostrar o antes e depois que enviou.
  const selecaoAtual = selecaoValida(linha, decupagem)
  const faixas = faixasComArrasto(faixasDe(decupagem, catalogo), selecaoAtual, arrastado)
  const alcas: AlcasDaLinha | undefined = podeEditar
    ? {
        selecionada: selecaoAtual?.chave ?? null,
        limiteMs: decupagem.video?.duracao_ms ?? Infinity,
        aoSelecionar: (ocorrencia) => despachar({ tipo: 'selecionar', decupagem, ocorrencia }),
        aoMover: (borda, ms) => {
          if (!selecaoAtual) return
          despachar({ tipo: 'mover', decupagem, borda, ms })
          saltar(ms)
        },
        aoSoltar: () => despachar({ tipo: 'soltar', decupagem }),
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
            api={api}
            aoFechar={() => setFilaAberta(false)}
            aoResolver={() => {
              setRecargaDaFila((n) => n + 1)
              recarregarDecupagem()
            }}
          />
        )}
        {podeEditar && (
          <HistoricoDeCorrecoes
            aberto={historicoAberto}
            api={api}
            aoFechar={() => setHistoricoAberto(false)}
            podeAprovar={podeAprovar}
            aoMudar={recarregarDecupagem}
          />
        )}
        <CorrigirPessoa
          key={corrigindo?.id ?? 'fechado'}
          pessoa={corrigindo}
          versao={decupagem.versao_decupagem ?? ''}
          api={api}
          aoFechar={() => setCorrigindo(null)}
          aoSalvar={() => {
            setCorrigindo(null)
            recarregarDecupagem()
          }}
          aoVersaoDesatualizada={recarregarDecupagem}
        />
        <CorrigirOcorrencia
          key={ocorrenciaAberta ? JSON.stringify(ocorrenciaAberta) : 'fechada'}
          acao={ocorrenciaAberta}
          pessoas={decupagem.pessoas.filter((p) => pessoaDoModelo(catalogo, p))}
          versao={decupagem.versao_decupagem ?? ''}
          api={api}
          aoFechar={() => setOcorrenciaAberta(null)}
          aoSalvar={() => {
            setOcorrenciaAberta(null)
            recarregarDecupagem()
          }}
          aoVersaoDesatualizada={recarregarDecupagem}
        />
        <CorrigirPauta
          key={corrigindoPauta?.id ?? 'fechada'}
          pauta={corrigindoPauta}
          versao={decupagem.versao_decupagem ?? ''}
          api={api}
          aoFechar={() => setCorrigindoPauta(null)}
          aoSalvar={() => {
            setCorrigindoPauta(null)
            recarregarDecupagem()
          }}
          aoVersaoDesatualizada={recarregarDecupagem}
        />
        <CorrigirTempos
          key={confirmandoTempos ? 'tempos-aberto' : 'tempos-fechado'}
          selecao={confirmandoTempos ? linha.selecao : null}
          depois={arrastado}
          versao={decupagem.versao_decupagem ?? ''}
          api={api}
          aoFechar={() => despachar({ tipo: 'cancelar' })}
          aoSalvar={() => {
            despachar({ tipo: 'enviado' })
            recarregarDecupagem()
          }}
          aoVersaoDesatualizada={recarregarDecupagem}
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
          api={api}
          aoFechar={() => setTrechoAberto(null)}
          aoSalvar={() => {
            setTrechoAberto(null)
            recarregarDecupagem()
          }}
          aoVersaoDesatualizada={recarregarDecupagem}
        />
        <CorrigirCampo
          key={campoAberto ? JSON.stringify(campoAberto) : 'fechado'}
          campo={campoAberto}
          versao={decupagem.versao_decupagem ?? ''}
          api={api}
          aoFechar={() => setCampoAberto(null)}
          aoSalvar={() => {
            setCampoAberto(null)
            recarregarDecupagem()
          }}
          aoVersaoDesatualizada={recarregarDecupagem}
        />
        <CorrigirComercial
          key={comercialAberto === 'novo' ? 'novo' : (comercialAberto?.id ?? 'fechado')}
          comercial={comercialAberto}
          versao={decupagem.versao_decupagem ?? ''}
          api={api}
          aoFechar={() => setComercialAberto(null)}
          aoSalvar={() => {
            setComercialAberto(null)
            recarregarDecupagem()
          }}
          aoVersaoDesatualizada={recarregarDecupagem}
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

/** O que todo modal de Correção recebe da tela do vídeo. */
interface PropsDaCorrecao {
  versao: string
  api: ClienteDoJob
  aoFechar: () => void
  aoSalvar: () => void
  aoVersaoDesatualizada: () => void
}

const DECUPAGEM_MUDOU = 'A decupagem mudou e foi recarregada. Confira e salve de novo.'

/**
 * Casca comum dos modais de Correção: os campos do modal, o motivo, o erro e Cancelar/Salvar.
 * `enviar` grava com o motivo; os erros do cliente viram as mensagens da tela.
 */
function FormularioDeCorrecao({
  titulo,
  aberto,
  podeSalvar,
  conflito = DECUPAGEM_MUDOU,
  invalido,
  enviar,
  aoFechar,
  aoSalvar,
  aoVersaoDesatualizada,
  children,
}: {
  titulo: string
  aberto: boolean
  /** Os campos do modal permitem salvar; o motivo o formulário confere. */
  podeSalvar: boolean
  /** Mensagem do 409, depois de recarregar a decupagem. */
  conflito?: string
  /** Mensagem do 422; sem ela, vale a mensagem genérica. */
  invalido?: string
  enviar: (motivo: string) => Promise<void>
  aoFechar: () => void
  aoSalvar: () => void
  aoVersaoDesatualizada: () => void
  children: ReactNode
}) {
  const catalogo = useCatalogo()
  const [motivo, setMotivo] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [salvando, setSalvando] = useState(false)

  async function salvar() {
    setSalvando(true)
    setErro(null)
    try {
      await enviar(motivo)
      aoSalvar()
    } catch (e) {
      if (e instanceof ConflitoNaApi) {
        // Recarrega o painel: a versão nova chega ao modal e o Editor pode salvar de novo.
        aoVersaoDesatualizada()
        setErro(conflito)
      } else if (e instanceof PedidoInvalido && invalido) {
        setErro(invalido)
      } else if (!(e instanceof SessaoExpirada)) {
        // Na sessão expirada o cliente já avisou o App.
        setErro('Não foi possível salvar a correção.')
      }
      setSalvando(false)
    }
  }

  return (
    <Modal opened={aberto} onClose={aoFechar} title={titulo} centered>
      <Stack gap="sm">
        {children}
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
            disabled={!podeSalvar || !motivo.trim()}
            onClick={() => void salvar()}
          >
            Salvar
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

/** Modal da Ilha de edição: novo nome e motivo; a API confere a permissão e a versão. */
function CorrigirPessoa({
  pessoa,
  versao,
  api,
  ...props
}: PropsDaCorrecao & { pessoa: Pessoa | null }) {
  const catalogo = useCatalogo()
  const [nome, setNome] = useState(pessoa?.nome ?? '')

  async function enviar(motivo: string) {
    if (!pessoa) return
    await api.corrigir({
      tipo: 'pessoa.renomear',
      item_id: pessoa.id,
      valor: nome,
      motivo,
      versao,
    })
  }

  return (
    <FormularioDeCorrecao
      {...props}
      titulo="Corrigir pessoa"
      aberto={pessoa !== null}
      podeSalvar={!!nome.trim()}
      enviar={enviar}
    >
      <TextInput
        label="Nome"
        value={nome}
        maxLength={catalogo.limites.nome}
        onChange={(e) => setNome(e.currentTarget.value)}
      />
    </FormularioDeCorrecao>
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
  api,
  ...props
}: PropsDaCorrecao & { acao: AcaoDeOcorrencia | null; pessoas: Pessoa[] }) {
  const catalogo = useCatalogo()
  const [destino, setDestino] = useState<string>('citada_na_fala')
  const [evidencia, setEvidencia] = useState('')
  const [pessoaId, setPessoaId] = useState(
    acao?.tipo === 'acrescentar' ? (acao.pessoa?.id ?? NOVA_PESSOA) : '',
  )
  const [nome, setNome] = useState('')
  const [inicio, setInicio] = useState(acao && acao.tipo === 'tempos' ? tempo(acao.inicio_ms) : '')
  const [fim, setFim] = useState(acao && acao.tipo === 'tempos' ? tempo(acao.fim_ms) : '')

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

  async function enviar(motivo: string) {
    if (!corpo) return
    await api.corrigir({ ...corpo, motivo, versao })
  }

  return (
    <FormularioDeCorrecao
      {...props}
      titulo={acao ? TITULOS[acao.tipo] : ''}
      aberto={acao !== null}
      podeSalvar={corpo !== null}
      invalido={
        acao?.tipo === 'acrescentar' || acao?.tipo === 'tempos'
          ? 'Confira os campos: os tempos ficam dentro da duração do vídeo.'
          : 'A ocorrência não foi encontrada. Recarregue a página e confira.'
      }
      enviar={enviar}
    >
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
    </FormularioDeCorrecao>
  )
}

/** Modal das alças: mostra antes e depois e pede o motivo; salvar grava um `item.tempos`. */
function CorrigirTempos({
  selecao,
  depois,
  versao,
  api,
  ...props
}: PropsDaCorrecao & { selecao: Selecao | null; depois: Intervalo | null }) {
  async function enviar(motivo: string) {
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
    await api.corrigir(corpo)
  }

  return (
    <FormularioDeCorrecao
      {...props}
      titulo="Corrigir tempos"
      aberto={selecao !== null && depois !== null}
      podeSalvar
      conflito="A decupagem mudou e foi recarregada. Cancele e arraste de novo."
      invalido="Confira os tempos: ficam dentro da duração do vídeo e a ocorrência precisa existir."
      enviar={enviar}
    >
      {selecao && depois && (
        <>
          <Text size="sm">{`Antes: ${tempoPreciso(selecao.original.inicio_ms)}–${tempoPreciso(selecao.original.fim_ms)}`}</Text>
          <Text size="sm" fw={700}>
            {`Depois: ${tempoPreciso(depois.inicio_ms)}–${tempoPreciso(depois.fim_ms)}`}
          </Text>
        </>
      )}
    </FormularioDeCorrecao>
  )
}

/** Modal da pauta: título, resumo, início e fim (mm:ss) e motivo. Cada campo mudado vira uma correção. */
function CorrigirPauta({
  pauta,
  versao,
  api,
  aoFechar,
  aoSalvar,
  aoVersaoDesatualizada,
}: PropsDaCorrecao & { pauta: Pauta | null }) {
  const catalogo = useCatalogo()
  const [titulo, setTitulo] = useState(pauta?.titulo ?? '')
  const [resumo, setResumo] = useState(pauta?.resumo ?? '')
  const [inicio, setInicio] = useState(pauta ? tempo(pauta.inicio_ms) : '')
  const [fim, setFim] = useState(pauta ? tempo(pauta.fim_ms) : '')
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

  async function enviar(motivo: string) {
    if (!pauta) return
    const feitas = { ...gravadas }
    try {
      for (const m of mudancas) {
        await api.corrigir({ ...m, item_id: pauta.id, motivo, versao })
        feitas[m.tipo] = m.valor
      }
    } catch (e) {
      setGravadas(feitas)
      throw e
    }
  }

  // Fechar depois de gravar parte dos campos recarrega a decupagem, como o salvar.
  function fechar() {
    if (Object.keys(gravadas).length > 0) aoSalvar()
    else aoFechar()
  }

  return (
    <FormularioDeCorrecao
      titulo="Corrigir pauta"
      aberto={pauta !== null}
      podeSalvar={
        !!titulo.trim() && !(temposMudaram && !temposValidos) && !resumoApagado && mudancas.length > 0
      }
      invalido="Confira os campos: os tempos ficam dentro da duração do vídeo."
      enviar={enviar}
      aoFechar={fechar}
      aoSalvar={aoSalvar}
      aoVersaoDesatualizada={aoVersaoDesatualizada}
    >
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
    </FormularioDeCorrecao>
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
  api,
  ...props
}: PropsDaCorrecao & { campo: CampoAberto | null }) {
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

  async function enviar(motivo: string) {
    if (!corpo) return
    await api.corrigir({ ...corpo, motivo, versao })
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
    <FormularioDeCorrecao
      {...props}
      titulo={campo ? TITULOS_DO_CAMPO[campo.modo] : ''}
      aberto={campo !== null}
      podeSalvar={corpo !== null}
      invalido="Confira os campos: o valor não foi aceito."
      enviar={enviar}
    >
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
    </FormularioDeCorrecao>
  )
}

/** Modal do plano (descrição e plano limpo) ou da fala (texto e locutor): os tempos não mudam. */
function CorrigirTrecho({
  trecho,
  versao,
  api,
  aoFechar,
  aoSalvar,
  aoVersaoDesatualizada,
}: PropsDaCorrecao & { trecho: Trecho | null }) {
  const catalogo = useCatalogo()
  const plano = trecho?.tipo === 'plano' ? trecho.plano : null
  const fala = trecho?.tipo === 'fala' ? trecho.fala : null
  const [ambiente, setAmbiente] = useState(plano?.ambiente ?? '')
  const [acao, setAcao] = useState(plano?.acao ?? '')
  const [objetos, setObjetos] = useState((plano?.objetos ?? []).join(', '))
  const [limpo, setLimpo] = useState(plano?.plano_limpo ?? false)
  const [texto, setTexto] = useState(fala?.texto ?? '')
  const [locutor, setLocutor] = useState(fala?.locutor ?? '')
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

  async function enviar(motivo: string) {
    const feitas = { ...gravadas }
    try {
      for (const m of mudancas) {
        await api.corrigir({ ...m, item_id: itemId, motivo, versao })
        feitas[m.tipo] = m.valor
      }
    } catch (e) {
      setGravadas(feitas)
      throw e
    }
  }

  // Fechar depois de gravar parte dos campos recarrega a decupagem, como o salvar.
  function fechar() {
    if (Object.keys(gravadas).length > 0) aoSalvar()
    else aoFechar()
  }

  return (
    <FormularioDeCorrecao
      titulo={plano ? 'Corrigir plano' : 'Corrigir fala'}
      aberto={trecho !== null}
      podeSalvar={
        !(plano !== null && !ambiente.trim()) &&
        !(fala !== null && (!texto.trim() || !locutor.trim())) &&
        mudancas.length > 0
      }
      invalido="Confira os campos: o trecho não foi encontrado ou há valor inválido."
      enviar={enviar}
      aoFechar={fechar}
      aoSalvar={aoSalvar}
      aoVersaoDesatualizada={aoVersaoDesatualizada}
    >
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
    </FormularioDeCorrecao>
  )
}

/** Modal do comercial: corrige marca, tipo e tempos de um comercial ou acrescenta um novo (`'novo'`). */
function CorrigirComercial({
  comercial,
  versao,
  api,
  aoFechar,
  aoSalvar,
  aoVersaoDesatualizada,
}: PropsDaCorrecao & { comercial: Comercial | 'novo' | null }) {
  const catalogo = useCatalogo()
  const novo = comercial === 'novo'
  const atual = comercial !== null && !novo ? comercial : null
  const [marca, setMarca] = useState(atual?.marca ?? '')
  const [tipo, setTipo] = useState<string | null>(atual?.tipo ?? null)
  const [inicio, setInicio] = useState(atual ? tempo(atual.inicio_ms) : '')
  const [fim, setFim] = useState(atual ? tempo(atual.fim_ms) : '')
  const [evidencias, setEvidencias] = useState<string[]>([])
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

  async function enviar(motivo: string) {
    const feitas = { ...gravadas }
    try {
      for (const m of mudancas) {
        await api.corrigir({ ...m, item_id: atual?.id ?? '', motivo, versao })
        feitas[m.tipo] = m.valor
      }
    } catch (e) {
      setGravadas(feitas)
      throw e
    }
  }

  // Fechar depois de gravar parte dos campos recarrega a decupagem, como o salvar.
  function fechar() {
    if (Object.keys(gravadas).length > 0) aoSalvar()
    else aoFechar()
  }

  return (
    <FormularioDeCorrecao
      titulo={novo ? 'Acrescentar comercial' : 'Corrigir comercial'}
      aberto={comercial !== null}
      podeSalvar={!!marca.trim() && !(temposMudaram && !temposValidos) && mudancas.length > 0}
      invalido="Confira os campos: os tempos ficam dentro da duração do vídeo."
      enviar={enviar}
      aoFechar={fechar}
      aoSalvar={aoSalvar}
      aoVersaoDesatualizada={aoVersaoDesatualizada}
    >
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
    </FormularioDeCorrecao>
  )
}

export interface ItemDoHistorico {
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
  api,
  aoFechar,
  podeAprovar,
  aoMudar,
}: {
  aberto: boolean
  api: ClienteDoJob
  aoFechar: () => void
  podeAprovar: boolean
  aoMudar: () => void
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

  useEffect(() => {
    if (!aberto) return
    let ativo = true
    api.historico().then(
      (lista) => {
        if (!ativo) return
        setItens(lista)
        setFalhou(false)
      },
      (e: unknown) => {
        if (!ativo) return
        if (!(e instanceof SessaoExpirada)) setFalhou(true)
      },
    )
    return () => {
      ativo = false
    }
  }, [aberto, api, recarga])

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
      await (acao === 'desfazer' ? api.desfazer(item.id, motivo) : api.recusar(item.id, motivo))
      fecharModal()
      carregar()
      aoMudar()
    } catch (e) {
      if (e instanceof SessaoExpirada) {
        // O cliente já avisou o App.
      } else if (e instanceof ConflitoNaApi) {
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
      await api.aprovar(item.id)
    } catch (e) {
      if (e instanceof SessaoExpirada) {
        // O cliente já avisou o App.
      } else if (e instanceof ConflitoNaApi)
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

export interface ItemDaFila {
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
  api,
  aoFechar,
  aoResolver,
}: {
  aberta: boolean
  itens: ItemDaFila[]
  api: ClienteDoJob
  aoFechar: () => void
  aoResolver: () => void
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
            api={api}
            aoResolver={(mensagem) => {
              setAviso(mensagem ?? null)
              aoResolver()
            }}
          />
        ))}
      </Stack>
    </Drawer>
  )
}

function ItemDaFilaDeRevisao({
  item,
  api,
  aoResolver,
}: {
  item: ItemDaFila
  api: ClienteDoJob
  /** `aviso`, se houver, sobrevive à recarga da fila. */
  aoResolver: (aviso?: string) => void
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
      await (acao === 'reaplicar'
        ? api.reaplicar(item.id, candidato, motivo)
        : api.descartar(item.id, motivo))
      aoResolver()
    } catch (e) {
      if (e instanceof SessaoExpirada) {
        // O cliente já avisou o App.
      } else if (e instanceof ConflitoNaApi) {
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
    baixarDecupagem(nome, decupagem)
  }
  return (
    <Tooltip label="Baixar decupagem (JSON)">
      <ActionIcon variant="default" aria-label="Baixar decupagem (JSON)" onClick={baixar}>
        <IconDownload />
      </ActionIcon>
    </Tooltip>
  )
}
