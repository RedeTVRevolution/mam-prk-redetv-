import { Box, Group, Loader, Select, Stack, Table, Tabs, Text, TextInput, Title } from '@mantine/core'
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import type { ClienteDaApi } from './api.ts'
import { periodoInvertido } from './auditoria.ts'
import { dataDeExibicao, dataEHora } from './jobs.ts'
import { duracaoLegivel } from './tempoDeTela.ts'
import {
  ABAS_DO_PAINEL,
  diaCurto,
  horasDeVideo,
  mesCurto,
  programaEUsuarioJuntos,
  type AbaDoPainel,
  type AtivosNoPeriodo,
  type DiaDeAcessos,
  type DiaDeBuscas,
  type FiltrosDoPainel,
  type NumerosDeVideos,
  type OpcoesDoPainel,
  type RelatorioDeAcessos,
  type RelatorioDeBuscas,
  type RelatorioDeVideos,
} from './painelDaDiretoria.ts'
import { AlertaDoCsv, BotaoDeCsv, ErroDoRelatorio } from './relatorios.tsx'
import { enderecoDoPainel, navegar } from './rotas.ts'
import { CORES } from './tema.ts'
import { useBaixarCsv, useRelatorio } from './useRelatorio.ts'

const TODOS = '__todos__'
const NUMEROS = { fontVariantNumeric: 'tabular-nums' } as const

function Filtros({
  api,
  filtros,
  comPrograma,
  aoMudar,
}: {
  api: ClienteDaApi
  filtros: FiltrosDoPainel
  comPrograma: boolean
  aoMudar: (parte: Partial<FiltrosDoPainel>) => void
}) {
  const [opcoes, setOpcoes] = useState<OpcoesDoPainel>({ programas: [], usuarios: [] })
  useEffect(() => {
    let atual = true
    api
      .opcoesDoPainel()
      .then((o) => atual && setOpcoes(o))
      .catch(() => undefined)
    return () => {
      atual = false
    }
  }, [api])

  return (
    <Group gap="sm" align="flex-end" wrap="wrap">
      <Select
        aria-label="Programa"
        size="xs"
        w={200}
        allowDeselect={false}
        disabled={!comPrograma}
        data={[{ value: TODOS, label: 'Todos os programas' }, ...opcoes.programas]}
        value={(comPrograma && filtros.programa) || TODOS}
        onChange={(valor) => aoMudar({ programa: valor && valor !== TODOS ? valor : '' })}
      />
      <Select
        aria-label="Usuário"
        size="xs"
        w={240}
        allowDeselect={false}
        searchable
        data={[
          { value: TODOS, label: 'Todos os usuários' },
          ...opcoes.usuarios.map((u) => ({ value: u.uid, label: u.email ?? u.uid })),
        ]}
        value={filtros.usuario || TODOS}
        onChange={(valor) => aoMudar({ usuario: valor && valor !== TODOS ? valor : '' })}
      />
      <TextInput type="date" aria-label="De" size="xs" value={filtros.de} onChange={(e) => aoMudar({ de: e.currentTarget.value })} />
      <TextInput type="date" aria-label="Até" size="xs" value={filtros.ate} onChange={(e) => aoMudar({ ate: e.currentTarget.value })} />
    </Group>
  )
}

/** Logins por dia: barras em SVG, com a tabela logo abaixo para ler os números. */
function GraficoDeLogins({ dias }: { dias: DiaDeAcessos[] }) {
  const maximo = Math.max(1, ...dias.map((d) => d.acessos))
  const largura = 28
  const altura = 120
  return (
    <svg
      role="img"
      aria-label={`Logins por dia: ${dias.map((d) => `${diaCurto(d.dia)}, ${d.acessos}`).join('; ')}`}
      width={Math.max(dias.length * largura, largura)}
      height={altura + 20}
    >
      {dias.map((d, i) => {
        const h = (d.acessos / maximo) * altura
        return (
          <g key={d.dia}>
            <rect x={i * largura + 4} y={altura - h} width={largura - 8} height={h} fill={CORES.textoSecundario}>
              <title>{`${dataDeExibicao(d.dia)}: ${d.acessos} logins`}</title>
            </rect>
            <text x={i * largura + largura / 2} y={altura + 14} fontSize={9} textAnchor="middle" fill={CORES.textoSecundario}>
              {diaCurto(d.dia)}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

function Numero({ rotulo, valor }: { rotulo: string; valor: number | string }) {
  return (
    <Box>
      <Text size="xs" c={CORES.textoSecundario}>
        {rotulo}
      </Text>
      <Text size="xl" fw={600} style={NUMEROS}>
        {valor}
      </Text>
    </Box>
  )
}

/** Usuários ativos por semana ou por mês: cada pessoa conta uma vez no período. */
function TabelaDeAtivos({
  rotulo,
  coluna,
  periodos,
  nome,
}: {
  rotulo: string
  coluna: string
  periodos: AtivosNoPeriodo[]
  nome: (inicio: string) => string
}) {
  return (
    <Table aria-label={rotulo} highlightOnHover maw={260}>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{coluna}</Table.Th>
          <Table.Th ta="right">Usuários ativos</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {periodos.map((p) => (
          <Table.Tr key={p.inicio}>
            <Table.Td>{nome(p.inicio)}</Table.Td>
            <Table.Td ta="right" style={NUMEROS}>
              {p.usuarios_ativos}
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  )
}

function Acessos({ relatorio }: { relatorio: RelatorioDeAcessos }) {
  if (relatorio.por_dia.length === 0) return <Text size="sm">Nenhum acesso neste filtro.</Text>
  return (
    <Stack gap="md">
      <Group gap="xl">
        <Numero rotulo="Logins no período" valor={relatorio.total.acessos} />
        <Numero rotulo="Usuários ativos no período" valor={relatorio.total.usuarios_ativos} />
      </Group>
      <Box style={{ overflowX: 'auto' }}>
        <GraficoDeLogins dias={relatorio.por_dia} />
      </Box>
      <Table aria-label="Acessos por dia" highlightOnHover maw={520}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Dia</Table.Th>
            <Table.Th ta="right">Logins</Table.Th>
            <Table.Th ta="right">Usuários ativos</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {relatorio.por_dia.map((d) => (
            <Table.Tr key={d.dia}>
              <Table.Td>{dataDeExibicao(d.dia)}</Table.Td>
              <Table.Td ta="right" style={NUMEROS}>{d.acessos}</Table.Td>
              <Table.Td ta="right" style={NUMEROS}>{d.usuarios_ativos}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Group gap="xl" align="flex-start">
        <TabelaDeAtivos
          rotulo="Usuários ativos por semana"
          coluna="Semana de"
          periodos={relatorio.por_semana}
          nome={dataDeExibicao}
        />
        <TabelaDeAtivos rotulo="Usuários ativos por mês" coluna="Mês" periodos={relatorio.por_mes} nome={mesCurto} />
      </Group>
      <Table aria-label="Acessos por usuário" highlightOnHover maw={760}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Usuário</Table.Th>
            <Table.Th ta="right">Logins</Table.Th>
            <Table.Th ta="right">Dias ativos</Table.Th>
            <Table.Th>Último login</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {relatorio.por_usuario.map((u) => (
            <Table.Tr key={u.uid}>
              <Table.Td>{u.email ?? u.uid}</Table.Td>
              <Table.Td ta="right" style={NUMEROS}>{u.acessos}</Table.Td>
              <Table.Td ta="right" style={NUMEROS}>{u.dias_ativos}</Table.Td>
              <Table.Td>{u.ultimo_acesso ? dataEHora(u.ultimo_acesso) : '—'}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  )
}

const tempoMedio = (n: NumerosDeVideos) => (n.tempo_medio_s === null ? '—' : duracaoLegivel(n.tempo_medio_s * 1000))

/** `quem_tipo` sistema aparece com o nome da chave e o rótulo "(sistema)"; pessoa sem e-mail, com o uid. */
const nomeDeQuem = (q: { quem_tipo: string; quem_id: string; email: string | null }) =>
  q.quem_tipo === 'sistema' ? `${q.quem_id} (sistema)` : (q.email ?? q.quem_id)

function ColunasDeVideos() {
  return (
    <>
      <Table.Th ta="right">Enviados</Table.Th>
      <Table.Th ta="right">Concluídos</Table.Th>
      <Table.Th ta="right">Com falha</Table.Th>
      <Table.Th ta="right">Horas de vídeo</Table.Th>
      <Table.Th ta="right">Tempo médio de processamento</Table.Th>
    </>
  )
}

function CelulasDeVideos({ n }: { n: NumerosDeVideos }) {
  return (
    <>
      <Table.Td ta="right" style={NUMEROS}>{n.enviados}</Table.Td>
      <Table.Td ta="right" style={NUMEROS}>{n.concluidos}</Table.Td>
      <Table.Td ta="right" style={NUMEROS}>{n.falhos}</Table.Td>
      <Table.Td ta="right" style={NUMEROS}>{horasDeVideo(n.horas_concluidas)}</Table.Td>
      <Table.Td ta="right" style={NUMEROS}>{tempoMedio(n)}</Table.Td>
    </>
  )
}

function TabelaDeVideos({
  rotulo,
  primeira,
  linhas,
}: {
  rotulo: string
  primeira: string
  linhas: { chave: string; nome: string; numeros: NumerosDeVideos }[]
}) {
  return (
    <Table aria-label={rotulo} highlightOnHover maw={900}>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{primeira}</Table.Th>
          <ColunasDeVideos />
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {linhas.map((l) => (
          <Table.Tr key={l.chave}>
            <Table.Td>{l.nome}</Table.Td>
            <CelulasDeVideos n={l.numeros} />
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  )
}

function Videos({ relatorio }: { relatorio: RelatorioDeVideos }) {
  if (relatorio.por_dia.length === 0) return <Text size="sm">Nenhum vídeo neste filtro.</Text>
  const t = relatorio.total
  return (
    <Stack gap="md">
      <Group gap="xl">
        <Numero rotulo="Enviados" valor={t.enviados} />
        <Numero rotulo="Concluídos" valor={t.concluidos} />
        <Numero rotulo="Com falha" valor={t.falhos} />
        <Numero rotulo="Horas de vídeo concluídas" valor={horasDeVideo(t.horas_concluidas)} />
        <Numero rotulo="Tempo médio de processamento" valor={tempoMedio(t)} />
      </Group>
      <TabelaDeVideos
        rotulo="Vídeos por dia"
        primeira="Dia"
        linhas={relatorio.por_dia.map((d) => ({ chave: d.dia, nome: dataDeExibicao(d.dia), numeros: d }))}
      />
      {relatorio.por_programa.length > 0 && (
        <TabelaDeVideos
          rotulo="Vídeos por programa"
          primeira="Programa"
          linhas={relatorio.por_programa.map((p) => ({ chave: p.programa, nome: p.programa, numeros: p }))}
        />
      )}
      {relatorio.por_usuario.length > 0 && (
        <TabelaDeVideos
          rotulo="Vídeos por usuário"
          primeira="Usuário"
          linhas={relatorio.por_usuario.map((u) => ({
            chave: `${u.quem_tipo}:${u.quem_id}`,
            nome: nomeDeQuem(u),
            numeros: u,
          }))}
        />
      )}
    </Stack>
  )
}

const quantos = (n: number | null) => (n === null ? '—' : n)

function Buscas({ relatorio }: { relatorio: RelatorioDeBuscas }) {
  if (relatorio.por_dia.length === 0) return <Text size="sm">Nenhuma busca neste filtro.</Text>
  const t = relatorio.total
  return (
    <Stack gap="md">
      <Group gap="xl">
        <Numero rotulo="Buscas" valor={t.buscas} />
        <Numero rotulo="Usuários que buscam" valor={quantos(t.usuarios_que_buscam)} />
        <Numero rotulo="Buscas sem resultado" valor={t.sem_resultado} />
      </Group>
      <Table aria-label="Buscas por dia" highlightOnHover maw={640}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Dia</Table.Th>
            <Table.Th ta="right">Buscas</Table.Th>
            <Table.Th ta="right">Usuários que buscam</Table.Th>
            <Table.Th ta="right">Sem resultado</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {relatorio.por_dia.map((d: DiaDeBuscas) => (
            <Table.Tr key={d.dia}>
              <Table.Td>{dataDeExibicao(d.dia)}</Table.Td>
              <Table.Td ta="right" style={NUMEROS}>{d.buscas}</Table.Td>
              <Table.Td ta="right" style={NUMEROS}>{quantos(d.usuarios_que_buscam)}</Table.Td>
              <Table.Td ta="right" style={NUMEROS}>{d.sem_resultado}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {relatorio.por_usuario.length > 0 && (
        <Table aria-label="Buscas por usuário" highlightOnHover maw={640}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Usuário</Table.Th>
              <Table.Th ta="right">Buscas</Table.Th>
              <Table.Th ta="right">Sem resultado</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {relatorio.por_usuario.map((u) => (
              <Table.Tr key={`${u.quem_tipo}:${u.quem_id}`}>
                <Table.Td>{nomeDeQuem(u)}</Table.Td>
                <Table.Td ta="right" style={NUMEROS}>{u.buscas}</Table.Td>
                <Table.Td ta="right" style={NUMEROS}>{u.sem_resultado}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  )
}

/**
 * Uma aba: busca o relatório, mostra o "Baixar CSV" e os avisos. `bloqueio` é o motivo de não
 * chamar a API (período invertido, filtros que não se combinam); `vazio` desliga o CSV.
 */
function AbaDoRelatorio<T>({
  buscar,
  arquivo,
  baixar,
  bloqueio,
  vazio,
  nota,
  mostrar,
}: {
  buscar: () => Promise<T>
  arquivo: string
  baixar: () => Promise<Blob>
  bloqueio: { mensagem: string; codigo: string } | null
  vazio: (relatorio: T) => boolean
  nota: ReactNode
  mostrar: (relatorio: T) => ReactNode
}) {
  const buscarSeLiberado = useCallback(
    () => (bloqueio ? new Promise<T>(() => undefined) : buscar()),
    [bloqueio, buscar],
  )
  const { carga, carregar } = useRelatorio(buscarSeLiberado)
  const csv = useBaixarCsv(arquivo, baixar)
  return (
    <Stack gap="md">
      <Group>
        <BotaoDeCsv
          desligado={bloqueio !== null || carga.tipo !== 'pronta' || vazio(carga.relatorio)}
          aoClicar={() => void csv.baixar()}
        />
      </Group>
      <AlertaDoCsv falhou={csv.falhou} />
      <Text size="xs" c={CORES.textoSecundario}>
        {nota}
      </Text>
      {bloqueio && <AlertaDeErro mensagem={bloqueio.mensagem} codigo={bloqueio.codigo} />}
      {!bloqueio && carga.tipo === 'carregando' && <Loader role="status" aria-label="Montando o painel" size="sm" />}
      {!bloqueio && <ErroDoRelatorio carga={carga} aoTentar={carregar} />}
      {!bloqueio && carga.tipo === 'pronta' && mostrar(carga.relatorio)}
    </Stack>
  )
}

const NOTA_DO_DIA = 'O dia é o de São Paulo; os números se atualizam a cada 10 minutos.'

/** A área do painel da diretoria: filtros no topo, abas e "Baixar CSV" em cada aba. */
export default function PainelDaDiretoria({
  api,
  aba,
  filtros,
}: {
  api: ClienteDaApi
  aba: AbaDoPainel
  filtros: FiltrosDoPainel
}) {
  const periodo = periodoInvertido(filtros)
    ? { mensagem: 'O período começa depois de terminar.', codigo: 'periodo' }
    : null
  const juntos =
    aba !== 'acessos' && programaEUsuarioJuntos(filtros)
      ? { mensagem: 'Escolha o programa ou o usuário, não os dois.', codigo: 'filtros' }
      : null
  const bloqueio = periodo ?? juntos

  function mudar(parte: Partial<FiltrosDoPainel>) {
    navegar(enderecoDoPainel(aba, { ...filtros, ...parte }), { substituir: true })
  }

  return (
    <Stack gap="md" maw={1100}>
      <Title order={2} size="h3">
        Painel da diretoria
      </Title>
      <Filtros api={api} filtros={filtros} comPrograma={aba !== 'acessos'} aoMudar={mudar} />
      <Tabs
        value={aba}
        keepMounted={false}
        onChange={(valor) => valor && navegar(enderecoDoPainel(valor as AbaDoPainel, filtros), { substituir: true })}
      >
        <Tabs.List aria-label="Abas do painel">
          {ABAS_DO_PAINEL.map((a) => (
            <Tabs.Tab key={a.chave} value={a.chave}>
              {a.rotulo}
            </Tabs.Tab>
          ))}
        </Tabs.List>
        <Tabs.Panel value="acessos" pt="md">
          <AbaDoRelatorio
            buscar={useCallback(() => api.acessosDoPainel(filtros), [api, filtros])}
            arquivo="acessos.csv"
            baixar={() => api.acessosDoPainelEmCsv(filtros)}
            bloqueio={periodo}
            vazio={(r: RelatorioDeAcessos) => r.por_dia.length === 0}
            nota={`Logins não têm programa: o filtro de programa vale para as outras abas. ${NOTA_DO_DIA} A primeira e a última semana ou mês contam só os dias do período.`}
            mostrar={(r) => <Acessos relatorio={r} />}
          />
        </Tabs.Panel>
        <Tabs.Panel value="videos" pt="md">
          <AbaDoRelatorio
            buscar={useCallback(() => api.videosDoPainel(filtros), [api, filtros])}
            arquivo="videos.csv"
            baixar={() => api.videosDoPainelEmCsv(filtros)}
            bloqueio={bloqueio}
            vazio={(r: RelatorioDeVideos) => r.por_dia.length === 0}
            nota={`Os vídeos de sistemas entram junto com os das pessoas. O tempo de processamento é o dos concluídos, do registro ao fim. Com um programa escolhido não há quebra por usuário, e com um usuário não há por programa. ${NOTA_DO_DIA}`}
            mostrar={(r) => <Videos relatorio={r} />}
          />
        </Tabs.Panel>
        <Tabs.Panel value="buscas" pt="md">
          <AbaDoRelatorio
            buscar={useCallback(() => api.buscasDoPainel(filtros), [api, filtros])}
            arquivo="buscas.csv"
            baixar={() => api.buscasDoPainelEmCsv(filtros)}
            bloqueio={bloqueio}
            vazio={(r: RelatorioDeBuscas) => r.por_dia.length === 0}
            nota={`Busca sem resultado é a que não trouxe nenhum vídeo; as feitas antes de o sistema contar isso não entram nela. A busca só tem programa quando foi filtrada por ele, e então não se sabe quem buscou. ${NOTA_DO_DIA}`}
            mostrar={(r) => <Buscas relatorio={r} />}
          />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
