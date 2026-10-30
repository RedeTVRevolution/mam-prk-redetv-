import {
  ActionIcon,
  Alert,
  AspectRatio,
  Badge,
  Center,
  Grid,
  Group,
  Loader,
  NavLink,
  Paper,
  Progress,
  ScrollArea,
  SegmentedControl,
  Slider,
  Stack,
  Text,
  Tooltip,
  UnstyledButton,
  type MantineColor,
} from '@mantine/core'
import { IconDownload } from '@tabler/icons-react'
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
  na_imagem: (Intervalo & { evidencia: string })[]
  citada_na_fala: Intervalo[]
  citada_no_texto: (Intervalo & { texto: string })[]
}

export interface Decupagem {
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
  let cursor = 0
  for (const o of ordenadas) {
    const inicio = Math.max(o.inicio_ms, cursor)
    const largura = Math.max(o.fim_ms - o.inicio_ms, LARGURA_MINIMA_MS)
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
        value={(largura / duracaoMs) * 100}
        color={faixa.cor}
        role="button"
        tabIndex={0}
        aria-label={`${faixa.nome} ${tempo(o.inicio_ms)}`}
        style={{ cursor: 'pointer' }}
        onClick={() => saltar(o.inicio_ms)}
        onKeyDown={(e: KeyboardEvent<HTMLDivElement>) => {
          if (e.key === 'Enter' || e.key === ' ') saltar(o.inicio_ms)
        }}
      />,
    )
    cursor = inicio + largura
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
}: {
  autenticador: Autenticador
  job: JobAberto
  aoSessaoExpirada: () => void
}) {
  const player = useRef<HTMLVideoElement>(null)
  const [carga, setCarga] = useState<Carga>({ tipo: 'carregando' })
  const concluido = job.estado === 'concluido'
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
                setDuracaoDoPlayerMs(e.currentTarget.duration * 1000)
              }}
              onTimeUpdate={(e) => setAtualMs(e.currentTarget.currentTime * 1000)}
              aria-label="Player"
              style={{ background: '#000' }}
            />
          </AspectRatio>
          <Paper p="sm" withBorder>
            <Stack gap={6}>
              <Group gap="sm" wrap="nowrap">
                <div style={{ width: LARGURA_DO_ROTULO, flexShrink: 0 }} />
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
              <BaixarJson nome={job.nome} decupagem={decupagem} />
            </Group>
            <ScrollArea flex={1}>
              {aba === 'Pessoas' && (
                <AbaPessoas decupagem={decupagem} quadro={quadro} saltar={saltar} />
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
    </Grid>
  )
}

/** Separa quem aparece de quem só é citado (menção não é aparição). */
function AbaPessoas({
  decupagem,
  quadro,
  saltar,
}: {
  decupagem: Decupagem
  quadro: (i: Intervalo) => string
  saltar: (ms: number) => void
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
            <Text size="sm" fw={600}>
              {p.nome}
            </Text>
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
            <Text size="sm">{p.nome}</Text>
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
