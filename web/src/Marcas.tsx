import { Button, Loader, Select, Stack, Table, Text, Title } from '@mantine/core'
import { IconChevronDown, IconChevronRight } from '@tabler/icons-react'
import { Fragment, useCallback, useState } from 'react'
import type { ClienteDaApi } from './api.ts'
import { Link } from './Link.tsx'
import { nomeDoTipo, TIPOS_DE_INSERCAO, type FiltrosDeMarcas, type RelatorioDeMarcas } from './marcas.ts'
import { AlertaDoCsv, BotaoDeCsv, ErroDoRelatorio, FiltrosDoPeriodo } from './relatorios.tsx'
import { enderecoDasMarcas, enderecoDoVideo, navegar } from './rotas.ts'
import { CORES } from './tema.ts'
import { useBaixarCsv, useRelatorio } from './useRelatorio.ts'
import { duracaoLegivel } from './tempoDeTela.ts'

const TODOS = '__todos__'
const NUMEROS = { fontVariantNumeric: 'tabular-nums' } as const

/** "Relatórios › Marcas": inserções, tempo somado e vídeos por marca, com o detalhe por tipo. */
export default function Marcas({ api, filtros }: { api: ClienteDaApi; filtros: FiltrosDeMarcas }) {
  const { carga, carregar } = useRelatorio(useCallback(() => api.marcas(filtros), [api, filtros]))
  // A marca aberta vale só para o relatório em que foi aberta: filtro novo fecha todas.
  const [aberta, setAberta] = useState<{ relatorio: RelatorioDeMarcas; marca: string } | null>(null)
  const csv = useBaixarCsv('marcas.csv', () => api.marcasEmCsv(filtros))

  function mudar(parte: Partial<FiltrosDeMarcas>) {
    navegar(enderecoDasMarcas({ ...filtros, ...parte }), { substituir: true })
  }

  const marcas = carga.tipo === 'pronta' ? carga.relatorio.marcas : []
  return (
    <Stack gap="md" maw={1100}>
      <Title order={2} size="h3">
        Relatórios › Marcas
      </Title>
      <FiltrosDoPeriodo api={api} filtros={filtros} aoMudar={mudar}>
        <Select
          aria-label="Tipo de inserção"
          size="xs"
          w={220}
          allowDeselect={false}
          data={[
            { value: TODOS, label: 'Todos os tipos' },
            ...Object.entries(TIPOS_DE_INSERCAO).map(([value, label]) => ({ value, label })),
          ]}
          value={filtros.tipo || TODOS}
          onChange={(valor) => mudar({ tipo: valor && valor !== TODOS ? valor : '' })}
        />
        <BotaoDeCsv desligado={carga.tipo !== 'pronta' || marcas.length === 0} aoClicar={() => void csv.baixar()} />
      </FiltrosDoPeriodo>
      <AlertaDoCsv falhou={csv.falhou} />
      <Text size="xs" c={CORES.textoSecundario}>
        O tempo é a soma das durações das inserções; inserções que se sobrepõem contam cada uma.
      </Text>
      {carga.tipo === 'carregando' && <Loader role="status" aria-label="Montando o relatório" size="sm" />}
      <ErroDoRelatorio carga={carga} aoTentar={carregar} />
      {carga.tipo === 'pronta' && marcas.length === 0 && (
        <Text size="sm">Nenhuma inserção de marca neste filtro.</Text>
      )}
      {carga.tipo === 'pronta' && marcas.length > 0 && (
        <Table aria-label="Inserções por marca" highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Marca</Table.Th>
              <Table.Th ta="right">Inserções</Table.Th>
              <Table.Th ta="right">Tempo</Table.Th>
              <Table.Th ta="right">Vídeos</Table.Th>
              <Table.Th>Por tipo</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {marcas.map((m) => {
              const expandida = aberta?.relatorio === carga.relatorio && aberta.marca === m.marca
              return (
                <Fragment key={m.marca}>
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
                        onClick={() => setAberta(expandida ? null : { relatorio: carga.relatorio, marca: m.marca })}
                      >
                        {m.marca}
                      </Button>
                    </Table.Td>
                    <Table.Td ta="right" style={NUMEROS}>{m.insercoes}</Table.Td>
                    <Table.Td ta="right" style={NUMEROS}>{duracaoLegivel(m.tempo_ms)}</Table.Td>
                    <Table.Td ta="right" style={NUMEROS}>{m.videos}</Table.Td>
                    <Table.Td>
                      <Text size="xs" c={CORES.textoSecundario}>
                        {m.por_tipo
                          .map((t) => `${nomeDoTipo(t.tipo)}: ${t.insercoes} (${duracaoLegivel(t.tempo_ms)})`)
                          .join(' · ')}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                  {expandida && (
                    <Table.Tr>
                      <Table.Td colSpan={5}>
                        <Table aria-label={`Inserções de ${m.marca}`} withRowBorders={false}>
                          <Table.Tbody>
                            {m.lista.map((i, n) => (
                              // Duas inserções iguais no mesmo vídeo podem existir: a posição desempata.
                              <Table.Tr key={`${n}-${i.job_id}-${i.inicio_ms}`}>
                                <Table.Td>
                                  <Link para={enderecoDoVideo(i.job_id, i.inicio_ms / 1000)}>{i.nome ?? i.job_id}</Link>
                                </Table.Td>
                                <Table.Td>{nomeDoTipo(i.tipo)}</Table.Td>
                                <Table.Td ta="right" style={NUMEROS}>
                                  {duracaoLegivel(i.inicio_ms)} – {duracaoLegivel(i.fim_ms)}
                                </Table.Td>
                                <Table.Td ta="right" style={NUMEROS}>{duracaoLegivel(i.fim_ms - i.inicio_ms)}</Table.Td>
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
