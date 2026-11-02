import { Button, Loader, Stack, Table, Text, Title } from '@mantine/core'
import { IconChevronDown, IconChevronRight } from '@tabler/icons-react'
import { Fragment, useCallback, useState } from 'react'
import type { ClienteDaApi } from './api.ts'
import { Link } from './Link.tsx'
import { AlertaDoCsv, BotaoDeCsv, ErroDoRelatorio, FiltrosDoPeriodo } from './relatorios.tsx'
import { enderecoDoTempoDeTela, enderecoDoVideo, navegar } from './rotas.ts'
import { CORES } from './tema.ts'
import { useBaixarCsv, useRelatorio } from './useRelatorio.ts'
import { duracaoLegivel, type FiltrosDoRelatorio, type RelatorioDeTempoDeTela } from './tempoDeTela.ts'

const NUMEROS = { fontVariantNumeric: 'tabular-nums' } as const

/** "Relatórios › Tempo de tela": só aparições somam; as menções ficam em colunas à parte. */
export default function TempoDeTela({ api, filtros }: { api: ClienteDaApi; filtros: FiltrosDoRelatorio }) {
  const { carga, carregar } = useRelatorio(useCallback(() => api.tempoDeTela(filtros), [api, filtros]))
  // A linha aberta vale só para o relatório em que foi aberta: filtro novo fecha todas.
  const [aberta, setAberta] = useState<{ relatorio: RelatorioDeTempoDeTela; id: string } | null>(null)
  const csv = useBaixarCsv('tempo-de-tela.csv', () => api.tempoDeTelaEmCsv(filtros))

  function mudar(parte: Partial<FiltrosDoRelatorio>) {
    navegar(enderecoDoTempoDeTela({ ...filtros, ...parte }), { substituir: true })
  }

  const pessoas = carga.tipo === 'pronta' ? carga.relatorio.pessoas : []
  return (
    <Stack gap="md" maw={1100}>
      <Title order={2} size="h3">
        Relatórios › Tempo de tela
      </Title>
      <FiltrosDoPeriodo api={api} filtros={filtros} aoMudar={mudar}>
        <BotaoDeCsv desligado={carga.tipo !== 'pronta' || pessoas.length === 0} aoClicar={() => void csv.baixar()} />
      </FiltrosDoPeriodo>
      <AlertaDoCsv falhou={csv.falhou} />
      <Text size="xs" c={CORES.textoSecundario}>
        Só aparições somam tempo de tela. Menções na fala e no texto da tela são só contagem.
      </Text>
      {carga.tipo === 'carregando' && <Loader role="status" aria-label="Montando o relatório" size="sm" />}
      <ErroDoRelatorio carga={carga} aoTentar={carregar} />
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
              const expandida = aberta?.relatorio === carga.relatorio && aberta.id === p.pessoa_id
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
                        onClick={() => setAberta(expandida ? null : { relatorio: carga.relatorio, id: p.pessoa_id })}
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
