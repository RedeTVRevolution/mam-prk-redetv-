import { ActionIcon, Alert, Box, Button, Group, Paper, Slider, Stack, Text, Tooltip } from '@mantine/core'
import {
  IconAlertTriangle,
  IconDownload,
  IconMaximize,
  IconPlayerPause,
  IconPlayerPlay,
  IconVolume,
  IconVolumeOff,
} from '@tabler/icons-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { type ClienteDaApi, FalhaNaApi, SessaoExpirada } from './api.ts'
import { type Atalho, useAtalhos } from './atalhos.ts'
import { baixarDecupagem } from './baixar.ts'
import type { Job } from './jobs.ts'
import { Link } from './Link.tsx'
import { relogio } from './linhaDoTempo.ts'
import { ALTURA_DA_BARRA, CORES } from './tema.ts'
import { timecodeNoInstante } from './timecode.ts'
import { enderecoDaTelaAnterior, enderecoDoVideo } from './rotas.ts'
import type { Reproducao } from './Video.tsx'

const VELOCIDADES = [1, 2, 4]
const SALTO_CURTO_S = 1
const SALTO_LONGO_S = 5
const AVISO_DO_TC_MS = 1500

const ATALHOS_DO_PLAYER: Omit<Atalho, 'executar'>[] = [
  { tecla: 'Espaço ou K', acao: 'Tocar e pausar', grupo: 'Player' },
  { tecla: 'L', acao: 'Tocar; de novo, 2×; de novo, 4×', grupo: 'Player' },
  { tecla: 'J', acao: 'Recuar 5 s', grupo: 'Player' },
  { tecla: '← →', acao: 'Recuar e avançar 1 s', grupo: 'Player' },
  { tecla: 'Shift + ← →', acao: 'Recuar e avançar 5 s', grupo: 'Player' },
  { tecla: ', .', acao: 'Quadro anterior e seguinte, com o vídeo pausado', grupo: 'Player' },
  { tecla: 'F', acao: 'Tela cheia', grupo: 'Player' },
]

function dataBr(iso: string): string {
  const [a, m, d] = iso.split('-')
  return `${d}/${m}/${a}`
}

function tocar(player: HTMLVideoElement) {
  // O navegador recusa o play sem gesto ou com o arquivo ainda sem carregar: sem erro na tela.
  Promise.resolve(player.play()).catch(() => {})
}

/** O Visualizador: o vídeo com controles e atalhos próprios, o TC de origem e o endereço com o tempo. */
export default function Visualizador({
  api,
  job,
  t,
  podeEditar,
}: {
  api: ClienteDaApi
  job: Job
  t: number | null
  podeEditar: boolean
}) {
  const [reproducao, setReproducao] = useState<Reproducao | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [tentativas, setTentativas] = useState(0)
  const player = useRef<HTMLVideoElement>(null)
  const moldura = useRef<HTMLDivElement>(null)
  const retomarEm = useRef<number | null>(t)
  const [atualMs, setAtualMs] = useState(0)
  const [duracaoMs, setDuracaoMs] = useState((job.duracao_s ?? 0) * 1000)
  const [tocando, setTocando] = useState(false)
  const [velocidade, setVelocidade] = useState(1)
  const [volume, setVolume] = useState(1)
  const [mudo, setMudo] = useState(false)
  const [copiado, setCopiado] = useState(false)
  const [falhaDoJson, setFalhaDoJson] = useState(false)

  useEffect(() => {
    let ativo = true
    api.job(job.id).reproducao().then(
      (r) => {
        if (ativo) {
          setErro(null)
          setReproducao(r)
        }
      },
      (e: unknown) => {
        if (!ativo || e instanceof SessaoExpirada) return
        setErro(e instanceof FalhaNaApi ? `http_${e.status}` : 'api_inacessivel')
      },
    )
    return () => {
      ativo = false
    }
  }, [api, job.id, tentativas])

  // Outro `?t=` no mesmo vídeo salta o player.
  const tAnterior = useRef(t)
  useEffect(() => {
    if (t === tAnterior.current) return
    tAnterior.current = t
    if (t === null) return
    if (player.current && player.current.readyState > 0) player.current.currentTime = t
    else retomarEm.current = t
  }, [t])

  /** O endereço copiado da barra é sempre o do momento atual, sem entrada nova no histórico. */
  function gravarNoEndereco() {
    if (!player.current) return
    history.replaceState(history.state, '', enderecoDoVideo(job.id, player.current.currentTime))
  }

  function saltarPara(segundos: number) {
    const el = player.current
    if (!el) return
    const limite = Number.isFinite(el.duration) ? el.duration : Infinity
    el.currentTime = Math.min(Math.max(segundos, 0), limite)
    setAtualMs(el.currentTime * 1000)
  }

  function mudarVelocidade(v: number) {
    if (player.current) player.current.playbackRate = v
    setVelocidade(v)
  }

  const fps = job.taxa_de_quadros ?? null
  const alternar = useCallback(() => {
    const el = player.current
    if (!el) return
    if (el.paused) tocar(el)
    else el.pause()
  }, [])
  const tocarMaisRapido = () => {
    const el = player.current
    if (!el) return
    if (el.paused) {
      tocar(el)
      return
    }
    const seguinte = VELOCIDADES.find((v) => v > el.playbackRate) ?? VELOCIDADES[VELOCIDADES.length - 1]
    mudarVelocidade(seguinte)
  }
  const telaCheia = () => {
    if (document.fullscreenElement) void document.exitFullscreen()
    else void moldura.current?.requestFullscreen?.()
  }
  const tecla = (e: KeyboardEvent, ...teclas: string[]) => teclas.includes(e.key.toLowerCase())

  useAtalhos(
    ATALHOS_DO_PLAYER.map((a): Atalho => {
      switch (a.tecla) {
        case 'Espaço ou K':
          return { ...a, casa: (e) => tecla(e, ' ', 'k'), executar: alternar }
        case 'L':
          return { ...a, casa: (e) => tecla(e, 'l'), executar: tocarMaisRapido }
        case 'J':
          return {
            ...a,
            casa: (e) => tecla(e, 'j'),
            executar: () => saltarPara((player.current?.currentTime ?? 0) - SALTO_LONGO_S),
          }
        case '← →':
        case 'Shift + ← →': {
          const comShift = a.tecla.startsWith('Shift')
          return {
            ...a,
            casa: (e) => (e.key === 'ArrowLeft' || e.key === 'ArrowRight') && e.shiftKey === comShift,
            executar: (e) => {
              const passo = comShift ? SALTO_LONGO_S : SALTO_CURTO_S
              saltarPara((player.current?.currentTime ?? 0) + (e.key === 'ArrowLeft' ? -passo : passo))
            },
          }
        }
        case ', .':
          return {
            ...a,
            casa: (e) => e.key === ',' || e.key === '.',
            executar: (e) => {
              const el = player.current
              if (!el || !el.paused || !fps) return
              saltarPara(el.currentTime + (e.key === ',' ? -1 : 1) / fps)
              gravarNoEndereco()
            },
          }
        default:
          return { ...a, casa: (e) => tecla(e, 'f'), executar: telaCheia }
      }
    }),
  )

  const tc = useMemo(
    () =>
      job.timecode_origem && fps
        ? timecodeNoInstante(job.timecode_origem, fps, atualMs)
        : null,
    [job.timecode_origem, fps, atualMs],
  )

  async function copiarTc() {
    if (!tc) return
    try {
      await navigator.clipboard.writeText(tc)
    } catch {
      return
    }
    setCopiado(true)
    setTimeout(() => setCopiado(false), AVISO_DO_TC_MS)
  }

  async function baixar() {
    setFalhaDoJson(false)
    try {
      baixarDecupagem(job.nome, await api.job(job.id).decupagem())
    } catch (e) {
      if (!(e instanceof SessaoExpirada)) setFalhaDoJson(true)
    }
  }

  const titulo = [job.programa, job.data_exibicao ? dataBr(job.data_exibicao) : null].filter(Boolean)

  return (
    <Group
      gap="sm"
      align="stretch"
      wrap="nowrap"
      h={`calc(100vh - ${ALTURA_DA_BARRA}px - 2 * var(--mantine-spacing-sm))`}
      style={{ overflow: 'hidden' }}
    >
      <Stack gap="xs" style={{ flex: '0 0 62%', minWidth: 0, minHeight: 0 }}>
        <Group justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
            {titulo.length > 0 && <Text fw={700}>{titulo.join(' · ')}</Text>}
            <Text size="sm" c="dimmed" truncate>
              {titulo.length > 0 ? `· ${job.nome}` : job.nome}
            </Text>
          </Group>
          <Group gap="xs" wrap="nowrap">
            {podeEditar && (
              <Link para={enderecoDaTelaAnterior(job.id)} size="sm">
                Tela anterior
              </Link>
            )}
            <Tooltip label="Baixar decupagem (JSON)">
              <ActionIcon variant="default" aria-label="Baixar decupagem (JSON)" onClick={() => void baixar()}>
                <IconDownload />
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>
        {falhaDoJson && (
          <Alert color={CORES.falhou} variant="light" icon={<IconAlertTriangle />} role="alert">
            Não foi possível baixar a decupagem. Tente de novo em instantes.
          </Alert>
        )}
        {erro ? (
          <Alert color={CORES.falhou} variant="light" icon={<IconAlertTriangle />} role="alert">
            <Stack gap="xs" align="flex-start">
              <Text size="sm">Não foi possível carregar o vídeo. Tente de novo em instantes.</Text>
              <Text size="xs" c="dimmed">
                Código para o suporte: {erro}
              </Text>
              <Button size="xs" variant="default" onClick={() => setTentativas((n) => n + 1)}>
                Tentar de novo
              </Button>
            </Stack>
          </Alert>
        ) : (
          <Box
            ref={moldura}
            style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
            bg="dark.7"
          >
            <video
              ref={player}
              src={reproducao?.url}
              aria-label="Player"
              onClick={alternar}
              onError={() => setTentativas((n) => n + 1)}
              onLoadedMetadata={(e) => {
                const el = e.currentTarget
                if (Number.isFinite(el.duration)) setDuracaoMs(el.duration * 1000)
                if (retomarEm.current !== null) {
                  el.currentTime = retomarEm.current
                  setAtualMs(el.currentTime * 1000)
                  retomarEm.current = null
                }
              }}
              onTimeUpdate={(e) => setAtualMs(e.currentTarget.currentTime * 1000)}
              onPlay={() => setTocando(true)}
              onPause={() => {
                setTocando(false)
                gravarNoEndereco()
              }}
              onSeeked={gravarNoEndereco}
              onRateChange={(e) => setVelocidade(e.currentTarget.playbackRate)}
              style={{ flex: 1, minHeight: 0, width: '100%', objectFit: 'contain', background: 'var(--mantine-color-black)' }}
            />
            <Paper withBorder p="xs">
              <Group gap="sm" wrap="nowrap">
                <Tooltip label={tocando ? 'Pausar (Espaço)' : 'Tocar (Espaço)'}>
                  <ActionIcon
                    variant="default"
                    aria-label={tocando ? 'Pausar' : 'Tocar'}
                    onClick={alternar}
                  >
                    {tocando ? <IconPlayerPause /> : <IconPlayerPlay />}
                  </ActionIcon>
                </Tooltip>
                <Button.Group aria-label="Velocidade">
                  {VELOCIDADES.map((v) => (
                    <Button
                      key={v}
                      size="compact-sm"
                      variant={velocidade === v ? 'filled' : 'default'}
                      aria-pressed={velocidade === v}
                      onClick={() => mudarVelocidade(v)}
                    >
                      {`${v}×`}
                    </Button>
                  ))}
                </Button.Group>
                <Text ff="monospace" style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {`${relogio(atualMs)} / ${relogio(duracaoMs)}`}
                </Text>
                {tc && (
                  <Tooltip label="Copiar o timecode">
                    <Text
                      component="button"
                      type="button"
                      ff="monospace"
                      size="sm"
                      c="dimmed"
                      aria-label={`Copiar o timecode ${tc}`}
                      onClick={() => void copiarTc()}
                      style={{ background: 'none', border: 0, cursor: 'pointer', fontVariantNumeric: 'tabular-nums' }}
                    >
                      {`TC ${tc}`}
                    </Text>
                  </Tooltip>
                )}
                <Text size="xs" c="dimmed" role="status">
                  {copiado ? 'Timecode copiado' : ''}
                </Text>
                <Box style={{ flex: 1 }} />
                <Tooltip label={mudo ? 'Ligar o som' : 'Silenciar'}>
                  <ActionIcon
                    variant="default"
                    aria-label={mudo ? 'Ligar o som' : 'Silenciar'}
                    onClick={() => {
                      if (player.current) player.current.muted = !mudo
                      setMudo(!mudo)
                    }}
                  >
                    {mudo ? <IconVolumeOff /> : <IconVolume />}
                  </ActionIcon>
                </Tooltip>
                <Slider
                  w={90}
                  min={0}
                  max={1}
                  step={0.05}
                  size="xs"
                  value={volume}
                  label={null}
                  aria-label="Volume"
                  onChange={(v) => {
                    if (player.current) player.current.volume = v
                    setVolume(v)
                  }}
                />
                <Tooltip label="Tela cheia (F)">
                  <ActionIcon variant="default" aria-label="Tela cheia" onClick={telaCheia}>
                    <IconMaximize />
                  </ActionIcon>
                </Tooltip>
              </Group>
            </Paper>
          </Box>
        )}
      </Stack>
      <Paper
        withBorder
        p="sm"
        aria-label="Painel"
        style={{ flex: '1 1 0', minWidth: 380, overflowY: 'auto' }}
      />
    </Group>
  )
}
