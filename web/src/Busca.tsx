import { Box, Button, Group, Loader, Paper, Select, Stack, Text } from '@mantine/core'
import { IconCheck } from '@tabler/icons-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import { codigoDoErro, FalhaNaApi, SessaoExpirada, type ClienteDaApi } from './api.ts'
import { useAtalhos } from './atalhos.ts'
import {
  EVIDENCIAS,
  contagemDeMencoes,
  contagemDeMomentos,
  contagemDeVideos,
  trechosDoMotivo,
  type ConsultaDaBusca,
  type Evidencia,
  type Momento,
  type ResultadoDaBusca,
  type VideoDoResultado,
} from './busca.ts'
import { dataDeExibicao } from './jobs.ts'
import { relogio } from './linhaDoTempo.ts'
import { Quadro } from './Miniatura.tsx'
import { enderecoDaBusca, enderecoDoVideo, navegar, seguir } from './rotas.ts'
import { CORES, CORES_DE_OCORRENCIA } from './tema.ts'

const VIDEOS_POR_VEZ = 20
const TETO_DE_VIDEOS = 50
const TODOS = 'todos'
const ENTENDIDO = 'entendido'
const ANOS_NO_SELECT = 26
const ANO_ATUAL = new Date().getFullYear()
const NUMEROS = { fontVariantNumeric: 'tabular-nums' } as const
// Momento selecionado pelo teclado: o azul de foco a 16% (0x29).
const SELECIONADO = { background: `${CORES.foco}29` }
// Acima disso (os GCs de regulamento), o motivo vem em 2 linhas, com "ver mais".
const MOTIVO_LONGO = 120
const ANOS: string[] = Array.from({ length: ANOS_NO_SELECT }, (_, i) => String(ANO_ATUAL - i))

type Carga =
  | { tipo: 'carregando' }
  | { tipo: 'pronta'; resultado: ResultadoDaBusca }
  | { tipo: 'erro'; mensagem: string; codigo: string }

function mensagemDoErro(erro: unknown): string {
  if (erro instanceof FalhaNaApi && erro.status === 429) return 'Muitas buscas seguidas. Espere alguns segundos.'
  if (erro instanceof FalhaNaApi && erro.status === 504) {
    return 'A busca demorou demais. Tente uma consulta mais específica.'
  }
  return 'Não foi possível buscar agora. Tente de novo.'
}

/** "01/03/2020 a 31/12/2024", "Desde 01/03/2020", "Até 31/12/2024". */
function rotuloDoPeriodo(desde: string | null, ate: string | null): string {
  if (desde && ate) return `${dataDeExibicao(desde)} a ${dataDeExibicao(ate)}`
  return desde ? `Desde ${dataDeExibicao(desde)}` : `Até ${dataDeExibicao(ate)}`
}

/** O motivo com os trechos destacados, montado pelas posições: o texto nunca vira HTML. */
function Motivo({ momento, encurtado }: { momento: Momento; encurtado: boolean }) {
  return (
    <Text size="sm" component="span" lineClamp={encurtado ? 2 : undefined}>
      {trechosDoMotivo(momento.motivo, momento.destaques).map((t, i) =>
        t.destacado ? (
          <mark
            key={i}
            style={{
              background: CORES.elevada,
              color: CORES.texto,
              fontWeight: 700,
              textDecoration: `underline ${CORES.foco} 2px`,
              textUnderlineOffset: 2,
            }}
          >
            {t.texto}
          </mark>
        ) : (
          <span key={i}>{t.texto}</span>
        ),
      )}
    </Text>
  )
}

function Chip({ rotulo, tipo, ligado, desabilitado, aoAlternar }: {
  rotulo: string
  tipo: keyof typeof CORES_DE_OCORRENCIA
  ligado: boolean
  desabilitado: boolean
  aoAlternar: () => void
}) {
  const cor = CORES_DE_OCORRENCIA[tipo].cor
  return (
    <Button
      type="button"
      size="compact-sm"
      variant="default"
      aria-pressed={ligado}
      disabled={desabilitado}
      leftSection={ligado ? <IconCheck size={14} aria-hidden /> : undefined}
      onClick={aoAlternar}
      styles={{ root: ligado ? { borderColor: cor, color: cor } : {} }}
    >
      {rotulo}
    </Button>
  )
}

/** Uma barra fina com a posição de cada momento no vídeo. */
function PosicaoDosMomentos({ video }: { video: VideoDoResultado }) {
  const total = (video.duracao_s ?? 0) * 1000
  if (total <= 0) return null
  return (
    <Box
      role="img"
      aria-label="Posição dos momentos no vídeo"
      pos="relative"
      h={8}
      bg="dark.5"
      style={{ borderRadius: 'var(--mantine-radius-xs)' }}
    >
      {video.momentos.map((m, i) => (
        <Box
          key={i}
          pos="absolute"
          top={0}
          h={8}
          bg={CORES.foco}
          style={{
            left: `${Math.min(100, (m.inicio_ms / total) * 100)}%`,
            width: `max(2px, ${Math.min(100, ((m.fim_ms - m.inicio_ms) / total) * 100)}%)`,
          }}
        />
      ))}
    </Box>
  )
}

function Linha({ video, momento, selecionado, busca }: {
  video: VideoDoResultado
  momento: Momento
  selecionado: boolean
  busca: string
}) {
  const endereco = enderecoDoVideo(video.job_id, momento.inicio_ms / 1000, busca)
  const [aberto, setAberto] = useState(false)
  const longo = momento.motivo.length > MOTIVO_LONGO
  return (
    <Group gap={0} wrap="nowrap">
      <a
        href={endereco}
        onClick={(e) => seguir(e, endereco)}
        aria-current={selecionado ? 'true' : undefined}
        data-momento={`${video.job_id}:${momento.inicio_ms}`}
        style={{
          display: 'flex',
          flex: 1,
          minWidth: 0,
          gap: 'var(--mantine-spacing-sm)',
          alignItems: 'center',
          padding: 'var(--mantine-spacing-xs)',
          color: 'inherit',
          textDecoration: 'none',
          ...(selecionado ? SELECIONADO : {}),
        }}
      >
        <Quadro url={momento.quadro_url} largura={96} altura={54} />
        <Text size="sm" c={CORES.textoSecundario} style={{ ...NUMEROS, flex: 'none' }}>
          {relogio(momento.inicio_ms)}–{relogio(momento.fim_ms)}
        </Text>
        <Motivo momento={momento} encurtado={longo && !aberto} />
      </a>
      {/* Fora do link: abrir o texto não abre o vídeo. */}
      {longo && (
        <Button variant="subtle" size="compact-xs" aria-expanded={aberto} onClick={() => setAberto(!aberto)}>
          {aberto ? 'ver menos' : 'ver mais'}
        </Button>
      )}
    </Group>
  )
}

/** A página `/busca`: o estado todo na URL, o resultado agrupado por vídeo. */
export default function Busca({ api, consulta }: { api: ClienteDaApi; consulta: ConsultaDaBusca }) {
  const [limite, setLimite] = useState(VIDEOS_POR_VEZ)
  const [carga, setCarga] = useState<Carga>({ tipo: 'carregando' })
  const [tentativas, setTentativas] = useState(0)
  const [programas, setProgramas] = useState<string[]>([])
  const [selecionado, setSelecionado] = useState<number | null>(null)

  // O limite volta ao padrão quando muda a consulta, os chips ou os filtros (não a ordem).
  const chaveDaConsulta = enderecoDaBusca({ ...consulta, ordem: 'relevancia' })
  const [chaveVista, setChaveVista] = useState(chaveDaConsulta)
  if (chaveVista !== chaveDaConsulta) {
    setChaveVista(chaveDaConsulta)
    setLimite(VIDEOS_POR_VEZ)
  }

  const consultaAtual = useRef(consulta)
  useEffect(() => {
    consultaAtual.current = consulta
  })
  const chaveDaBusca = enderecoDaBusca(consulta)
  useEffect(() => {
    if (!consultaAtual.current.q) return
    let ativo = true
    // Cada busca nova recomeça pelo carregamento.
    // oxlint-disable-next-line react/set-state-in-effect
    setCarga((c) => (c.tipo === 'pronta' ? c : { tipo: 'carregando' }))
    // oxlint-disable-next-line react/set-state-in-effect
    setSelecionado(null)
    api.buscar(consultaAtual.current, limite).then(
      (resultado) => {
        if (ativo) setCarga({ tipo: 'pronta', resultado })
      },
      (erro: unknown) => {
        if (!ativo || erro instanceof SessaoExpirada) return
        setCarga({ tipo: 'erro', mensagem: mensagemDoErro(erro), codigo: codigoDoErro(erro) })
      },
    )
    return () => {
      ativo = false
    }
  }, [api, chaveDaBusca, limite, tentativas])

  useEffect(() => {
    let ativo = true
    api.programas().then(
      (lista) => {
        if (ativo) setProgramas(lista)
      },
      () => {},
    )
    return () => {
      ativo = false
    }
  }, [api])

  const resultado = carga.tipo === 'pronta' ? carga.resultado : null
  const momentos = useMemo(
    () => (resultado?.videos ?? []).flatMap((video) => video.momentos.map((momento) => ({ video, momento }))),
    [resultado],
  )

  function abrir(i: number) {
    const { video, momento } = momentos[i]
    navegar(enderecoDoVideo(video.job_id, momento.inicio_ms / 1000, consulta.q))
  }

  // Pelo registro de atalhos, que já ignora os campos de texto.
  useAtalhos([
    {
      tecla: '↓ ↑',
      acao: 'Ir ao momento seguinte ou anterior, também entre vídeos',
      grupo: 'Busca',
      casa: (e) => momentos.length > 0 && (e.key === 'ArrowDown' || e.key === 'ArrowUp'),
      executar: (e) => {
        const passo = e.key === 'ArrowDown' ? 1 : -1
        setSelecionado((atual) =>
          atual === null
            ? passo === 1 ? 0 : momentos.length - 1
            : Math.min(momentos.length - 1, Math.max(0, atual + passo)),
        )
      },
    },
    {
      tecla: 'Enter',
      acao: 'Abrir o vídeo no momento selecionado',
      grupo: 'Busca',
      // Com o foco num momento (pelo Tab), o Enter é do próprio link.
      casa: (e) => e.key === 'Enter' && selecionado !== null && !(e.target instanceof HTMLAnchorElement),
      executar: () => {
        if (selecionado !== null) abrir(selecionado)
      },
    },
  ])

  useEffect(() => {
    if (selecionado === null) return
    const { video, momento } = momentos[selecionado] ?? {}
    if (!video) return
    document
      .querySelector(`[data-momento="${CSS.escape(`${video.job_id}:${momento.inicio_ms}`)}"]`)
      ?.scrollIntoView?.({ block: 'nearest' })
  }, [selecionado, momentos])

  function mudar(mudancas: Partial<ConsultaDaBusca>) {
    navegar(enderecoDaBusca({ ...consulta, ...mudancas }))
  }

  // Os chips da URL valem sobre o entendido: um clique antes de a busca voltar não se perde.
  const ligadas = consulta.evidencias ?? resultado?.entendida.evidencias ?? []
  function alternar(id: Evidencia) {
    mudar({ evidencias: ligadas.includes(id) ? ligadas.filter((e) => e !== id) : [...ligadas, id] })
  }

  if (!consulta.q) {
    return (
      <Box p="md">
        <Text c={CORES.textoSecundario}>Escreva na caixa do topo o que procurar no acervo.</Text>
      </Box>
    )
  }

  const programaEntendido = resultado?.entendida.programa ?? null
  const programaNaTela = consulta.programa ?? programaEntendido ?? ''
  const { desde, ate } = resultado?.entendida ?? { desde: null, ate: null }
  const anoEntendido = desde && ate && desde.slice(0, 4) === ate.slice(0, 4) ? Number(desde.slice(0, 4)) : null
  // Um período entendido que não cabe num ano aparece como está; "Todos os anos" o tira.
  const periodoEntendido =
    consulta.ano === null && anoEntendido === null && (desde || ate) ? rotuloDoPeriodo(desde, ate) : null
  const anoNaTela = consulta.ano ?? anoEntendido
  const valorDoAno = periodoEntendido ? ENTENDIDO : anoNaTela === null ? TODOS : String(anoNaTela)
  const anos = typeof anoNaTela === 'number' && !ANOS.includes(String(anoNaTela)) ? [String(anoNaTela), ...ANOS] : ANOS
  const totalDeMomentos = momentos.length

  return (
    <Stack p="md" gap="md" component="main">
      <Group gap="xs" role="group" aria-label="Tipo de evidência">
        {EVIDENCIAS.map((e) => (
          <Chip
            key={e.id}
            rotulo={e.rotulo}
            tipo={e.tipo}
            ligado={ligadas.includes(e.id)}
            // Sem nenhum chip ligado a busca voltaria ao entendido: o último fica.
            desabilitado={ligadas.length === 1 && ligadas.includes(e.id)}
            aoAlternar={() => alternar(e.id)}
          />
        ))}
        <Select
          aria-label="Programa"
          placeholder="Programa"
          w={170}
          size="xs"
          allowDeselect={false}
          data={[{ value: TODOS, label: 'Todos os programas' }, ...programas]}
          value={programaNaTela || TODOS}
          onChange={(v) => mudar({ programa: v && v !== TODOS ? v : '' })}
        />
        <Select
          aria-label="Ano"
          w={110}
          size="xs"
          allowDeselect={false}
          data={[
            { value: TODOS, label: 'Todos os anos' },
            ...(periodoEntendido ? [{ value: ENTENDIDO, label: periodoEntendido }] : []),
            ...anos,
          ]}
          value={valorDoAno}
          onChange={(v) => {
            if (v !== ENTENDIDO) mudar({ ano: !v || v === TODOS ? 'todos' : Number(v) })
          }}
        />
      </Group>

      {carga.tipo === 'erro' && (
        <AlertaDeErro
          mensagem={carga.mensagem}
          codigo={carga.codigo}
          aoTentar={() => {
            setCarga({ tipo: 'carregando' })
            setTentativas((n) => n + 1)
          }}
        />
      )}
      {carga.tipo === 'carregando' && <Loader role="status" aria-label="Buscando" />}

      {resultado && (
        <>
          <Group justify="space-between">
            <Text size="sm" role="status">
              {contagemDeMomentos(totalDeMomentos)} em {contagemDeVideos(resultado.videos.length)}
            </Text>
            <Select
              aria-label="Ordenar"
              w={190}
              size="xs"
              allowDeselect={false}
              data={[
                { value: 'relevancia', label: 'Ordenar: Relevância' },
                { value: 'data', label: 'Ordenar: Data de exibição' },
              ]}
              value={consulta.ordem}
              onChange={(v) => mudar({ ordem: v === 'data' ? 'data' : 'relevancia' })}
            />
          </Group>

          {resultado.sem_aparicoes.map((s) => {
            const mencoes = s.mencoes_na_fala + s.mencoes_na_tela
            return (
              <Group key={s.pessoa_id} gap="sm">
                <Text size="sm">
                  Nenhuma aparição de {s.nome}.
                  {s.mencoes_na_fala > 0 && ` ${contagemDeMencoes(s.mencoes_na_fala)} na fala.`}
                  {s.mencoes_na_tela > 0 && ` ${contagemDeMencoes(s.mencoes_na_tela)} na tela.`}
                </Text>
                {mencoes > 0 && (
                  <Button
                    type="button"
                    size="compact-sm"
                    variant="default"
                    onClick={() => mudar({ evidencias: [...new Set<Evidencia>([...ligadas, 'citada', 'fala'])] })}
                  >
                    Ver as menções
                  </Button>
                )}
              </Group>
            )
          })}

          {resultado.videos.length === 0 && resultado.sem_aparicoes.length === 0 && (
            <Text c={CORES.textoSecundario}>Nenhum momento encontrado. Tente outras palavras ou tire um filtro.</Text>
          )}

          {resultado.videos.map((video) => (
            <Paper key={video.job_id} withBorder bg="dark.6" p="sm" component="section" aria-label={video.nome}>
              <Stack gap="xs">
                <Group justify="space-between" wrap="nowrap">
                  <Text size="sm" fw={600} style={NUMEROS}>
                    {[
                      video.programa ?? video.nome,
                      video.data_exibicao ? dataDeExibicao(video.data_exibicao) : null,
                      video.duracao_s ? relogio(video.duracao_s * 1000) : null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </Text>
                  <Text size="sm" c={CORES.textoSecundario}>
                    {contagemDeMomentos(video.n_momentos)}
                  </Text>
                </Group>
                <PosicaoDosMomentos video={video} />
                <div>
                  {video.momentos.map((momento) => (
                    <Linha
                      key={momento.inicio_ms}
                      video={video}
                      momento={momento}
                      busca={consulta.q}
                      selecionado={
                        selecionado !== null &&
                        momentos[selecionado]?.video === video &&
                        momentos[selecionado].momento === momento
                      }
                    />
                  ))}
                </div>
              </Stack>
            </Paper>
          ))}

          {resultado.videos.length >= limite && limite < TETO_DE_VIDEOS && (
            <Button
              type="button"
              variant="default"
              onClick={() => setLimite((l) => Math.min(TETO_DE_VIDEOS, l + VIDEOS_POR_VEZ))}
            >
              Mais vídeos
            </Button>
          )}
        </>
      )}
    </Stack>
  )
}
