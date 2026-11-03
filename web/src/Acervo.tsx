import {
  AppShell,
  Badge,
  Box,
  Button,
  Center,
  Chip,
  Group,
  Loader,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
  VisuallyHidden,
} from '@mantine/core'
import {
  IconArrowDown,
  IconFilterOff,
  IconSearch,
  IconUpload,
  IconX,
} from '@tabler/icons-react'
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react'
import { codigoDoErro, SessaoExpirada, type ClienteDaApi } from './api.ts'
import { useAtalhos, type Atalho } from './atalhos.ts'
import EnvioDeVideo from './EnvioDeVideo.tsx'
import { Quadro } from './Miniatura.tsx'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import { fraseDaFalha } from './falhas.ts'
import { dataDeExibicao, filtrosParaBusca, finalizando, haFiltro, SEM_FILTROS, type FiltrosDoAcervo, type Job, type Ordem } from './jobs.ts'
import { tempo } from './linhaDoTempo.ts'
import { ACERVO, enderecoDoVideo, navegar, seguir } from './rotas.ts'
import { CORES, ESTADOS_DO_JOB, FINALIZANDO, type EstadoDoJob } from './tema.ts'

const ESTADOS = Object.keys(ESTADOS_DO_JOB) as EstadoDoJob[]
const NAO_TERMINAIS: string[] = ESTADOS.filter((e) => e !== 'concluido' && e !== 'falhou' && e !== 'cancelado')
const TODOS = '__todos__'
const ESPERA_DA_BUSCA_MS = 300
const NUMEROS = { fontVariantNumeric: 'tabular-nums' } as const
// Linha selecionada: o azul de foco a 16% (0x29) e a barra de 3 px à esquerda.
const SELECIONADA = { background: `${CORES.foco}29`, boxShadow: `inset 3px 0 0 ${CORES.foco}` }

const ATALHOS: Atalho[] = [
  { tecla: '↑ ↓', acao: 'Na tabela: mover a linha selecionada', grupo: 'Acervo' },
  { tecla: 'Enter', acao: 'Na tabela: abrir o vídeo da linha selecionada', grupo: 'Acervo' },
]

function dataEHora(iso: string): string {
  const d = new Date(iso)
  const hora = d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
  return `${d.toLocaleDateString('pt-BR')} ${hora}`
}

type Carga =
  | { tipo: 'carregando' }
  | { tipo: 'pronta'; jobs: Job[]; proximo: string | null }
  | { tipo: 'erro'; codigo: string }

function irPara(filtros: FiltrosDoAcervo, opcoes: { substituir?: boolean } = {}) {
  navegar(`${ACERVO}${filtrosParaBusca(filtros)}`, opcoes)
}

function CabecalhoOrdenavel({
  rotulo,
  ordem,
  atual,
  aoOrdenar,
}: {
  rotulo: string
  ordem: Ordem
  atual: Ordem
  aoOrdenar: (ordem: Ordem) => void
}) {
  const ativa = ordem === atual
  return (
    <Table.Th aria-sort={ativa ? 'descending' : 'none'}>
      <Button
        type="button"
        variant="subtle"
        color="gray"
        size="compact-sm"
        px={0}
        fw={600}
        c={ativa ? undefined : CORES.textoSecundario}
        rightSection={ativa ? <IconArrowDown size={14} aria-hidden /> : null}
        onClick={() => aoOrdenar(ordem)}
      >
        {rotulo}
      </Button>
    </Table.Th>
  )
}

function Linha({
  job,
  selecionada,
  ancora,
  aoSelecionar,
}: {
  job: Job
  selecionada: boolean
  /** Só uma linha entra na ordem do Tab; as setas movem o foco entre as demais. */
  ancora: boolean
  aoSelecionar: (id: string) => void
}) {
  const estado = finalizando(job) ? FINALIZANDO : ESTADOS_DO_JOB[job.estado as EstadoDoJob]
  // A tela do vídeo também explica a falha, como na Biblioteca de antes.
  const abre = job.estado === 'concluido' || job.estado === 'falhou'
  const endereco = enderecoDoVideo(job.id)
  const enviadoPor = job.enviado_por?.nome ?? '—'

  function aoTeclar(e: KeyboardEvent<HTMLTableRowElement>) {
    if (e.target !== e.currentTarget) return
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      const vizinha =
        e.key === 'ArrowDown'
          ? e.currentTarget.nextElementSibling
          : e.currentTarget.previousElementSibling
      if (vizinha instanceof HTMLElement) {
        e.preventDefault()
        vizinha.focus()
      }
    } else if (e.key === 'Enter' && abre) {
      e.preventDefault()
      navegar(endereco)
    }
  }

  return (
    <Table.Tr
      tabIndex={selecionada || ancora ? 0 : -1}
      data-selected={selecionada || undefined}
      aria-selected={selecionada}
      onFocus={(e: React.FocusEvent<HTMLTableRowElement>) => {
        if (e.target === e.currentTarget) aoSelecionar(job.id)
      }}
      onClick={() => {
        aoSelecionar(job.id)
        if (abre) navegar(endereco)
      }}
      onKeyDown={aoTeclar}
      style={{ cursor: abre ? 'pointer' : undefined, ...(selecionada ? SELECIONADA : {}) }}
    >
      <Table.Td p={0} w={72}>
        <Box ml="sm">
          <Quadro url={job.capa_url} largura={64} altura={36} />
        </Box>
      </Table.Td>
      <Table.Td maw={360}>
        <Tooltip label={job.nome}>
          {abre ? (
            <Text
              component="a"
              href={endereco}
              size="sm"
              truncate
              c="inherit"
              onClick={(e: MouseEvent<HTMLAnchorElement>) => {
                seguir(e, endereco)
                e.stopPropagation()
              }}
            >
              {job.nome}
            </Text>
          ) : (
            <Text size="sm" truncate>
              {job.nome}
            </Text>
          )}
        </Tooltip>
        {job.codigo_falha && (
          <Tooltip label={`Código para o suporte: ${job.codigo_falha}`}>
            <Text size="xs" c={CORES.falhou} truncate>
              {fraseDaFalha(job.codigo_falha)}
            </Text>
          </Tooltip>
        )}
      </Table.Td>
      <Table.Td>{job.programa ?? '—'}</Table.Td>
      <Table.Td style={NUMEROS}>
        {dataDeExibicao(job.data_exibicao)}
      </Table.Td>
      <Table.Td style={NUMEROS}>
        {job.duracao_s != null ? tempo(job.duracao_s * 1000) : '—'}
      </Table.Td>
      <Table.Td>
        <Badge color={estado?.cor}>
          {estado?.rotulo ?? job.estado}
        </Badge>
      </Table.Td>
      <Table.Td maw={240}>
        <Text size="sm" truncate>
          {enviadoPor}
        </Text>
      </Table.Td>
      <Table.Td style={{ ...NUMEROS, whiteSpace: 'nowrap' }}>
        {dataEHora(job.criado_em)}
      </Table.Td>
    </Table.Tr>
  )
}

/** O acervo: filtros na URL, tabela densa que rola sozinha, envio num diálogo. */
export default function Acervo({
  api,
  filtros,
  podeEnviar,
  intervaloMs = 5000,
}: {
  api: ClienteDaApi
  filtros: FiltrosDoAcervo
  podeEnviar: boolean
  intervaloMs?: number
}) {
  const [carga, setCarga] = useState<Carga>({ tipo: 'carregando' })
  const [maisFalhou, setMaisFalhou] = useState<string | null>(null)
  const [carregandoMais, setCarregandoMais] = useState(false)
  const [atualizacaoFalhou, setAtualizacaoFalhou] = useState<string | null>(null)
  const [selecionada, setSelecionada] = useState<string | null>(null)
  const [programas, setProgramas] = useState<string[]>([])
  const [envioAberto, setEnvioAberto] = useState(false)
  const [busca, setBusca] = useState(filtros.q)
  const [recarga, setRecarga] = useState(0)
  useAtalhos(ATALHOS)

  const chave = filtrosParaBusca(filtros)
  // Cada carga da lista (outro filtro ou um envio) abre uma geração; resposta de "Carregar
  // mais" ou da atualização pedida numa geração anterior é descartada.
  const geracao = useRef(0)
  const filtrosAtuais = useRef(filtros)
  const chaveNaTela = useRef<string | null>(null)
  useEffect(() => {
    filtrosAtuais.current = filtros
  })

  useEffect(() => {
    let ativo = true
    geracao.current += 1
    // Recomeça a lista quando os filtros mudam ou um envio cria um Job.
    // Um envio recarrega a mesma lista sem piscar o carregamento; outro filtro, não.
    if (chaveNaTela.current !== chave) {
      // oxlint-disable-next-line react/set-state-in-effect
      setCarga({ tipo: 'carregando' })
    }
    // oxlint-disable-next-line react/set-state-in-effect
    setMaisFalhou(null)
    // oxlint-disable-next-line react/set-state-in-effect
    setAtualizacaoFalhou(null)
    api.acervo(filtrosAtuais.current).then(
      (pagina) => {
        if (!ativo) return
        chaveNaTela.current = chave
        setCarga({ tipo: 'pronta', ...pagina })
      },
      (erro: unknown) => {
        if (!ativo || erro instanceof SessaoExpirada) return
        chaveNaTela.current = null
        setCarga({ tipo: 'erro', codigo: codigoDoErro(erro) })
      },
    )
    return () => {
      ativo = false
    }
  }, [api, chave, recarga])

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

  // A caixa de busca espera 300 ms; mudança vinda da URL (Limpar, voltar) a sobrescreve.
  // A URL leva o texto sem os espaços das pontas: o espaço que se acabou de digitar fica na caixa.
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    setBusca((atual) => (atual.trim() === filtros.q ? atual : filtros.q))
  }, [filtros.q])
  useEffect(() => {
    if (busca.trim() === filtros.q) return
    const relogio = setTimeout(
      () => irPara({ ...filtrosAtuais.current, q: busca.trim() }, { substituir: true }),
      ESPERA_DA_BUSCA_MS,
    )
    return () => clearTimeout(relogio)
  }, [busca, filtros.q])

  // Só as linhas em andamento são consultadas de novo, e só com a aba à vista.
  const emAndamento = carga.tipo === 'pronta' ? carga.jobs.filter((j) => NAO_TERMINAIS.includes(j.estado) || finalizando(j)) : []
  const idsEmAndamento = emAndamento.map((j) => j.id).join(',')
  // Com a API lenta, uma rodada não começa enquanto a anterior não volta.
  const atualizando = useRef(false)
  const atualizar = useCallback(async () => {
    const ids = idsEmAndamento ? idsEmAndamento.split(',') : []
    if (ids.length === 0 || document.visibilityState !== 'visible' || atualizando.current) return
    const daVez = geracao.current
    atualizando.current = true
    try {
      const novos = await Promise.all(ids.map((id) => api.job(id).detalhe()))
      if (geracao.current !== daVez) return
      setAtualizacaoFalhou(null)
      // O detalhe não traz a capa (só a listagem assina a URL): fica a da lista.
      const comACapa = (j: Job) => {
        const novo = novos.find((n) => n.id === j.id)
        return novo ? { ...novo, capa_url: novo.capa_url ?? j.capa_url } : j
      }
      setCarga((c) => (c.tipo === 'pronta' ? { ...c, jobs: c.jobs.map(comACapa) } : c))
    } catch (erro) {
      if (geracao.current === daVez && !(erro instanceof SessaoExpirada)) {
        setAtualizacaoFalhou(codigoDoErro(erro))
      }
    } finally {
      atualizando.current = false
    }
  }, [api, idsEmAndamento])
  useEffect(() => {
    if (!idsEmAndamento) return
    const relogio = setInterval(() => void atualizar(), intervaloMs)
    document.addEventListener('visibilitychange', atualizar)
    return () => {
      clearInterval(relogio)
      document.removeEventListener('visibilitychange', atualizar)
    }
  }, [atualizar, idsEmAndamento, intervaloMs])

  async function carregarMais() {
    if (carga.tipo !== 'pronta' || !carga.proximo || carregandoMais) return
    const daVez = geracao.current
    setCarregandoMais(true)
    setMaisFalhou(null)
    try {
      const pagina = await api.acervo(filtros, carga.proximo)
      if (geracao.current !== daVez) return
      setCarga((c) =>
        c.tipo === 'pronta'
          ? { tipo: 'pronta', jobs: [...c.jobs, ...pagina.jobs], proximo: pagina.proximo }
          : c,
      )
    } catch (erro) {
      if (geracao.current === daVez && !(erro instanceof SessaoExpirada)) {
        setMaisFalhou(codigoDoErro(erro))
      }
    } finally {
      setCarregandoMais(false)
    }
  }

  const limparFiltros = () => irPara(SEM_FILTROS)
  const mudar = (parte: Partial<FiltrosDoAcervo>) => irPara({ ...filtros, ...parte })
  const jobs = carga.tipo === 'pronta' ? carga.jobs : []

  return (
    <AppShell.Main
      bg="dark.7"
      h="100vh"
      style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
    >
      <Group gap="sm" pb="sm" wrap="nowrap" justify="space-between" align="flex-end">
        <Group gap="sm" wrap="wrap" align="flex-end" style={{ flex: 1 }}>
          <TextInput
            aria-label="Buscar por nome"
            placeholder="Buscar por nome"
            size="xs"
            w={220}
            leftSection={<IconSearch size={14} aria-hidden />}
            value={busca}
            onChange={(e) => setBusca(e.currentTarget.value)}
          />
          <Select
            aria-label="Programa"
            size="xs"
            w={180}
            allowDeselect={false}
            data={[{ value: TODOS, label: 'Todos' }, ...programas]}
            value={filtros.programa || TODOS}
            onChange={(valor) => mudar({ programa: valor && valor !== TODOS ? valor : '' })}
          />
          <TextInput
            type="date"
            aria-label="Exibido de"
            size="xs"
            value={filtros.de}
            onChange={(e) => mudar({ de: e.currentTarget.value })}
          />
          <TextInput
            type="date"
            aria-label="Exibido até"
            size="xs"
            value={filtros.ate}
            onChange={(e) => mudar({ ate: e.currentTarget.value })}
          />
          <Chip.Group
            multiple
            value={filtros.estado}
            onChange={(estado) => mudar({ estado })}
          >
            <Group gap={4} role="group" aria-label="Estado">
              {ESTADOS.map((estado) => (
                <Chip
                  key={estado}
                  value={estado}
                  size="xs"
                  variant="outline"
                  color={ESTADOS_DO_JOB[estado].cor}
                >
                  {ESTADOS_DO_JOB[estado].rotulo}
                </Chip>
              ))}
            </Group>
          </Chip.Group>
          {haFiltro(filtros) && (
            <Button
              type="button"
              variant="subtle"
              color="gray"
              size="compact-sm"
              leftSection={<IconX size={14} aria-hidden />}
              onClick={limparFiltros}
            >
              Limpar filtros
            </Button>
          )}
        </Group>
        {podeEnviar && (
          <Button
            type="button"
            size="xs"
            leftSection={<IconUpload size={14} aria-hidden />}
            onClick={() => setEnvioAberto(true)}
          >
            Enviar vídeo
          </Button>
        )}
      </Group>

      {maisFalhou !== null ? (
        <Box mb="sm">
          <AlertaDeErro
            mensagem="Não foi possível carregar mais vídeos."
            codigo={maisFalhou}
            aoTentar={() => void carregarMais()}
          />
        </Box>
      ) : (
        atualizacaoFalhou !== null && (
          <Box mb="sm">
            <AlertaDeErro
              mensagem="Não foi possível atualizar a lista; tentando de novo."
              codigo={atualizacaoFalhou}
            />
          </Box>
        )
      )}

      {carga.tipo === 'carregando' && (
        <Center py="xl">
          <Loader role="status" aria-label="Carregando o acervo" />
        </Center>
      )}
      {carga.tipo === 'erro' && (
        <Center py="xl">
          <AlertaDeErro
            mensagem="Não foi possível carregar o acervo."
            codigo={carga.codigo}
            aoTentar={() => setRecarga((n) => n + 1)}
          />
        </Center>
      )}
      {carga.tipo === 'pronta' && jobs.length === 0 && (
        <Center py="xl">
          <Stack align="center" gap="xs">
            {haFiltro(filtros) ? (
              <>
                <Text c="dimmed">Nenhum vídeo com esses filtros.</Text>
                <Button
                  type="button"
                  size="xs"
                  variant="default"
                  leftSection={<IconFilterOff size={14} aria-hidden />}
                  onClick={limparFiltros}
                >
                  Limpar filtros
                </Button>
              </>
            ) : (
              <Text c="dimmed">Nenhum vídeo enviado ainda.</Text>
            )}
          </Stack>
        </Center>
      )}
      {carga.tipo === 'pronta' && jobs.length > 0 && (
        // Só a tabela rola: a página inteira fica parada.
        <Box style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
          <Table stickyHeader highlightOnHover aria-label="Vídeos do acervo" style={{ tableLayout: 'auto' }}>
            <Table.Thead bg="dark.6">
              <Table.Tr>
                <Table.Th w={72}>
                  <VisuallyHidden>Miniatura</VisuallyHidden>
                </Table.Th>
                <Table.Th>Nome do arquivo</Table.Th>
                <Table.Th>Programa</Table.Th>
                <CabecalhoOrdenavel
                  rotulo="Data de exibição"
                  ordem="exibicao"
                  atual={filtros.ordem}
                  aoOrdenar={(ordem) => mudar({ ordem })}
                />
                <Table.Th>Duração</Table.Th>
                <Table.Th>Estado</Table.Th>
                <Table.Th>Enviado por</Table.Th>
                <CabecalhoOrdenavel
                  rotulo="Enviado em"
                  ordem="enviado"
                  atual={filtros.ordem}
                  aoOrdenar={(ordem) => mudar({ ordem })}
                />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {jobs.map((job, i) => (
                <Linha
                  key={job.id}
                  job={job}
                  selecionada={job.id === selecionada}
                  ancora={i === 0 && !jobs.some((j) => j.id === selecionada)}
                  aoSelecionar={setSelecionada}
                />
              ))}
            </Table.Tbody>
          </Table>
          {carga.proximo && (
            <Center py="sm">
              <Button
                type="button"
                size="xs"
                variant="default"
                loading={carregandoMais}
                onClick={() => void carregarMais()}
              >
                Carregar mais
              </Button>
            </Center>
          )}
        </Box>
      )}

      {podeEnviar && (
        <EnvioDeVideo
          api={api}
          programas={programas}
          aberto={envioAberto}
          aoFechar={() => setEnvioAberto(false)}
          aoCriar={() => setRecarga((n) => n + 1)}
        />
      )}
    </AppShell.Main>
  )
}
