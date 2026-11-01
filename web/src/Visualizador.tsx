import { ActionIcon, Box, Button, Group, Paper, Slider, Stack, Text, Tooltip } from '@mantine/core'
import {
  IconDownload,
  IconMaximize,
  IconPlayerPause,
  IconPlayerPlay,
  IconVolume,
  IconVolumeOff,
} from '@tabler/icons-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import { type ClienteDaApi, codigoDoErro, SessaoExpirada } from './api.ts'
import { useAtalhos } from './atalhos.ts'
import { baixarDecupagem } from './baixar.ts'
import { dataDeExibicao, type Job } from './jobs.ts'
import { FaixasDoVideo } from './FaixasDoVideo.tsx'
import { Link } from './Link.tsx'
import { Painel } from './Painel.tsx'
import { criarCacheDeQuadros } from './quadros.ts'
import { type Aba, abaDaChave } from './painel.ts'
import { duracaoDaLinha, faixasDoVisualizador, relogio } from './linhaDoTempo.ts'
import { ALTURA_DA_BARRA } from './tema.ts'
import { timecodeNoInstante } from './timecode.ts'
import { enderecoDaTelaAnterior, enderecoDoVideo } from './rotas.ts'
import type { Decupagem, Reproducao } from './Video.tsx'

const VELOCIDADES = [1, 2, 4]
const SALTO_CURTO_S = 1
const SALTO_LONGO_S = 5
const AVISO_DO_TC_MS = 1500

const GRUPO = 'Player'
const GRUPO_DA_LINHA = 'Linha do tempo'

/** O evento é de uma destas teclas (letras sem diferença de caixa). */
function tecla(e: KeyboardEvent, ...teclas: string[]): boolean {
  return teclas.includes(e.key.toLowerCase())
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
  const [falhaDoJson, setFalhaDoJson] = useState<string | null>(null)
  const [decupagem, setDecupagem] = useState<Decupagem | null>(null)
  const [falhaDaDecupagem, setFalhaDaDecupagem] = useState<string | null>(null)
  const [cargasDaDecupagem, setCargasDaDecupagem] = useState(0)
  const [selecionada, setSelecionada] = useState<string | null>(null)
  const [aba, setAba] = useState<Aba>('agora')
  const [pessoasAbertas, setPessoasAbertas] = useState<ReadonlySet<string>>(new Set())
  // "Reproduzir trecho": onde o player para sozinho.
  const pararEm = useRef<number | null>(null)
  const avisoDoTc = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(avisoDoTc.current), [])

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
        setErro(codigoDoErro(e))
      },
    )
    return () => {
      ativo = false
    }
  }, [api, job.id, tentativas])

  const concluido = job.estado === 'concluido'
  useEffect(() => {
    if (!concluido) return
    let ativo = true
    api.job(job.id).decupagem().then(
      (d) => {
        if (!ativo) return
        setFalhaDaDecupagem(null)
        setDecupagem(d)
      },
      (e: unknown) => {
        if (ativo && !(e instanceof SessaoExpirada)) setFalhaDaDecupagem(codigoDoErro(e))
      },
    )
    return () => {
      ativo = false
    }
  }, [api, job.id, concluido, cargasDaDecupagem])

  // As URLs assinadas dos quadros valem alguns minutos: o cache evita pedir de novo a cada linha.
  const urlDoQuadro = useMemo(() => criarCacheDeQuadros((arquivo) => api.job(job.id).quadro(arquivo)), [api, job.id])

  const faixas = useMemo(() => (decupagem ? faixasDoVisualizador(decupagem) : null), [decupagem])
  const duracaoDaLinhaMs = duracaoDaLinha(duracaoMs, faixas ?? [])

  // Outro `?t=` no mesmo vídeo salta o player.
  const tAnterior = useRef(t)
  useEffect(() => {
    if (t === tAnterior.current) return
    tAnterior.current = t
    if (t === null) return
    pararEm.current = null
    if (player.current && player.current.readyState > 0) player.current.currentTime = t
    else retomarEm.current = t
  }, [t])

  /** O endereço copiado da barra é sempre o do momento atual, sem entrada nova no histórico. */
  function gravarNoEndereco() {
    if (!player.current) return
    const busca = new URLSearchParams(location.search).get('busca')
    history.replaceState(history.state, '', enderecoDoVideo(job.id, Math.floor(player.current.currentTime), busca))
  }

  function saltarPara(segundos: number) {
    const el = player.current
    if (!el) return
    pararEm.current = null
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
    pararEm.current = null
    if (el.paused) tocar(el)
    else el.pause()
  }, [])
  const tocarMaisRapido = () => {
    const el = player.current
    if (!el) return
    // Pausado, o L recomeça o ciclo: toca em 1×.
    if (el.paused) {
      mudarVelocidade(1)
      tocar(el)
      return
    }
    const seguinte = VELOCIDADES.find((v) => v > el.playbackRate) ?? VELOCIDADES[VELOCIDADES.length - 1]
    mudarVelocidade(seguinte)
  }
  function reproduzirTrecho(trecho: { inicio_ms: number; fim_ms: number }) {
    const el = player.current
    if (!el) return
    saltarPara(trecho.inicio_ms / 1000)
    pararEm.current = trecho.fim_ms
    tocar(el)
  }
  function aoAtualizarOTempo(el: HTMLVideoElement) {
    setAtualMs(el.currentTime * 1000)
    // O `timeupdate` chega a cada ~250 ms: o player volta ao fim exato do trecho.
    if (pararEm.current !== null && el.currentTime * 1000 >= pararEm.current) {
      el.pause()
      el.currentTime = pararEm.current / 1000
      setAtualMs(pararEm.current)
      pararEm.current = null
    }
  }
  const telaCheia = () => {
    if (document.fullscreenElement) void document.exitFullscreen()
    else void moldura.current?.requestFullscreen?.()
  }

  const recuarOuAvancar = (passo: number) => ({
    casa: (e: KeyboardEvent) =>
      (e.key === 'ArrowLeft' || e.key === 'ArrowRight') && e.shiftKey === (passo === SALTO_LONGO_S),
    executar: (e: KeyboardEvent) =>
      saltarPara((player.current?.currentTime ?? 0) + (e.key === 'ArrowLeft' ? -passo : passo)),
  })

  useAtalhos([
    {
      tecla: 'Espaço ou K',
      acao: 'Tocar e pausar',
      grupo: GRUPO,
      casa: (e) => tecla(e, ' ', 'k'),
      executar: alternar,
    },
    {
      tecla: 'L',
      acao: 'Tocar; de novo, 2×; de novo, 4×',
      grupo: GRUPO,
      casa: (e) => tecla(e, 'l'),
      executar: tocarMaisRapido,
    },
    {
      tecla: 'J',
      acao: 'Recuar 5 s',
      grupo: GRUPO,
      casa: (e) => tecla(e, 'j'),
      executar: () => saltarPara((player.current?.currentTime ?? 0) - SALTO_LONGO_S),
    },
    { tecla: '← →', acao: 'Recuar e avançar 1 s', grupo: GRUPO, ...recuarOuAvancar(SALTO_CURTO_S) },
    { tecla: 'Shift + ← →', acao: 'Recuar e avançar 5 s', grupo: GRUPO, ...recuarOuAvancar(SALTO_LONGO_S) },
    {
      tecla: ', .',
      acao: 'Quadro anterior e seguinte, com o vídeo pausado',
      grupo: GRUPO,
      casa: (e) => e.key === ',' || e.key === '.',
      // O `seeked` do player grava o novo instante no endereço.
      executar: (e) => {
        const el = player.current
        if (!el || !el.paused || !fps) return
        saltarPara(el.currentTime + (e.key === ',' ? -1 : 1) / fps)
      },
    },
    { tecla: 'F', acao: 'Tela cheia', grupo: GRUPO, casa: (e) => tecla(e, 'f'), executar: telaCheia },
    {
      tecla: '← →',
      acao: 'Numa faixa: passar de ocorrência (o player não anda)',
      grupo: GRUPO_DA_LINHA,
    },
    { tecla: 'Enter', acao: 'Numa faixa: saltar à ocorrência', grupo: GRUPO_DA_LINHA },
  ])

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
    clearTimeout(avisoDoTc.current)
    avisoDoTc.current = setTimeout(() => setCopiado(false), AVISO_DO_TC_MS)
  }

  async function baixar() {
    setFalhaDoJson(null)
    try {
      baixarDecupagem(job.nome, await api.job(job.id).decupagem())
    } catch (e) {
      if (!(e instanceof SessaoExpirada)) setFalhaDoJson(codigoDoErro(e))
    }
  }

  // O link assinado expira em minutos: se o player falhar depois disso, pede outro e continua
  // do mesmo ponto. Com o link ainda válido, a falha é do arquivo, e pedir de novo não adianta.
  function aoFalharOPlayer() {
    if (!reproducao) return
    retomarEm.current = player.current?.currentTime ?? null
    if (Date.parse(reproducao.expira_em) > Date.now()) setErro(`midia_${player.current?.error?.code ?? 0}`)
    else setTentativas((n) => n + 1)
  }

  const titulo = [job.programa, job.data_exibicao ? dataDeExibicao(job.data_exibicao) : null].filter(Boolean)

  return (
    <Stack
      gap="xs"
      h={`calc(100vh - ${ALTURA_DA_BARRA}px - 2 * var(--mantine-spacing-sm))`}
      style={{ overflow: 'hidden' }}
    >
      <Group justify="space-between" wrap="nowrap">
        <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
          {titulo.length > 0 && <Text fw={700}>{titulo.join(' · ')}</Text>}
          <Text size="sm" c="dimmed" truncate>
            {titulo.length > 0 ? `· ${job.nome}` : job.nome}
          </Text>
        </Group>
        <Group gap="xs" wrap="nowrap">
          {podeEditar && (
            <Link para={enderecoDaTelaAnterior(job.id, Math.floor(atualMs / 1000))} size="sm">
              Tela anterior
            </Link>
          )}
          {job.estado === 'concluido' && (
            <Tooltip label="Baixar decupagem (JSON)">
              <ActionIcon variant="default" aria-label="Baixar decupagem (JSON)" onClick={() => void baixar()}>
                <IconDownload />
              </ActionIcon>
            </Tooltip>
          )}
        </Group>
      </Group>
      {falhaDoJson && (
        <AlertaDeErro
          mensagem="Não foi possível baixar a decupagem. Tente de novo em instantes."
          codigo={falhaDoJson}
          aoTentar={() => void baixar()}
        />
      )}
      <Group gap="sm" align="stretch" wrap="nowrap" style={{ flex: 1, minHeight: 0 }}>
        <Stack gap="xs" style={{ flex: '1 1 0', minWidth: 0, minHeight: 0 }}>
          {erro ? (
            <AlertaDeErro
              mensagem="Não foi possível carregar o vídeo. Tente de novo em instantes."
              codigo={erro}
              aoTentar={() => {
                setErro(null)
                setTentativas((n) => n + 1)
              }}
            />
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
                onError={aoFalharOPlayer}
                onLoadedMetadata={(e) => {
                  const el = e.currentTarget
                  if (Number.isFinite(el.duration)) setDuracaoMs(el.duration * 1000)
                  if (retomarEm.current !== null) {
                    el.currentTime = retomarEm.current
                    setAtualMs(el.currentTime * 1000)
                    retomarEm.current = null
                  }
                }}
                onTimeUpdate={(e) => aoAtualizarOTempo(e.currentTarget)}
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
                  <Text style={{ fontVariantNumeric: 'tabular-nums' }}>
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
          {falhaDaDecupagem && (
            <AlertaDeErro
              mensagem="Não foi possível carregar a linha do tempo. Tente de novo em instantes."
              codigo={falhaDaDecupagem}
              aoTentar={() => {
                setFalhaDaDecupagem(null)
                setCargasDaDecupagem((n) => n + 1)
              }}
            />
          )}
          {faixas && (
            <FaixasDoVideo
              faixas={faixas}
              cortesMs={job.cortes_ms}
              duracaoMs={duracaoDaLinhaMs}
              atualMs={atualMs}
              selecionada={selecionada}
              aoSaltar={(ms) => saltarPara(ms / 1000)}
              aoSelecionar={(chave, inicioMs) => {
                setSelecionada(chave)
                const aberta = abaDaChave(chave)
                if (aberta) setAba(aberta)
                saltarPara(inicioMs / 1000)
              }}
            />
          )}
        </Stack>
        <Paper
          withBorder
          p="sm"
          aria-label="Painel"
          style={{ flex: '0 0 38%', minWidth: 380, minHeight: 0, display: 'flex', flexDirection: 'column' }}
        >
          {decupagem ? (
            <Painel
              decupagem={decupagem}
              duracaoMs={duracaoDaLinhaMs}
              atualMs={atualMs}
              aba={aba}
              aoTrocarAba={setAba}
              selecionada={selecionada}
              pessoasAbertas={pessoasAbertas}
              aoAbrirPessoa={(id) =>
                setPessoasAbertas((abertas) => {
                  const novas = new Set(abertas)
                  if (!novas.delete(id)) novas.add(id)
                  return novas
                })
              }
              aoSelecionar={setSelecionada}
              aoSaltar={(ms) => saltarPara(ms / 1000)}
              aoReproduzir={reproduzirTrecho}
              urlDoQuadro={urlDoQuadro}
            />
          ) : (
            <Text size="sm" c="dimmed">
              {concluido ? 'Carregando a decupagem…' : 'O painel aparece quando a decupagem estiver pronta.'}
            </Text>
          )}
        </Paper>
      </Group>
    </Stack>
  )
}
