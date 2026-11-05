import { Button, Loader, Select, Stack, Table, Text, Title } from '@mantine/core'
import { IconChevronDown, IconChevronRight } from '@tabler/icons-react'
import { Fragment, useCallback, useEffect, useState } from 'react'
import type { ClienteDaApi } from './api.ts'
import { MatrizDeCalor, RankingEmBarras } from './graficos.tsx'
import { Link } from './Link.tsx'
import { nomeDoTipo, TIPOS_DE_INSERCAO, type FiltrosDeMarcas, type RelatorioDeMarcas } from './marcas.ts'
import { AlertaDoCsv, BotaoDeCsv, ErroDoRelatorio, FiltrosDoPeriodo } from './relatorios.tsx'
import { enderecoDasMarcas, enderecoDoVideo, navegar } from './rotas.ts'
import { CORES } from './tema.ts'
import { useBaixarCsv, useRelatorio } from './useRelatorio.ts'
import { duracaoLegivel } from './tempoDeTela.ts'

const TODOS = '__todos__'
const NUMEROS = { fontVariantNumeric: 'tabular-nums' } as const

/** Quantas marcas o gráfico e a matriz mostram; a tabela tem todas. */
const NO_GRAFICO = 15

/** "Relatórios › Marcas": inserções, tempo somado e vídeos por marca, com o detalhe por tipo. */
export default function Marcas({ api, filtros }: { api: ClienteDaApi; filtros: FiltrosDeMarcas }) {
  const { carga, carregar } = useRelatorio(useCallback(() => api.marcas(filtros), [api, filtros]))
  // A marca aberta vale só para o relatório em que foi aberta: filtro novo fecha todas.
  const [aberta, setAberta] = useState<{ relatorio: RelatorioDeMarcas; marca: string; tipo?: string } | null>(null)
  const csv = useBaixarCsv('marcas.csv', () => api.marcasEmCsv(filtros))

  function mudar(parte: Partial<FiltrosDeMarcas>) {
    navegar(enderecoDasMarcas({ ...filtros, ...parte }), { substituir: true })
  }

  const marcas = carga.tipo === 'pronta' ? carga.relatorio.marcas : []
  const abertaAgora = carga.tipo === 'pronta' && aberta?.relatorio === carga.relatorio ? aberta : null
  const abertaMarca = abertaAgora?.marca ?? null
  useEffect(() => {
    if (abertaMarca) document.getElementById(`marca-${abertaMarca}`)?.scrollIntoView({ block: 'nearest' })
  }, [abertaMarca])
  const noGrafico = marcas.slice(0, NO_GRAFICO)
  const total = {
    insercoes: marcas.reduce((soma, m) => soma + m.insercoes, 0),
    tempo_ms: marcas.reduce((soma, m) => soma + m.tempo_ms, 0),
    videos: new Set(marcas.flatMap((m) => m.lista.map((i) => i.job_id))).size,
  }
  // Os tipos da API que a lista de tipos da tela não conhece entram no fim, com o código como nome.
  const tipos = [...new Set([...Object.keys(TIPOS_DE_INSERCAO), ...marcas.flatMap((m) => m.por_tipo.map((t) => t.tipo))])]
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
        <Stack gap="lg">
          <Text size="sm" style={NUMEROS}>
            {total.insercoes} {total.insercoes === 1 ? 'inserção' : 'inserções'} · {duracaoLegivel(total.tempo_ms)} ·{' '}
            {total.videos} {total.videos === 1 ? 'vídeo' : 'vídeos'}
          </Text>
          <RankingEmBarras
            rotulo="Marcas com mais tempo"
            escolhido={abertaMarca}
            aoEscolher={(marca) => setAberta({ relatorio: carga.relatorio, marca })}
            itens={noGrafico.map((m) => ({
              id: m.marca,
              nome: m.marca,
              valor: m.tempo_ms,
              texto: duracaoLegivel(m.tempo_ms),
              dica: [
                `Tempo ${duracaoLegivel(m.tempo_ms)}`,
                `${m.insercoes} ${m.insercoes === 1 ? 'inserção' : 'inserções'}`,
                `${m.videos} ${m.videos === 1 ? 'vídeo' : 'vídeos'}`,
              ],
            }))}
          />
          <MatrizDeCalor
            rotulo="Tempo por marca e tipo de inserção"
            tituloDaLinha="Marca"
            linhas={noGrafico.map((m) => m.marca)}
            colunas={tipos.map((id) => ({ id, nome: nomeDoTipo(id) }))}
            celulas={noGrafico.flatMap((m) =>
              m.por_tipo.map((t) => ({
                linha: m.marca,
                coluna: t.tipo,
                valor: t.tempo_ms,
                texto: duracaoLegivel(t.tempo_ms),
              })),
            )}
            aoEscolher={(marca, tipo) => setAberta({ relatorio: carga.relatorio, marca, tipo })}
          />
        </Stack>
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
              const expandida = abertaMarca === m.marca
              const lista = abertaAgora?.tipo ? m.lista.filter((i) => i.tipo === abertaAgora.tipo) : m.lista
              return (
                <Fragment key={m.marca}>
                  <Table.Tr id={`marca-${m.marca}`}>
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
                        {abertaAgora?.tipo && (
                          <Text size="xs" c={CORES.textoSecundario}>
                            Só {nomeDoTipo(abertaAgora.tipo)}
                          </Text>
                        )}
                        <Table aria-label={`Inserções de ${m.marca}`} withRowBorders={false}>
                          <Table.Tbody>
                            {lista.map((i, n) => (
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
