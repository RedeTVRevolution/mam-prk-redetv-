import { Button, Group, Loader, Select, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { IconChevronDown, IconChevronRight, IconDownload } from '@tabler/icons-react'
import { Fragment, useCallback, useEffect, useState } from 'react'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import { codigoDoErro, PedidoInvalido, SessaoExpirada, type ClienteDaApi } from './api.ts'
import { baixarArquivo } from './baixar.ts'
import { Link } from './Link.tsx'
import { enderecoDoTempoDeTela, enderecoDoVideo, navegar } from './rotas.ts'
import { CORES } from './tema.ts'
import { duracaoLegivel, type FiltrosDoRelatorio, type RelatorioDeTempoDeTela } from './tempoDeTela.ts'

const TODOS = '__todos__'
const NUMEROS = { fontVariantNumeric: 'tabular-nums' } as const

type Carga =
  | { tipo: 'carregando' }
  | { tipo: 'pronta'; relatorio: RelatorioDeTempoDeTela }
  | { tipo: 'erro'; mensagem: string; codigo: string }

/** "Relatórios › Tempo de tela": só aparições somam; as menções ficam em colunas à parte. */
export default function TempoDeTela({ api, filtros }: { api: ClienteDaApi; filtros: FiltrosDoRelatorio }) {
  const [carga, setCarga] = useState<Carga>({ tipo: 'carregando' })
  const [programas, setProgramas] = useState<string[]>([])
  const [aberta, setAberta] = useState<string | null>(null)
  const [erroDoCsv, setErroDoCsv] = useState(false)

  useEffect(() => {
    let atual = true
    api
      .programas()
      .then((lista) => atual && setProgramas(lista))
      .catch(() => undefined)
    return () => {
      atual = false
    }
  }, [api])

  const carregar = useCallback(() => {
    let atual = true
    setCarga({ tipo: 'carregando' })
    setAberta(null)
    api
      .tempoDeTela(filtros)
      .then((relatorio) => atual && setCarga({ tipo: 'pronta', relatorio }))
      .catch((erro: unknown) => {
        if (!atual || erro instanceof SessaoExpirada) return
        const mensagem =
          erro instanceof PedidoInvalido
            ? erro.message
            : 'Não foi possível montar o relatório agora. Tente de novo.'
        setCarga({ tipo: 'erro', mensagem, codigo: codigoDoErro(erro) })
      })
    return () => {
      atual = false
    }
  }, [api, filtros])

  // Busca na API, um sistema externo, sempre que os filtros do endereço mudam.
  // oxlint-disable-next-line react/set-state-in-effect
  useEffect(() => carregar(), [carregar])

  function mudar(parte: Partial<FiltrosDoRelatorio>) {
    navegar(enderecoDoTempoDeTela({ ...filtros, ...parte }), { substituir: true })
  }

  async function baixar() {
    setErroDoCsv(false)
    try {
      baixarArquivo('tempo-de-tela.csv', await api.tempoDeTelaEmCsv(filtros))
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setErroDoCsv(true)
    }
  }

  const pessoas = carga.tipo === 'pronta' ? carga.relatorio.pessoas : []
  return (
    <Stack gap="md" maw={1100}>
      <Title order={2} size="h3">
        Relatórios › Tempo de tela
      </Title>
      <Group gap="sm" align="flex-end" wrap="wrap">
        <Select
          aria-label="Programa"
          size="xs"
          w={200}
          allowDeselect={false}
          data={[{ value: TODOS, label: 'Todos os programas' }, ...programas]}
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
        <Button
          type="button"
          size="xs"
          variant="default"
          leftSection={<IconDownload size={14} aria-hidden />}
          disabled={carga.tipo !== 'pronta' || pessoas.length === 0}
          onClick={() => void baixar()}
        >
          Baixar CSV
        </Button>
      </Group>
      {erroDoCsv && <AlertaDeErro mensagem="Não foi possível baixar o CSV agora." codigo="csv" />}
      <Text size="xs" c={CORES.textoSecundario}>
        Só aparições somam tempo de tela. Menções na fala e no texto da tela são só contagem.
      </Text>
      {carga.tipo === 'carregando' && <Loader role="status" aria-label="Montando o relatório" size="sm" />}
      {carga.tipo === 'erro' && <AlertaDeErro mensagem={carga.mensagem} codigo={carga.codigo} aoTentar={carregar} />}
      {carga.tipo === 'pronta' && pessoas.length === 0 && (
        <Text size="sm">Nenhuma pessoa com aparição ou menção neste filtro.</Text>
      )}
      {carga.tipo === 'pronta' && pessoas.length > 0 && (
        <Table aria-label="Tempo de tela por pessoa" highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Pessoa</Table.Th>
              <Table.Th ta="right">Tempo de tela</Table.Th>
              <Table.Th ta="right">Vídeos</Table.Th>
              <Table.Th ta="right">Aparições</Table.Th>
              <Table.Th ta="right">Menções na fala</Table.Th>
              <Table.Th ta="right">Menções no texto</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {pessoas.map((p) => {
              const expandida = aberta === p.pessoa_id
              return (
                <Fragment key={p.pessoa_id}>
                  <Table.Tr>
                    <Table.Td>
                      <Button
                        type="button"
                        variant="subtle"
                        color="gray"
                        size="compact-sm"
                        aria-expanded={expandida}
                        leftSection={
                          expandida ? <IconChevronDown size={14} aria-hidden /> : <IconChevronRight size={14} aria-hidden />
                        }
                        onClick={() => setAberta(expandida ? null : p.pessoa_id)}
                      >
                        {p.nome}
                      </Button>
                    </Table.Td>
                    <Table.Td ta="right" style={NUMEROS}>
                      {duracaoLegivel(p.tempo_de_tela_ms)}
                    </Table.Td>
                    <Table.Td ta="right" style={NUMEROS}>{p.videos}</Table.Td>
                    <Table.Td ta="right" style={NUMEROS}>{p.aparicoes}</Table.Td>
                    <Table.Td ta="right" style={NUMEROS}>{p.mencoes_na_fala}</Table.Td>
                    <Table.Td ta="right" style={NUMEROS}>{p.mencoes_no_texto}</Table.Td>
                  </Table.Tr>
                  {expandida && (
                    <Table.Tr>
                      <Table.Td colSpan={6}>
                        <Table aria-label={`Vídeos de ${p.nome}`} withRowBorders={false}>
                          <Table.Tbody>
                            {p.por_video.map((v) => (
                              <Table.Tr key={v.job_id}>
                                <Table.Td>
                                  <Link para={enderecoDoVideo(v.job_id)}>{v.nome ?? v.job_id}</Link>
                                </Table.Td>
                                <Table.Td ta="right" style={NUMEROS}>
                                  {duracaoLegivel(v.tempo_de_tela_ms)}
                                </Table.Td>
                                <Table.Td ta="right" style={NUMEROS}>{v.aparicoes} aparições</Table.Td>
                                <Table.Td ta="right" style={NUMEROS}>{v.mencoes_na_fala} na fala</Table.Td>
                                <Table.Td ta="right" style={NUMEROS}>{v.mencoes_no_texto} no texto</Table.Td>
                              </Table.Tr>
                            ))}
                          </Table.Tbody>
                        </Table>
                      </Table.Td>
                    </Table.Tr>
                  )}
                </Fragment>
              )
            })}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  )
}
