import {
  Alert,
  Badge,
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
import { IconX } from '@tabler/icons-react'
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { codigoDoErro, SessaoExpirada, type ClienteDaApi } from './api.ts'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import { useAtalhos, type Atalho } from './atalhos.ts'
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
} from './entradas.ts'
import { etapaDeReprocesso, nomeDaEtapa, partidaDaEtapa } from './etapas.ts'
import { falhaDaAcao, type Falha } from './falhaDaAcao.ts'
import { fraseDaFalha } from './falhas.ts'
import { dataEHora, type EtapaDoJob, type Job } from './jobs.ts'
import { relogio } from './linhaDoTempo.ts'
import { ReprocessarEtapa } from './ReprocessarEtapa.tsx'
import { enderecoDasEntradas, navegar } from './rotas.ts'
import { CORES, ESTADOS_DO_JOB, type EstadoDoJob } from './tema.ts'

const ESTADOS = Object.keys(ESTADOS_DO_JOB) as EstadoDoJob[]
const TODOS = '__todos__'
const PESSOAS = 'pessoas'
const NUMEROS = { fontVariantNumeric: 'tabular-nums' } as const

const ATALHOS: Atalho[] = [{ tecla: 'Enter', acao: 'Na tabela: mostrar ou esconder as etapas da linha', grupo: 'Entradas' }]

type Carga = { tipo: 'carregando' } | { tipo: 'pronta'; jobs: Job[]; proximo: string | null } | { tipo: 'erro'; codigo: string }

/** O que a linha tem aberto embaixo: a confirmação de reprocessar o que falhou ou a escolha da etapa. */
type Aberto = { id: string; tipo: 'falha' | 'etapa' }

function irPara(filtros: FiltrosDasEntradas) {
  navegar(enderecoDasEntradas(filtros), { substituir: true })
}

function resultadoDaEtapa(etapa: EtapaDoJob): string {
  if (etapa.resultado === 'concluida') return 'Concluída'
  if (etapa.resultado === 'falhou') return 'Falhou'
  return 'Em andamento'
}

function EtapasDoJob({ job, agora }: { job: Job; agora: number }) {
  const etapas = job.etapas ?? []
  if (etapas.length === 0) return <Text size="sm" c={CORES.textoSecundario}>Nenhuma etapa registrada ainda.</Text>
  return (
    <Table aria-label={`Etapas de ${job.nome}`} verticalSpacing={2}>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Etapa</Table.Th>
          <Table.Th>Início</Table.Th>
          <Table.Th>Fim</Table.Th>
          <Table.Th>Duração</Table.Th>
          <Table.Th>Resultado</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {etapas.map((e) => (
          <Table.Tr key={e.nome}>
            <Table.Td>{nomeDaEtapa(e.nome)}</Table.Td>
            <Table.Td style={NUMEROS}>{dataEHora(e.inicio)}</Table.Td>
            <Table.Td style={NUMEROS}>{e.fim ? dataEHora(e.fim) : '—'}</Table.Td>
            <Table.Td style={NUMEROS}>{relogio((e.fim ? new Date(e.fim).getTime() : agora) - new Date(e.inicio).getTime())}</Table.Td>
            <Table.Td>
              <Text size="sm" c={e.resultado === 'falhou' ? CORES.falhou : undefined}>
                {resultadoDaEtapa(e)}
              </Text>
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  )
}

function Falha({ job, etapaFalha }: { job: Job; etapaFalha: string | null }) {
  if (job.codigo_falha) {
    return (
      <Tooltip label={`Código para o suporte: ${job.codigo_falha}`}>
        <Text size="xs" c={CORES.falhou}>
          {fraseDaFalha(job.codigo_falha)}
        </Text>
      </Tooltip>
    )
  }
  if (etapaFalha && job.estado === 'concluido') {
    return (
      <Text size="xs" c={CORES.falhou}>
        {`A etapa ${nomeDaEtapa(etapaFalha)} falhou; o vídeo segue concluído.`}
      </Text>
    )
  }
  return null
}

function Linha({
  job,
  agora,
  aberta,
  aoAlternar,
  podeReprocessar,
  podeEscolherEtapa,
  aoPedir,
}: {
  job: Job
  agora: number
  aberta: boolean
  aoAlternar: () => void
  podeReprocessar: boolean
  podeEscolherEtapa: boolean
  aoPedir: (tipo: Aberto['tipo']) => void
}) {
  const estado = ESTADOS_DO_JOB[job.estado as EstadoDoJob]
  const partida = etapaDeReprocesso(job)
  const falhaDoArquivo = job.estado === 'falhou' && partida === null
  const andando = emAndamento(job)
  const etapaFalha = job.estado === 'concluido' ? partida : null

  function aoTeclar(e: KeyboardEvent<HTMLTableRowElement>) {
    if (e.target !== e.currentTarget || e.key !== 'Enter') return
    e.preventDefault()
    aoAlternar()
  }

  return (
    <Table.Tr tabIndex={0} aria-expanded={aberta} onClick={aoAlternar} onKeyDown={aoTeclar} style={{ cursor: 'pointer' }}>
      <Table.Td maw={320}>
        <Tooltip label={job.nome}>
          <Text size="sm" truncate>
            {job.nome}
          </Text>
        </Tooltip>
      </Table.Td>
      <Table.Td maw={220}>
        <Text size="sm" truncate>
          {job.enviado_por?.nome ?? '—'}
        </Text>
      </Table.Td>
      <Table.Td>{job.programa ?? '—'}</Table.Td>
      <Table.Td style={{ ...NUMEROS, whiteSpace: 'nowrap' }}>{dataEHora(job.criado_em)}</Table.Td>
      <Table.Td>
        {job.etapa_atual ? (
          <Badge color={CORES.andamento}>{nomeDaEtapa(job.etapa_atual)}</Badge>
        ) : (
          <Badge color={estado?.cor}>{estado?.rotulo ?? job.estado}</Badge>
        )}
      </Table.Td>
      <Table.Td style={NUMEROS}>{relogio(tempoDaEntradaMs(job, agora))}</Table.Td>
      <Table.Td maw={280}>
        <Falha job={job} etapaFalha={etapaFalha} />
      </Table.Td>
      <Table.Td onClick={(e) => e.stopPropagation()}>
        <Group gap="xs" wrap="nowrap">
          {falhaDoArquivo && (
            <Tooltip label={job.codigo_falha ? fraseDaFalha(job.codigo_falha) : 'O arquivo não foi aceito.'}>
              <Text size="sm">Envie o arquivo de novo</Text>
            </Tooltip>
          )}
          {podeReprocessar && partida && (
            <Button type="button" size="compact-xs" variant="default" aria-label={`Reprocessar ${job.nome}`} onClick={() => aoPedir('falha')}>
              Reprocessar
            </Button>
          )}
          {podeEscolherEtapa && job.estado === 'concluido' && !andando && (
            <Button type="button" size="compact-xs" variant="default" aria-label={`Reprocessar ${job.nome} a partir de uma etapa`} onClick={() => aoPedir('etapa')}>
              Reprocessar…
            </Button>
          )}
        </Group>
      </Table.Td>
    </Table.Tr>
  )
}

function ConfirmarReprocesso({
  job,
  etapa,
  aoConfirmar,
  aoCancelar,
}: {
  job: Job
  etapa: string
  aoConfirmar: (motivo: string) => Promise<void>
  aoCancelar: () => void
}) {
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
    <Stack gap="xs" onKeyDown={(e) => e.key === 'Escape' && !enviando && aoCancelar()}>
      <Text size="sm">{`Reprocessar ${partidaDaEtapa(etapa) ? `a partir ${partidaDaEtapa(etapa)}` : ''}? As etapas já concluídas não são refeitas.`}</Text>
      <TextInput
        label="Motivo (opcional)"
        size="xs"
        maxLength={500}
        value={motivo}
        onChange={(e) => setMotivo(e.currentTarget.value)}
        data-autofocus
        autoFocus
      />
      {falha && <AlertaDeErro mensagem={falha.mensagem} codigo={falha.codigo} />}
      <Group gap="xs">
        <Button type="button" size="xs" loading={enviando} onClick={() => void confirmar()}>
          Reprocessar
        </Button>
        <Button type="button" size="xs" variant="default" disabled={enviando} onClick={aoCancelar}>
          Cancelar
        </Button>
      </Group>
    </Stack>
  )
}

/** `/admin/entradas`: todos os vídeos que entraram, de pessoas e de sistemas, e o reprocessamento. */
export default function Entradas({
  api,
  filtros,
  podeReprocessar,
  podeEscolherEtapa,
  intervaloMs = 10_000,
}: {
  api: ClienteDaApi
  filtros: FiltrosDasEntradas
  /** `video.reprocessar`: o botão "Reprocessar" das falhas de etapa. */
  podeReprocessar: boolean
  /** `video.reprocessar_etapa`: o "Reprocessar…" dos vídeos concluídos. */
  podeEscolherEtapa: boolean
  intervaloMs?: number
}) {
  const [carga, setCarga] = useState<Carga>({ tipo: 'carregando' })
  const [recarga, setRecarga] = useState(0)
  const [carregandoMais, setCarregandoMais] = useState(false)
  const [maisFalhou, setMaisFalhou] = useState<string | null>(null)
  const [atualizacaoFalhou, setAtualizacaoFalhou] = useState<string | null>(null)
  const [abertas, setAbertas] = useState<string[]>([])
  const [pedido, setPedido] = useState<Aberto | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [sistemas, setSistemas] = useState<string[]>([])
  const [agora, setAgora] = useState(() => Date.now())
  useAtalhos(ATALHOS)

  // Só sistema e estado vão à API: trocar o resto não recarrega a lista.
  const chave = JSON.stringify([sistemaDoFiltro(filtros.por), filtros.estado])
  const filtrosAtuais = useRef(filtros)
  useEffect(() => {
    filtrosAtuais.current = filtros
  })
  // Cada carga da lista abre uma geração; a resposta de uma anterior é descartada.
  const geracao = useRef(0)

  useEffect(() => {
    let ativo = true
    geracao.current += 1
    // Recomeça a lista quando o sistema ou o estado mudam.
    // oxlint-disable-next-line react/set-state-in-effect
    setCarga({ tipo: 'carregando' })
    // oxlint-disable-next-line react/set-state-in-effect
    setMaisFalhou(null)
    // oxlint-disable-next-line react/set-state-in-effect
    setAtualizacaoFalhou(null)
    api.entradas(filtrosAtuais.current).then(
      (pagina) => {
        if (ativo) setCarga({ tipo: 'pronta', ...pagina })
      },
      (erro: unknown) => {
        if (ativo && !(erro instanceof SessaoExpirada)) setCarga({ tipo: 'erro', codigo: codigoDoErro(erro) })
      },
    )
    return () => {
      ativo = false
    }
  }, [api, chave, recarga])

  // Os sistemas do filtro: os que têm chave (quem não pode ver as chaves fica só com os das linhas).
  useEffect(() => {
    let ativo = true
    api.chaves.listar().then(
      (chaves) => {
        if (ativo) setSistemas(chaves.map((c) => c.sistema))
      },
      () => {},
    )
    return () => {
      ativo = false
    }
  }, [api])

  const jobs = carga.tipo === 'pronta' ? carga.jobs : []
  const proximo = carga.tipo === 'pronta' ? carga.proximo : null
  const sistemasConhecidos = [
    ...new Set([
      ...sistemas,
      ...jobs.flatMap((j) => (j.enviado_por?.tipo === 'sistema' && j.enviado_por.nome ? [j.enviado_por.nome] : [])),
      ...(sistemaDoFiltro(filtros.por) ? [sistemaDoFiltro(filtros.por)!] : []),
    ]),
  ].sort((a, b) => a.localeCompare(b, 'pt-BR'))

  // Só as linhas em andamento são consultadas de novo, e só com a aba à vista.
  const idsEmAndamento = jobs.filter(emAndamento).map((j) => j.id).join(',')
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
      setAgora(Date.now())
      setCarga((c) => (c.tipo === 'pronta' ? { ...c, jobs: c.jobs.map((j) => novos.find((n) => n.id === j.id) ?? j) } : c))
    } catch (erro) {
      if (geracao.current === daVez && !(erro instanceof SessaoExpirada)) setAtualizacaoFalhou(codigoDoErro(erro))
    } finally {
      atualizando.current = false
    }
  }, [api, idsEmAndamento])
  useEffect(() => {
    if (!idsEmAndamento) return
    const relogioDaTela = setInterval(() => void atualizar(), intervaloMs)
    document.addEventListener('visibilitychange', atualizar)
    return () => {
      clearInterval(relogioDaTela)
      document.removeEventListener('visibilitychange', atualizar)
    }
  }, [atualizar, idsEmAndamento, intervaloMs])

  async function carregarMais() {
    if (carga.tipo !== 'pronta' || !carga.proximo || carregandoMais) return
    const daVez = geracao.current
    setCarregandoMais(true)
    setMaisFalhou(null)
    try {
      const pagina = await api.entradas(filtros, carga.proximo)
      if (geracao.current !== daVez) return
      setAgora(Date.now())
      setCarga((c) => (c.tipo === 'pronta' ? { tipo: 'pronta', jobs: [...c.jobs, ...pagina.jobs], proximo: pagina.proximo } : c))
    } catch (erro) {
      if (geracao.current === daVez && !(erro instanceof SessaoExpirada)) setMaisFalhou(codigoDoErro(erro))
    } finally {
      setCarregandoMais(false)
    }
  }

  function trocarJob(novo: Job) {
    setCarga((c) => (c.tipo === 'pronta' ? { ...c, jobs: c.jobs.map((j) => (j.id === novo.id ? novo : j)) } : c))
    // Chamada de um manipulador de evento, não da renderização.
    // oxlint-disable-next-line react/purity
    setAgora(Date.now())
    setPedido(null)
  }

  function alternar(id: string) {
    setAbertas((atuais) => (atuais.includes(id) ? atuais.filter((a) => a !== id) : [...atuais, id]))
  }

  const mudar = (parte: Partial<FiltrosDasEntradas>) => irPara({ ...filtros, ...parte })
  const visiveis = jobs.filter((j) => casaComOsFiltrosDoCliente(j, filtros))
  const haMais = proximo !== null && !passouDoPeriodo(jobs, filtros)

  return (
    <Stack gap="sm">
      <Group gap="sm" wrap="wrap" align="flex-end">
        <Select
          aria-label="Enviado por"
          size="xs"
          w={200}
          allowDeselect={false}
          data={[
            { value: TODOS, label: 'Todos' },
            { value: PESSOAS, label: 'Pessoas' },
            ...sistemasConhecidos.map((s) => ({ value: porSistema(s), label: s })),
          ]}
          value={filtros.por || TODOS}
          onChange={(valor) => mudar({ por: valor && valor !== TODOS ? valor : '' })}
        />
        <TextInput type="date" aria-label="Enviado de" size="xs" value={filtros.de} onChange={(e) => mudar({ de: e.currentTarget.value })} />
        <TextInput type="date" aria-label="Enviado até" size="xs" value={filtros.ate} onChange={(e) => mudar({ ate: e.currentTarget.value })} />
        <Chip.Group multiple value={filtros.estado} onChange={(estado) => mudar({ estado })}>
          <Group gap={4} role="group" aria-label="Estado">
            {ESTADOS.map((e) => (
              <Chip key={e} value={e} size="xs" variant="outline" color={ESTADOS_DO_JOB[e].cor}>
                {ESTADOS_DO_JOB[e].rotulo}
              </Chip>
            ))}
          </Group>
        </Chip.Group>
        {haFiltroDeEntradas(filtros) && (
          <Button type="button" variant="subtle" color="gray" size="compact-sm" leftSection={<IconX size={14} aria-hidden />} onClick={() => irPara(SEM_FILTROS_DAS_ENTRADAS)}>
            Limpar filtros
          </Button>
        )}
      </Group>
      {aviso && (
        <Alert color={CORES.concluido} variant="light" role="status" withCloseButton closeButtonLabel="Fechar o aviso" onClose={() => setAviso(null)}>
          {aviso}
        </Alert>
      )}
      {maisFalhou !== null ? (
        <AlertaDeErro mensagem="Não foi possível carregar mais vídeos." codigo={maisFalhou} aoTentar={() => void carregarMais()} />
      ) : (
        atualizacaoFalhou !== null && <AlertaDeErro mensagem="Não foi possível atualizar a lista; tentando de novo." codigo={atualizacaoFalhou} />
      )}
      {carga.tipo === 'carregando' && (
        <Center py="xl">
          <Loader role="status" aria-label="Carregando as entradas" size="sm" />
        </Center>
      )}
      {carga.tipo === 'erro' && <AlertaDeErro mensagem="Não foi possível carregar as entradas. Tente de novo." codigo={carga.codigo} aoTentar={() => setRecarga((n) => n + 1)} />}
      {carga.tipo === 'pronta' && visiveis.length === 0 && (
        <Text size="sm">{haFiltroDeEntradas(filtros) ? 'Nenhum vídeo com esses filtros.' : 'Nenhum vídeo entrou ainda.'}</Text>
      )}
      {carga.tipo === 'pronta' && visiveis.length > 0 && (
        <Table aria-label="Entradas" highlightOnHover verticalSpacing={4}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Arquivo</Table.Th>
              <Table.Th>Enviado por</Table.Th>
              <Table.Th>Programa</Table.Th>
              <Table.Th>Enviado em</Table.Th>
              <Table.Th>Etapa ou estado</Table.Th>
              <Table.Th>Tempo</Table.Th>
              <Table.Th>Falha</Table.Th>
              <Table.Th>
                <VisuallyHidden>Ações</VisuallyHidden>
              </Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {visiveis.flatMap((job) => {
              const aberta = abertas.includes(job.id)
              const doPedido = pedido?.id === job.id ? pedido.tipo : null
              const partida = etapaDeReprocesso(job)
              return [
                <Linha
                  key={job.id}
                  job={job}
                  agora={agora}
                  aberta={aberta}
                  aoAlternar={() => alternar(job.id)}
                  podeReprocessar={podeReprocessar}
                  podeEscolherEtapa={podeEscolherEtapa}
                  aoPedir={(tipo) => {
                    setAviso(null)
                    setPedido(pedido?.id === job.id && pedido.tipo === tipo ? null : { id: job.id, tipo })
                  }}
                />,
                aberta && (
                  <Table.Tr key={`${job.id}:etapas`}>
                    <Table.Td colSpan={8}>
                      <EtapasDoJob job={job} agora={agora} />
                    </Table.Td>
                  </Table.Tr>
                ),
                doPedido === 'falha' && partida && (
                  <Table.Tr key={`${job.id}:falha`}>
                    <Table.Td colSpan={8}>
                      <ConfirmarReprocesso
                        job={job}
                        etapa={partida}
                        aoCancelar={() => setPedido(null)}
                        aoConfirmar={async (motivo) => {
                          const novo = await api.job(job.id).reprocessarOQueFalhou(motivo)
                          trocarJob(novo)
                          setAviso(`${job.nome} voltou a ser processado a partir ${partidaDaEtapa(partida)}.`)
                        }}
                      />
                    </Table.Td>
                  </Table.Tr>
                ),
                doPedido === 'etapa' && (
                  <Table.Tr key={`${job.id}:etapa`}>
                    <Table.Td colSpan={8}>
                      <ReprocessarEtapa
                        api={api.job(job.id)}
                        aoCancelar={() => setPedido(null)}
                        aoReprocessar={(novo, etapa) => {
                          trocarJob(novo)
                          setAviso(`${job.nome} voltou a ser processado a partir ${partidaDaEtapa(etapa)}.`)
                        }}
                      />
                    </Table.Td>
                  </Table.Tr>
                ),
              ]
            })}
          </Table.Tbody>
        </Table>
      )}
      {carga.tipo === 'pronta' && haMais && (
        <Group justify="center">
          <Button type="button" size="xs" variant="default" loading={carregandoMais} onClick={() => void carregarMais()}>
            Carregar mais
          </Button>
        </Group>
      )}
    </Stack>
  )
}
