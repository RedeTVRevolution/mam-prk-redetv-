import { BarChart } from '@mantine/charts'
import { Box, Group, Stack, Table, Text, UnstyledButton } from '@mantine/core'
import { fundoDaCelula } from './escalaDaMatriz.ts'
import { CORES } from './tema.ts'

// Os gráficos dos relatórios (docs/design/sistema-visual.md, "Gráficos"): uma cor por série, rótulo
// direto no lugar de eixo, sem grade nem legenda. A tabela de cada tela continua sendo a forma
// acessível de ler os números (P8).

const NUMEROS = { fontVariantNumeric: 'tabular-nums' } as const

/** Altura da barra e vão entre barras, em px (base de 4). */
const BARRA = 20
const VAO = 8
const LARGURA_DO_NOME = 150

export interface ItemDoRanking {
  id: string
  nome: string
  valor: number
  /** O valor como a tela o escreve (a ponta da barra). */
  texto: string
  /** As linhas da dica, abaixo do nome. */
  dica: string[]
}

function DicaDoRanking({ active, payload }: { active?: boolean; payload?: readonly { payload?: unknown }[] }) {
  const item = payload?.[0]?.payload as { item?: ItemDoRanking } | undefined
  if (!active || !item?.item) return null
  return (
    <Box bg={CORES.elevada} p="sm" style={{ border: `1px solid ${CORES.borda}`, borderRadius: 4 }}>
      <Text fw={600} size="sm">
        {item.item.nome}
      </Text>
      {item.item.dica.map((linha) => (
        <Text key={linha} size="xs" c={CORES.textoSecundario} style={NUMEROS}>
          {linha}
        </Text>
      ))}
    </Box>
  )
}

/**
 * Barras horizontais de uma série só: todas em `foco`, a escolhida e a que está sob o ponteiro em
 * `focoTexto`. Clicar numa barra chama `aoEscolher`.
 */
export function RankingEmBarras({
  rotulo,
  itens,
  escolhido,
  aoEscolher,
}: {
  rotulo: string
  itens: ItemDoRanking[]
  escolhido: string | null
  aoEscolher: (id: string) => void
}) {
  // A barra escolhida é a segunda série empilhada: assim ganha a cor sem cor por barra.
  const dados = itens.map((item) => ({
    nome: item.nome,
    id: item.id,
    item,
    valor: item.id === escolhido ? 0 : item.valor,
    escolhida: item.id === escolhido ? item.valor : 0,
    // O rótulo de cada série lê o seu próprio texto: o da série vazia fica em branco.
    textoDoValor: item.id === escolhido ? '' : item.texto,
    textoDaEscolhida: item.id === escolhido ? item.texto : '',
  }))
  return (
    <Box role="img" aria-label={rotulo}>
      <BarChart
        h={itens.length * (BARRA + VAO)}
        data={dados}
        dataKey="nome"
        orientation="vertical"
        series={[
          { name: 'valor', color: CORES.foco, stackId: 'barra' },
          { name: 'escolhida', color: CORES.focoTexto, stackId: 'barra' },
        ]}
        withXAxis={false}
        gridAxis="none"
        tickLine="none"
        withLegend={false}
        withBarValueLabel
        barLabelColor={CORES.textoSecundario}
        valueLabelProps={(serie) => ({
          position: 'right',
          fontSize: 13,
          style: NUMEROS,
          formatter: (texto: unknown) => String(texto ?? ''),
          dataKey: serie.name === 'valor' ? 'textoDoValor' : 'textoDaEscolhida',
        })}
        yAxisProps={{ width: LARGURA_DO_NOME, tick: { fontSize: 13, fill: CORES.texto }, axisLine: false }}
        barChartProps={{ margin: { top: 0, right: 80, bottom: 0, left: 0 }, barCategoryGap: VAO }}
        barProps={{
          barSize: BARRA,
          radius: [0, 2, 2, 0],
          isAnimationActive: false,
          activeBar: { fill: CORES.focoTexto },
          cursor: 'pointer',
          onClick: (d: { id?: string }) => d.id && aoEscolher(d.id),
        }}
        cursorFill={CORES.elevada}
        tooltipAnimationDuration={150}
        tooltipProps={{ content: (p) => <DicaDoRanking active={p.active} payload={p.payload} /> }}
      />
    </Box>
  )
}

export interface FatiaDaDivisao {
  nome: string
  valor: number
  cor: string
}

/** A divisão de um total em fatias numa faixa só, com a contagem escrita embaixo de cada nome. */
export function DivisaoEmFaixa({ rotulo, fatias }: { rotulo: string; fatias: FatiaDaDivisao[] }) {
  const total = fatias.reduce((soma, f) => soma + f.valor, 0)
  return (
    <Stack gap="xs" role="img" aria-label={rotulo}>
      <Group gap={2} wrap="nowrap" h={BARRA}>
        {total === 0 && <Box h={BARRA} w="100%" style={{ border: `1px solid ${CORES.borda}`, borderRadius: 2 }} />}
        {fatias
          .filter((f) => f.valor > 0)
          .map((f) => (
            <Box key={f.nome} h={BARRA} bg={f.cor} style={{ flexGrow: f.valor, flexBasis: 0, borderRadius: 2 }} />
          ))}
      </Group>
      <Group gap="lg">
        {fatias.map((f) => (
          <Group key={f.nome} gap="xs">
            <Box w={10} h={10} bg={f.cor} style={{ borderRadius: 2 }} aria-hidden />
            <Text size="xs" c={CORES.textoSecundario}>
              {f.nome}
            </Text>
            <Text size="xs" fw={600} style={NUMEROS}>
              {f.valor}
            </Text>
          </Group>
        ))}
      </Group>
    </Stack>
  )
}

export interface CelulaDaMatriz {
  linha: string
  coluna: string
  valor: number
  texto: string
}

/**
 * Uma tabela de linhas por colunas com o fundo em `foco` conforme o valor. Coluna sem nenhum valor
 * some. Clicar numa célula com valor chama `aoEscolher`.
 */
export function MatrizDeCalor({
  rotulo,
  tituloDaLinha,
  linhas,
  colunas,
  celulas,
  aoEscolher,
}: {
  rotulo: string
  tituloDaLinha: string
  linhas: string[]
  colunas: { id: string; nome: string }[]
  celulas: CelulaDaMatriz[]
  aoEscolher: (linha: string, coluna: string) => void
}) {
  const chave = (l: string, c: string) => JSON.stringify([l, c])
  const porChave = new Map(celulas.map((c) => [chave(c.linha, c.coluna), c]))
  const visiveis = colunas.filter((c) => celulas.some((x) => x.coluna === c.id && x.valor > 0))
  const maximo = Math.max(0, ...celulas.map((c) => c.valor))
  return (
    <Table aria-label={rotulo} withRowBorders={false} withColumnBorders>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{tituloDaLinha}</Table.Th>
          {visiveis.map((c) => (
            <Table.Th key={c.id} ta="right">
              {c.nome}
            </Table.Th>
          ))}
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {linhas.map((linha) => (
          <Table.Tr key={linha}>
            <Table.Td>{linha}</Table.Td>
            {visiveis.map((c) => {
              const celula = porChave.get(chave(linha, c.id))
              const valor = celula?.valor ?? 0
              return (
                <Table.Td
                  key={c.id}
                  ta="right"
                  style={{ ...NUMEROS, background: fundoDaCelula(valor, maximo), padding: 0 }}
                >
                  {celula && valor > 0 ? (
                    <UnstyledButton
                      type="button"
                      w="100%"
                      py={6}
                      px="sm"
                      ta="right"
                      aria-label={`${linha}, ${c.nome}: ${celula.texto}`}
                      onClick={() => aoEscolher(linha, c.id)}
                    >
                      {celula.texto}
                    </UnstyledButton>
                  ) : (
                    <Text component="span" size="sm" c={CORES.textoDesabilitado} px="sm">
                      –
                    </Text>
                  )}
                </Table.Td>
              )
            })}
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  )
}
