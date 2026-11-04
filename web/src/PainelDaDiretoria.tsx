import { Box, Group, Loader, Select, Stack, Table, Tabs, Text, TextInput, Title } from '@mantine/core'
import { useCallback, useEffect, useState } from 'react'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import type { ClienteDaApi } from './api.ts'
import { dataEHora } from './jobs.ts'
import {
  ABAS_DO_PAINEL,
  diaCompleto,
  diaCurto,
  periodoInvertidoNoPainel,
  type AbaDoPainel,
  type DiaDeAcessos,
  type FiltrosDoPainel,
  type OpcoesDoPainel,
  type RelatorioDeAcessos,
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
        value={filtros.programa || TODOS}
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
            <rect x={i * largura + 4} y={altura - h} width={largura - 8} height={h} fill={CORES.foco}>
              <title>{`${diaCompleto(d.dia)}: ${d.acessos} logins`}</title>
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

function Numero({ rotulo, valor }: { rotulo: string; valor: number }) {
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

function Acessos({ relatorio }: { relatorio: RelatorioDeAcessos }) {
  if (relatorio.por_dia.length === 0) return <Text size="sm">Nenhum acesso neste filtro.</Text>
  return (
    <Stack gap="md">
      <Group gap="xl">
        <Numero rotulo="Logins no período" valor={relatorio.total.acessos} />
        <Numero rotulo="Usuários ativos no período" valor={relatorio.total.usuarios_ativos} />
      </Group>
      <GraficoDeLogins dias={relatorio.por_dia} />
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
              <Table.Td>{diaCompleto(d.dia)}</Table.Td>
              <Table.Td ta="right" style={NUMEROS}>{d.acessos}</Table.Td>
              <Table.Td ta="right" style={NUMEROS}>{d.usuarios_ativos}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
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
  const invertido = periodoInvertidoNoPainel(filtros)
  const buscar = useCallback(
    () => (invertido ? new Promise<RelatorioDeAcessos>(() => undefined) : api.acessosDoPainel(filtros)),
    [api, filtros, invertido],
  )
  const { carga, carregar } = useRelatorio(buscar)
  const csv = useBaixarCsv('acessos.csv', () => api.acessosDoPainelEmCsv(filtros))

  function mudar(parte: Partial<FiltrosDoPainel>) {
    navegar(enderecoDoPainel(aba, { ...filtros, ...parte }), { substituir: true })
  }

  return (
    <Stack gap="md" maw={1100}>
      <Title order={2} size="h3">
        Painel da diretoria
      </Title>
      <Filtros api={api} filtros={filtros} comPrograma={false} aoMudar={mudar} />
      <Tabs
        value={aba}
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
          <Stack gap="md">
            <Group>
              <BotaoDeCsv
                desligado={invertido || carga.tipo !== 'pronta' || carga.relatorio.por_dia.length === 0}
                aoClicar={() => void csv.baixar()}
              />
            </Group>
            <AlertaDoCsv falhou={csv.falhou} />
            <Text size="xs" c={CORES.textoSecundario}>
              Logins não têm programa: o filtro de programa vale para as outras abas. O dia é o de São Paulo; os números
              se atualizam a cada 10 minutos.
            </Text>
            {invertido && <AlertaDeErro mensagem="O período começa depois de terminar." codigo="periodo" />}
            {!invertido && carga.tipo === 'carregando' && <Loader role="status" aria-label="Montando o painel" size="sm" />}
            {!invertido && <ErroDoRelatorio carga={carga} aoTentar={carregar} />}
            {!invertido && carga.tipo === 'pronta' && <Acessos relatorio={carga.relatorio} />}
          </Stack>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
