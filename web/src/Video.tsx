import {
  ActionIcon,
  Alert,
  AspectRatio,
  Badge,
  Box,
  Center,
  Drawer,
  Grid,
  Group,
  Button,
  Loader,
  Modal,
  NavLink,
  Paper,
  Progress,
  ScrollArea,
  SegmentedControl,
  Slider,
  Stack,
  Text,
  TextInput,
  Textarea,
  Tooltip,
  UnstyledButton,
  type MantineColor,
} from '@mantine/core'
import { IconDownload, IconHistory, IconPencil } from '@tabler/icons-react'
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { chamarApi, SessaoExpirada } from './api.ts'
import type { Autenticador } from './auth/autenticador.ts'
import { CORES_DE_OCORRENCIA } from './tema.ts'

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

interface Pessoa {
  id: string
  nome: string
  origem?: 'modelo' | 'revisao'
  na_imagem: (Intervalo & { evidencia: string })[]
  citada_na_fala: Intervalo[]
  citada_no_texto: (Intervalo & { texto: string })[]
}

export interface Decupagem {
  versao_decupagem?: string
  pautas: (Intervalo & { titulo: string })[]
  pessoas: Pessoa[]
  planos: (Intervalo & { id: string; ambiente: string; acao?: string | null })[]
  comerciais: (Intervalo & { marca: string; tipo: string })[]
  transcricao: (Intervalo & { locutor: string; texto: string })[]
}

interface Reproducao {
  url: string
  expira_em: string
}

interface Ocorrencia extends Intervalo {
  chave: string
}

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

function faixasDe(d: Decupagem): Faixa[] {
  const de = <T extends Intervalo>(prefixo: string, lista: T[]): Ocorrencia[] =>
    lista.map((x, i) => ({ chave: `${prefixo}-${i}`, inicio_ms: x.inicio_ms, fim_ms: x.fim_ms }))
  return [
    { nome: 'Pautas', cor: CORES_DE_OCORRENCIA.pautas, ocorrencias: de('pauta', d.pautas) },
    {
      nome: 'Aparições',
      cor: CORES_DE_OCORRENCIA.aparicoes,
      ocorrencias: de('img', d.pessoas.flatMap((p) => p.na_imagem)),
    },
    {
      nome: 'Menções',
      cor: CORES_DE_OCORRENCIA.mencoes,
      ocorrencias: de(
        'mencao',
        d.pessoas.flatMap((p) => [...p.citada_na_fala, ...p.citada_no_texto]),
      ),
    },
    { nome: 'Comerciais', cor: CORES_DE_OCORRENCIA.comerciais, ocorrencias: de('com', d.comerciais) },
    { nome: 'Planos', cor: CORES_DE_OCORRENCIA.planos, ocorrencias: de('plano', d.planos) },
    { nome: 'Fala', cor: CORES_DE_OCORRENCIA.fala, ocorrencias: de('fala', d.transcricao) },
  ]
}

function maiorFim(faixas: Faixa[]): number {
  return Math.max(0, ...faixas.flatMap((f) => f.ocorrencias.map((o) => o.fim_ms)))
}

/** Uma faixa da linha do tempo: ocorrências na cor da faixa e vãos transparentes. */
function FaixaDoTempo({
  faixa,
  duracaoMs,
  saltar,
}: {
  faixa: Faixa
  duracaoMs: number
  saltar: (ms: number) => void
}) {
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
        style={{ cursor: 'pointer' }}
        onClick={() => saltar(o.inicio_ms)}
        onKeyDown={(e: KeyboardEvent<HTMLDivElement>) => {
          if (e.key !== 'Enter' && e.key !== ' ') return
          e.preventDefault()
          saltar(o.inicio_ms)
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
      <Progress.Root size={14} radius="xs" bg="dark.6" flex={1}>
        {secoes}
      </Progress.Root>
    </Group>
  )
}

const ABAS = ['Pessoas', 'Pautas', 'Marcas', 'Planos', 'Fala'] as const
type Aba = (typeof ABAS)[number]

const dentro = (atualMs: number, i: Intervalo) => atualMs >= i.inicio_ms && atualMs < i.fim_ms

type Carga =
  | { tipo: 'carregando' }
  | { tipo: 'erro' }
  | { tipo: 'pronta'; reproducao: Reproducao; decupagem: Decupagem }

export default function Video({
  autenticador,
  job,
  aoSessaoExpirada,
  podeEditar = false,
}: {
  autenticador: Autenticador
  job: JobAberto
  aoSessaoExpirada: () => void
  podeEditar?: boolean
}) {
  const player = useRef<HTMLVideoElement>(null)
  const [carga, setCarga] = useState<Carga>({ tipo: 'carregando' })
  const concluido = job.estado === 'concluido'
  const [corrigindo, setCorrigindo] = useState<Pessoa | null>(null)
  const [historicoAberto, setHistoricoAberto] = useState(false)
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
    ]).then(
      ([reproducao, decupagem]) => {
        if (ativo) setCarga({ tipo: 'pronta', reproducao, decupagem })
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
        <Loader color="red" role="status" aria-label="Carregando o vídeo" />
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

  const { decupagem, reproducao } = carga
  const faixas = faixasDe(decupagem)
  const duracaoMs = Math.max(duracaoDoPlayerMs ?? maiorFim(faixas), 1)
  const quadro = (i: Intervalo) => `${reproducao.url}#t=${i.inicio_ms / 1000 + 1}`

  return (
    <Grid gap="sm">
      <Grid.Col span={{ base: 12, lg: 8 }}>
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={700}>{job.nome}</Text>
            <Text ff="monospace" size="xl" c="red.5">
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
                  color="red"
                  label={tempo}
                />
              </Group>
              {faixas.map((faixa) => (
                <FaixaDoTempo key={faixa.nome} faixa={faixa} duracaoMs={duracaoMs} saltar={saltar} />
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
                  aoCorrigir={podeEditar ? setCorrigindo : undefined}
                />
              )}
              {aba === 'Pautas' &&
                decupagem.pautas.map((p, i) => (
                  <NavLink
                    key={`pauta-${i}`}
                    label={p.titulo}
                    description={`${tempo(p.inicio_ms)}–${tempo(p.fim_ms)}`}
                    active={dentro(atualMs, p)}
                    onClick={() => saltar(p.inicio_ms)}
                  />
                ))}
              {aba === 'Marcas' &&
                decupagem.comerciais.map((c, i) => (
                  <NavLink
                    key={`com-${i}`}
                    label={c.marca}
                    description={`${c.tipo} · ${tempo(c.inicio_ms)}`}
                    onClick={() => saltar(c.inicio_ms)}
                  />
                ))}
              {aba === 'Planos' &&
                decupagem.planos.map((p) => (
                  <NavLink
                    key={p.id}
                    label={p.acao ?? p.ambiente}
                    description={`${p.ambiente} · ${tempo(p.inicio_ms)}`}
                    onClick={() => saltar(p.inicio_ms)}
                  />
                ))}
              {aba === 'Fala' &&
                decupagem.transcricao.map((f, i) => (
                  <UnstyledButton key={`fala-${i}`} w="100%" onClick={() => saltar(f.inicio_ms)}>
                    <Paper p={6} bg={dentro(atualMs, f) ? 'red.9' : 'transparent'}>
                      <Text size="xs" ff="monospace" c="dimmed">
                        {`${tempo(f.inicio_ms)} ${f.locutor.toUpperCase()}`}
                      </Text>
                      <Text size="sm">{f.texto}</Text>
                    </Paper>
                  </UnstyledButton>
                ))}
            </ScrollArea>
          </Stack>
        </Paper>
      </Grid.Col>
      {podeEditar && (
        <HistoricoDeCorrecoes
          aberto={historicoAberto}
          autenticador={autenticador}
          jobId={job.id}
          aoFechar={() => setHistoricoAberto(false)}
          aoDesfazer={recarregarDecupagem}
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
    </Grid>
  )
}

/** Nome da pessoa, com o selo de revisão e, para quem edita, o botão de corrigir. */
function NomeDaPessoa({
  pessoa,
  fw,
  aoCorrigir,
}: {
  pessoa: Pessoa
  fw?: number
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
          maxLength={200}
          onChange={(e) => setNome(e.currentTarget.value)}
        />
        <Textarea
          label="Motivo"
          value={motivo}
          maxLength={500}
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
            color="red"
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

interface ItemDoHistorico {
  id: string
  tipo: 'pessoa.renomear' | 'desfazer'
  autor_email: string
  criada_em: string
  motivo: string
  antes: string
  depois: string
  estado: 'ativa' | 'desfeita'
}

const TIPOS_DE_CORRECAO: Record<ItemDoHistorico['tipo'], string> = {
  'pessoa.renomear': 'Renomear pessoa',
  desfazer: 'Desfazer',
}

const quando = (iso: string) =>
  new Date(iso).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' })

/** Gaveta com as correções da mais recente à mais antiga; desfazer acrescenta, nada se apaga. */
function HistoricoDeCorrecoes({
  aberto,
  autenticador,
  jobId,
  aoFechar,
  aoDesfazer,
  aoSessaoExpirada,
}: {
  aberto: boolean
  autenticador: Autenticador
  jobId: string
  aoFechar: () => void
  aoDesfazer: () => void
  aoSessaoExpirada: () => void
}) {
  const [itens, setItens] = useState<ItemDoHistorico[] | null>(null)
  const [falhou, setFalhou] = useState(false)
  const [desfazendo, setDesfazendo] = useState<ItemDoHistorico | null>(null)
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
    setDesfazendo(null)
    setMotivo('')
    setErro(null)
  }

  async function confirmar() {
    if (!desfazendo) return
    setEnviando(true)
    setErro(null)
    try {
      await chamarApi(autenticador, `/v1/jobs/${jobId}/correcoes/${desfazendo.id}/desfazer`, {
        metodo: 'POST',
        corpo: { motivo },
      })
      fecharModal()
      carregar()
      aoDesfazer()
    } catch (e) {
      if (e instanceof SessaoExpirada) aoSessaoExpirada()
      else if (e instanceof Error && e.message.startsWith('Falha 409')) {
        // Outro Editor pode ter desfeito antes: a decupagem também mudou.
        setErro('Essa correção já foi desfeita ou não casa com a versão atual. O histórico foi recarregado.')
        carregar()
        aoDesfazer()
      } else setErro('Não foi possível desfazer a correção.')
    }
    setEnviando(false)
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
          {itens?.length === 0 && <Text size="sm">Nenhuma correção ainda.</Text>}
          {itens?.map((i) => (
            <Paper key={i.id} withBorder p="sm">
              <Stack gap={4}>
                <Group justify="space-between">
                  <Text size="xs" fw={700}>
                    {TIPOS_DE_CORRECAO[i.tipo]}
                  </Text>
                  {i.estado === 'desfeita' && (
                    <Badge size="xs" color="gray" variant="light">
                      desfeita
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
                  <Text size="sm">{i.antes}</Text>
                </Group>
                <Group gap={4} wrap="nowrap">
                  <Text size="xs" c="dimmed">
                    Depois:
                  </Text>
                  <Text size="sm" fw={600}>
                    {i.depois}
                  </Text>
                </Group>
                <Text size="sm">{i.motivo}</Text>
                {i.estado === 'ativa' && i.tipo !== 'desfazer' && (
                  <Group justify="flex-end">
                    <Button size="xs" variant="default" onClick={() => setDesfazendo(i)}>
                      Desfazer
                    </Button>
                  </Group>
                )}
              </Stack>
            </Paper>
          ))}
        </Stack>
      </Drawer>
      <Modal opened={desfazendo !== null} onClose={fecharModal} title="Desfazer correção" centered>
        <Stack gap="sm">
          <Textarea
            label="Motivo"
            value={motivo}
            maxLength={500}
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
              color="red"
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

/** Separa quem aparece de quem só é citado (menção não é aparição). */
function AbaPessoas({
  decupagem,
  quadro,
  saltar,
  aoCorrigir,
}: {
  decupagem: Decupagem
  quadro: (i: Intervalo) => string
  saltar: (ms: number) => void
  aoCorrigir?: (p: Pessoa) => void
}) {
  const aparecem = decupagem.pessoas.filter((p) => p.na_imagem.length > 0)
  const citadas = decupagem.pessoas.filter(
    (p) => p.citada_na_fala.length > 0 || p.citada_no_texto.length > 0,
  )
  return (
    <Stack gap="md">
      <Stack gap="xs">
        <Text size="xs" fw={700} tt="uppercase" c="blue.4">
          Aparecem na imagem
        </Text>
        {aparecem.map((p) => (
          <Stack key={p.id} gap={4}>
            <NomeDaPessoa pessoa={p} fw={600} aoCorrigir={aoCorrigir} />
            <ScrollArea type="never">
              <Group gap={6} wrap="nowrap">
                {p.na_imagem.map((a, i) => (
                  <UnstyledButton key={i} onClick={() => saltar(a.inicio_ms)}>
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
            <NomeDaPessoa pessoa={p} aoCorrigir={aoCorrigir} />
            <Group gap={6}>
              {p.citada_na_fala.map((m, i) => (
                <Badge
                  key={`fala-${i}`}
                  component="button"
                  type="button"
                  variant="light"
                  color="orange"
                  style={{ cursor: 'pointer' }}
                  onClick={() => saltar(m.inicio_ms)}
                >
                  {`fala ${tempo(m.inicio_ms)}`}
                </Badge>
              ))}
              {p.citada_no_texto.map((m, i) => (
                <Tooltip key={`texto-${i}`} label={m.texto}>
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
