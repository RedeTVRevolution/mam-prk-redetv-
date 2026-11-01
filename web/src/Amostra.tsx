import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Chip,
  Code,
  Group,
  Kbd,
  Loader,
  Menu,
  Modal,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
  UnstyledButton,
} from '@mantine/core'
import {
  IconAlertTriangle,
  IconArrowDown,
  IconDots,
  IconDownload,
  IconHistory,
  IconPlayerPlay,
  IconSearch,
  IconX,
} from '@tabler/icons-react'
import { useState, type CSSProperties, type ReactNode } from 'react'
import { tempo as tempoEmMs } from './linhaDoTempo.ts'
import {
  contraste,
  CORES,
  CORES_DE_OCORRENCIA,
  ESTADOS_DO_JOB,
  HACHURADO,
  type EstadoDoJob,
  type TipoDeOcorrencia,
} from './tema.ts'

// A página de amostra do sistema visual (docs/design/sistema-visual.md): abre em /amostra,
// sem login, e só usa os dados fixos daqui. Não chama a API.

type CampoProps = { error?: string; disabled?: boolean; styles?: { input: CSSProperties } }
type ChipProps = { defaultChecked?: boolean; disabled?: boolean; styles?: { label: CSSProperties } }

const NUMEROS: CSSProperties = { fontVariantNumeric: 'tabular-nums' }
// Hover e foco desenhados parados, para avaliar sem passar o mouse.
const ANEL: CSSProperties = { outline: `2px solid ${CORES.foco}`, outlineOffset: 2 }
// Item selecionado: o azul de foco a 16% (0x29), sobre a superfície.
const SELECIONADO = `${CORES.foco}29`

/** Os tempos da amostra estão em segundos. */
const tempo = (s: number): string => tempoEmMs(s * 1000)

const razao = (cor: string, fundo: string) =>
  `${contraste(cor, fundo).toFixed(1).replace('.', ',')}:1`

function Secao({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <Box component="section" aria-label={titulo}>
      <Stack gap="md">
        <Title order={2}>{titulo}</Title>
        {children}
      </Stack>
    </Box>
  )
}

function Parte({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <Stack gap="sm">
      <Title order={3}>{titulo}</Title>
      {children}
    </Stack>
  )
}

function Amostrinha({ cor, largura = 16 }: { cor: string; largura?: number }) {
  return (
    <Box
      w={largura}
      h={16}
      bg={cor}
      style={{ border: `1px solid ${CORES.borda}`, borderRadius: 2, flexShrink: 0 }}
    />
  )
}

// --- Dados de exemplo: um TV Fama de 49:12 -------------------------------------------

const DURACAO = 49 * 60 + 12
const AGORA = 12 * 60 + 4
const SEM_DECUPAGEM = { inicio: 31 * 60 + 10, fim: 33 * 60 + 40 }

interface Trecho {
  inicio: number
  fim: number
  nome: string
}

const PAUTAS: Trecho[] = [
  { inicio: 0, fim: 95, nome: 'Abertura e escalada' },
  { inicio: 95, fim: 410, nome: 'Leão Lobo comenta a separação de um casal de atores' },
  { inicio: 410, fim: 690, nome: 'Bastidores da novela das nove' },
  { inicio: 690, fim: 980, nome: 'Nelson Rubens e as notícias da semana' },
  { inicio: 980, fim: 1040, nome: 'Merchandising Ultrafarma' },
  { inicio: 1040, fim: 1420, nome: 'Andréa Corazza na estreia de um filme nacional' },
  { inicio: 1420, fim: 1870, nome: 'Entrevista no estúdio com Flávia Noronha' },
  { inicio: 2020, fim: 2640, nome: 'Casamento de uma cantora sertaneja' },
  { inicio: 2640, fim: DURACAO, nome: 'Encerramento' },
]

const APARICOES: Trecho[] = [
  { inicio: 12, fim: 80, nome: 'Flávia Noronha' },
  { inicio: 211, fim: 261, nome: 'Leão Lobo' },
  { inicio: 300, fim: 395, nome: 'Leão Lobo' },
  { inicio: 700, fim: 760, nome: 'Nelson Rubens' },
  { inicio: 990, fim: 1035, nome: 'Flávia Noronha' },
  { inicio: 1100, fim: 1180, nome: 'Andréa Corazza' },
  { inicio: 1430, fim: 1840, nome: 'Flávia Noronha' },
  { inicio: 2100, fim: 2160, nome: 'Não identificado' },
  { inicio: 2650, fim: 2940, nome: 'Flávia Noronha' },
]

const MENCOES: Trecho[] = [
  { inicio: 98, fim: 104, nome: 'Leão Lobo' },
  { inicio: 688, fim: 694, nome: 'Nelson Rubens' },
  { inicio: 1045, fim: 1050, nome: 'Andréa Corazza' },
  { inicio: 2600, fim: 2606, nome: 'Leão Lobo' },
]

const OBJETOS: Trecho[] = [
  { inicio: 12, fim: 80, nome: 'Vestido vermelho de Flávia Noronha' },
  { inicio: 211, fim: 261, nome: 'Óculos escuros de Leão Lobo' },
  { inicio: 990, fim: 1035, nome: 'Caixa de remédio Ultrafarma' },
  { inicio: 2210, fim: 2290, nome: 'Buquê de flores brancas' },
]

const COMERCIAIS: Trecho[] = [{ inicio: 980, fim: 1040, nome: 'Ultrafarma' }]

const TEXTOS: Trecho[] = [
  { inicio: 14, fim: 22, nome: 'TV FAMA' },
  { inicio: 215, fim: 222, nome: 'LEÃO LOBO · COLUNISTA' },
  { inicio: 702, fim: 709, nome: 'NELSON RUBENS' },
  { inicio: 995, fim: 1030, nome: 'ULTRAFARMA · LIGUE JÁ' },
  { inicio: 1102, fim: 1110, nome: 'ANDRÉA CORAZZA · REPÓRTER' },
]

// Falas curtas e seguidas, menos no trecho sem decupagem.
const FALAS: Trecho[] = []
for (let t = 0, i = 0; t < DURACAO; i++) {
  const passo = [7, 12, 5, 9, 15, 6, 11][i % 7]
  if (t < SEM_DECUPAGEM.inicio || t >= SEM_DECUPAGEM.fim) {
    FALAS.push({ inicio: t, fim: Math.min(t + passo - 1, DURACAO), nome: 'Fala' })
  }
  t += passo
}

const CORTES = Array.from({ length: 60 }, (_, i) => Math.round((i + 1) * 47.3 + (i % 3) * 9))

const FAIXAS: { tipo: TipoDeOcorrencia; singular: string; trechos: Trecho[] }[] = [
  { tipo: 'pauta', singular: 'Pauta', trechos: PAUTAS },
  { tipo: 'aparicao', singular: 'Aparição de', trechos: APARICOES },
  { tipo: 'mencao', singular: 'Menção a', trechos: MENCOES },
  { tipo: 'objeto', singular: 'Objeto', trechos: OBJETOS },
  { tipo: 'comercial', singular: 'Comercial de', trechos: COMERCIAIS },
  { tipo: 'fala', singular: 'Fala', trechos: FALAS },
  { tipo: 'texto_na_tela', singular: 'Texto na tela', trechos: TEXTOS },
]

const ENVIOS = ['Ana Lima', 'Bruno Costa', 'Carla Dias']
const ESTADOS_DA_AMOSTRA: Partial<Record<number, EstadoDoJob>> = {
  0: 'aguardando_upload',
  1: 'validando',
  2: 'analisando',
  5: 'falhou',
  11: 'cancelado',
}
const ACERVO = Array.from({ length: 30 }, (_, i) => {
  const exibicao = new Date(2026, 9, 30 - i)
  return {
    nome: `tv-fama-${exibicao.toISOString().slice(0, 10)}.mp4`,
    exibicao: exibicao.toLocaleDateString('pt-BR'),
    duracao: tempo(DURACAO - ((i * 37) % 180)),
    estado: ESTADOS_DA_AMOSTRA[i] ?? 'concluido',
    enviadoPor: ENVIOS[i % 3],
  }
})

const ATALHOS: [string[], string][] = [
  [['/'], 'Focar a busca'],
  [['Espaço', 'K'], 'Tocar e pausar'],
  [['L'], 'Tocar; de novo, 2× e 4×'],
  [['J'], 'Recuar 5 s'],
  [['←', '→'], 'Recuar e avançar 1 s; com Shift, 5 s'],
  [[',', '.'], 'Quadro anterior e seguinte, pausado'],
  [['N', 'Shift+N'], 'Momento seguinte e anterior da busca'],
  [['↑', '↓'], 'Item anterior e seguinte do painel'],
  [['Enter'], 'Saltar ao item'],
  [['E'], 'Modo de catalogação'],
  [['I', 'O', 'A'], 'Entrada, saída, acrescentar'],
  [['Ctrl+Z'], 'Desfazer a última correção'],
  [['?'], 'Lista de atalhos'],
  [['Esc'], 'Fechar o que estiver aberto'],
]

// --- Seções ---------------------------------------------------------------------------

const TOKENS: [string, string][] = [
  ['Fundo da página', CORES.fundo],
  ['Superfície (painel, tabela)', CORES.superficie],
  ['Superfície elevada (menu, diálogo)', CORES.elevada],
  ['Borda', CORES.borda],
  ['Texto', CORES.texto],
  ['Texto secundário', CORES.textoSecundario],
  ['Texto desabilitado', CORES.textoDesabilitado],
  ['Foco e seleção', CORES.foco],
  ['Texto de foco (link)', CORES.focoTexto],
  ['Concluído', CORES.concluido],
  ['Em andamento ou aguardando', CORES.andamento],
  ['Falhou', CORES.falhou],
  ['Marca RedeTV (só no logotipo)', CORES.marca],
]

const TEXTOS_SOBRE_FUNDOS: [string, string][] = [
  ['Texto', CORES.texto],
  ['Texto secundário', CORES.textoSecundario],
  ['Texto desabilitado (mínimo 3:1)', CORES.textoDesabilitado],
  ['Texto de foco (link)', CORES.focoTexto],
  ['Concluído', CORES.concluido],
  ['Em andamento', CORES.andamento],
  ['Falhou', CORES.falhou],
  ...Object.values(CORES_DE_OCORRENCIA).map(({ rotulo, cor }): [string, string] => [rotulo, cor]),
]

const FUNDOS: [string, string][] = [
  ['Fundo', CORES.fundo],
  ['Superfície', CORES.superficie],
  ['Elevada', CORES.elevada],
]

function Cores() {
  return (
    <Secao titulo="Cores">
      <Parte titulo="Tokens">
        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="xs" verticalSpacing="xs">
          {TOKENS.map(([nome, cor]) => (
            <Group key={nome} gap="sm" wrap="nowrap">
              <Amostrinha cor={cor} />
              <Text size="sm">{nome}</Text>
              <Code>{cor}</Code>
            </Group>
          ))}
        </SimpleGrid>
      </Parte>
      <Parte titulo="Contraste de cada texto">
        <Table aria-label="Contraste dos textos" withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Texto</Table.Th>
              {FUNDOS.map(([nome, cor]) => (
                <Table.Th key={nome}>
                  {nome} <Code>{cor}</Code>
                </Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {TEXTOS_SOBRE_FUNDOS.map(([nome, cor]) => (
              <Table.Tr key={nome}>
                <Table.Td>{nome}</Table.Td>
                {FUNDOS.map(([fundo, corDoFundo]) => (
                  <Table.Td key={fundo} bg={corDoFundo} c={cor} style={NUMEROS}>
                    Aa {razao(cor, corDoFundo)}
                  </Table.Td>
                ))}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Parte>
      <Parte titulo="Tipos de ocorrência">
        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="xs" verticalSpacing="xs">
          {Object.values(CORES_DE_OCORRENCIA).map(({ rotulo, cor }) => (
            <Group key={rotulo} gap="sm" wrap="nowrap">
              <Amostrinha cor={cor} largura={40} />
              <Text size="sm">{rotulo}</Text>
              <Code>{cor}</Code>
            </Group>
          ))}
          <Group gap="sm" wrap="nowrap">
            <Box
              w={40}
              h={16}
              style={{ background: HACHURADO, border: `1px solid ${CORES.borda}` }}
            />
            <Text size="sm">Trecho sem decupagem</Text>
          </Group>
          <Group gap="sm" wrap="nowrap">
            <Amostrinha cor={CORES.foco} largura={40} />
            <Text size="sm">Momentos da busca (cor de foco)</Text>
          </Group>
        </SimpleGrid>
      </Parte>
      <Parte titulo="Estados">
        <Group gap="xs">
          {Object.values(ESTADOS_DO_JOB).map(({ cor, rotulo }) => (
            <Badge key={rotulo} color={cor}>
              {rotulo}
            </Badge>
          ))}
        </Group>
      </Parte>
    </Secao>
  )
}

function Tipografia() {
  const tamanhos: [string, string, string][] = [
    ['xs', '12 px', 'Rótulo de faixa, metadado, selo'],
    ['sm', '13 px', 'Tabela, painel, botão'],
    ['md', '14 px', 'Texto corrido, campo'],
    ['lg', '16 px', 'Pouco uso: destaque dentro de diálogo'],
  ]
  return (
    <Secao titulo="Tipografia">
      <Stack gap="xs">
        {tamanhos.map(([t, px, uso]) => (
          <Group key={t} gap="md" wrap="nowrap">
            <Text size="xs" c="dimmed" w={110} style={NUMEROS}>
              {t} · {px}
            </Text>
            <Text size={t}>Leão Lobo comenta a separação de um casal de atores</Text>
            <Text size="xs" c="dimmed">
              {uso}
            </Text>
          </Group>
        ))}
        <Group gap="md" wrap="nowrap">
          <Text size="xs" c="dimmed" w={110}>
            Título 20 / 16 / 14
          </Text>
          <Text fz={20} fw={600}>
            Acervo
          </Text>
          <Text fz={16} fw={600}>
            Componentes
          </Text>
          <Text fz={14} fw={600}>
            Pessoas na imagem
          </Text>
        </Group>
        <Group gap="md" wrap="nowrap">
          <Text size="xs" c="dimmed" w={110}>
            Pesos
          </Text>
          <Text size="sm">400 regular</Text>
          <Text size="sm" fw={600}>
            600 seminegrito
          </Text>
        </Group>
        <Group gap="md" wrap="nowrap">
          <Text size="xs" c="dimmed" w={110}>
            Timecode
          </Text>
          <Text size="sm" ff="monospace" style={NUMEROS}>
            01:12:04:15
          </Text>
          <Text size="xs" c="dimmed">
            Monoespaçada, só no timecode de origem
          </Text>
        </Group>
        <Group gap="md" wrap="nowrap" align="flex-start">
          <Text size="xs" c="dimmed" w={110}>
            Algarismos fixos
          </Text>
          <Stack gap={0}>
            {['11:11', '48:08', '03:31'].map((t) => (
              <Text key={t} size="sm" style={NUMEROS}>
                {t}
              </Text>
            ))}
          </Stack>
          <Text size="xs" c="dimmed">
            tabular-nums: os tempos se alinham na coluna
          </Text>
        </Group>
      </Stack>
    </Secao>
  )
}

function Espacamentos() {
  const escala: [string, number, string][] = [
    ['xs', 4, 'Entre ícone e rótulo; dentro de selo'],
    ['sm', 8, 'Dentro de componente; entre itens de um grupo'],
    ['md', 12, 'Entre componentes'],
    ['lg', 16, 'Margem da página; entre blocos'],
    ['xl', 24, 'Entre seções'],
  ]
  return (
    <Secao titulo="Espaçamentos">
      <Stack gap="xs">
        {escala.map(([nome, px, uso]) => (
          <Group key={nome} gap="md" wrap="nowrap">
            <Text size="xs" c="dimmed" w={110} style={NUMEROS}>
              {nome} · {px} px
            </Text>
            <Box w={px} h={12} bg={CORES.textoSecundario} />
            <Text size="xs" c="dimmed">
              {uso}
            </Text>
          </Group>
        ))}
      </Stack>
    </Secao>
  )
}

function ItemDoPainel({
  tempo: t,
  cor,
  atual = false,
  selecionado = false,
  children,
}: {
  tempo: string
  cor: string
  atual?: boolean
  selecionado?: boolean
  children: ReactNode
}) {
  return (
    <UnstyledButton
      aria-current={atual || undefined}
      aria-pressed={selecionado}
      px="sm"
      py={6}
      bg={selecionado ? SELECIONADO : atual ? CORES.elevada : undefined}
      style={{ borderLeft: `3px solid ${atual ? CORES.foco : 'transparent'}`, display: 'block' }}
    >
      <Group gap="sm" wrap="nowrap">
        <Box w={8} h={8} bg={cor} style={{ borderRadius: 2, flexShrink: 0 }} />
        <Text size="xs" c="dimmed" style={NUMEROS}>
          {t}
        </Text>
        <Text size="sm" truncate>
          {children}
        </Text>
      </Group>
    </UnstyledButton>
  )
}

function Componentes() {
  const [dialogo, setDialogo] = useState(false)
  // O fundo de hover de cada variante, como o Mantine o pinta.
  const botoes: [string, string, (estilo?: CSSProperties, desabilitado?: boolean) => ReactNode][] =
    [
      [
        'Primário',
        'var(--mantine-primary-color-filled-hover)',
        (s, d) => (
          <Button style={s} disabled={d}>
            Salvar
          </Button>
        ),
      ],
      [
        'Secundário',
        'var(--mantine-color-default-hover)',
        (s, d) => (
          <Button variant="default" style={s} disabled={d}>
            Cancelar
          </Button>
        ),
      ],
      [
        'Perigo',
        `${CORES.falhou}0D`,
        (s, d) => (
          <Button variant="outline" color={CORES.falhou} style={s} disabled={d}>
            Apagar
          </Button>
        ),
      ],
      [
        'Ícone',
        'var(--mantine-color-gray-light-hover)',
        (s, d) => (
          <ActionIcon
            variant="subtle"
            color="gray"
            aria-label="Baixar o JSON"
            style={s}
            disabled={d}
          >
            <IconDownload size={18} />
          </ActionIcon>
        ),
      ],
    ]
  const campos: [string, (estado: CampoProps) => ReactNode][] = [
    ['Campo de texto', (e) => <TextInput aria-label="Nome" defaultValue="Leão Lobo" {...e} />],
    [
      'Campo de busca',
      (e) => (
        <TextInput
          aria-label="Buscar no acervo"
          placeholder="Buscar no acervo…"
          leftSection={<IconSearch size={16} />}
          rightSection={<Kbd size="xs">/</Kbd>}
          {...e}
        />
      ),
    ],
    [
      'Select',
      (e) => (
        <Select
          aria-label="Programa"
          data={['TV Fama', 'Superpop', 'A Tarde é Sua']}
          defaultValue="TV Fama"
          {...e}
        />
      ),
    ],
  ]
  const chips: [string, (estado: ChipProps) => ReactNode][] = [
    ['Estado', (e) => <Chip {...e}>Concluído</Chip>],
    [
      'Tipo',
      (e) => (
        <Chip color={CORES_DE_OCORRENCIA.mencao.cor} variant="outline" {...e}>
          Menções
        </Chip>
      ),
    ],
  ]
  return (
    <Secao titulo="Componentes">
      <Parte titulo="Botões">
        <Table withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th />
              <Table.Th>Normal</Table.Th>
              <Table.Th>Hover</Table.Th>
              <Table.Th>Foco</Table.Th>
              <Table.Th>Desabilitado</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {botoes.map(([nome, hover, botao]) => (
              <Table.Tr key={nome}>
                <Table.Td>{nome}</Table.Td>
                <Table.Td>{botao()}</Table.Td>
                <Table.Td>{botao({ background: hover })}</Table.Td>
                <Table.Td>{botao(ANEL)}</Table.Td>
                <Table.Td>{botao(undefined, true)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Group gap="sm">
          <Button loading>Salvar</Button>
          <Text size="xs" c="dimmed">
            Carregando. O primário é o azul de foco, nunca o vermelho.
          </Text>
        </Group>
      </Parte>

      <Parte titulo="Dica">
        <Group gap="xl" h={40} align="flex-end">
          <Tooltip label="Tocar o trecho" opened position="right">
            <ActionIcon variant="subtle" color="gray" aria-label="Tocar o trecho">
              <IconPlayerPlay size={18} />
            </ActionIcon>
          </Tooltip>
        </Group>
        <Text size="xs" c="dimmed">
          Todo botão de ícone tem dica e nome acessível. Ícone só onde a função é universal.
        </Text>
      </Parte>

      <Parte titulo="Campos">
        <Table withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th />
              <Table.Th>Normal</Table.Th>
              <Table.Th>Foco</Table.Th>
              <Table.Th>Erro</Table.Th>
              <Table.Th>Desabilitado</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {campos.map(([nome, campo]) => (
              <Table.Tr key={nome}>
                <Table.Td>{nome}</Table.Td>
                <Table.Td>{campo({})}</Table.Td>
                <Table.Td>{campo({ styles: { input: { borderColor: CORES.foco } } })}</Table.Td>
                <Table.Td>{campo({ error: 'Diga por que a correção é necessária.' })}</Table.Td>
                <Table.Td>{campo({ disabled: true })}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Text size="xs" c="dimmed">
          Campo e select não mudam no hover: o cursor de texto basta. O rótulo fica acima do campo;
          aqui ele vai no nome acessível, para caber na tabela.
        </Text>
      </Parte>

      <Parte titulo="Chips de filtro">
        <Table withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th />
              <Table.Th>Desligado</Table.Th>
              <Table.Th>Hover</Table.Th>
              <Table.Th>Ligado</Table.Th>
              <Table.Th>Foco</Table.Th>
              <Table.Th>Desabilitado</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {chips.map(([nome, chip]) => (
              <Table.Tr key={nome}>
                <Table.Td>{nome}</Table.Td>
                <Table.Td>{chip({})}</Table.Td>
                <Table.Td>
                  {chip({
                    styles: { label: { background: 'var(--mantine-color-default-hover)' } },
                  })}
                </Table.Td>
                <Table.Td>{chip({ defaultChecked: true })}</Table.Td>
                <Table.Td>{chip({ defaultChecked: true, styles: { label: ANEL } })}</Table.Td>
                <Table.Td>{chip({ disabled: true })}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Group gap="xs">
          {Object.entries(CORES_DE_OCORRENCIA).map(([tipo, { rotulo, cor }], i) => (
            <Chip key={tipo} color={cor} variant="outline" defaultChecked={i % 2 === 0}>
              {rotulo}
            </Chip>
          ))}
        </Group>
        <Text size="xs" c="dimmed">
          Ligado, o chip de tipo leva a cor do tipo; a marca de seleção é a pista que não depende de
          cor.
        </Text>
      </Parte>

      <Parte titulo="Selos">
        <Group gap="xs">
          {Object.values(ESTADOS_DO_JOB).map(({ cor, rotulo }) => (
            <Badge key={rotulo} color={cor}>
              {rotulo}
            </Badge>
          ))}
          <Badge variant="outline" color={CORES.textoSecundario}>
            não confirmado
          </Badge>
        </Group>
      </Parte>

      <Parte titulo="Abas com contagem">
        <Tabs defaultValue="pautas">
          <Tabs.List>
            {[
              ['pessoas', 'Pessoas', 4],
              ['pautas', 'Pautas', 9],
              ['marcas', 'Marcas', 0],
            ].map(([valor, nome, n]) => (
              <Tabs.Tab
                key={valor}
                value={String(valor)}
                rightSection={
                  <Text size="xs" c="dimmed" style={NUMEROS}>
                    {n}
                  </Text>
                }
              >
                {nome}
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </Tabs>
      </Parte>

      <Parte titulo="Item de lista do painel">
        <Stack gap={0} maw={480} bg={CORES.superficie}>
          <ItemDoPainel tempo="03:31" cor={CORES_DE_OCORRENCIA.aparicao.cor}>
            Normal: Leão Lobo
          </ItemDoPainel>
          <ItemDoPainel tempo="05:00" cor={CORES_DE_OCORRENCIA.aparicao.cor} selecionado>
            Selecionado: Leão Lobo
          </ItemDoPainel>
          <ItemDoPainel tempo="11:40" cor={CORES_DE_OCORRENCIA.aparicao.cor} atual>
            Atual: Nelson Rubens (barra de 3 px, nunca um bloco colorido)
          </ItemDoPainel>
        </Stack>
      </Parte>

      <Parte titulo="Faixa da linha do tempo">
        <Group gap="lg">
          {[
            ['Bloco', { background: CORES_DE_OCORRENCIA.pauta.cor }],
            [
              'Bloco selecionado',
              { background: CORES_DE_OCORRENCIA.pauta.cor, ...ANEL, outlineOffset: 1 },
            ],
            ['Sem decupagem', { background: HACHURADO }],
          ].map(([nome, estilo]) => (
            <Group key={String(nome)} gap="xs">
              <Box w={48} h={14} style={{ borderRadius: 2, ...(estilo as CSSProperties) }} />
              <Text size="xs" c="dimmed">
                {String(nome)}
              </Text>
            </Group>
          ))}
          <Group gap="xs">
            <Box w={2} h={20} bg={CORES.texto} />
            <Text size="xs" c="dimmed">
              Cursor de reprodução
            </Text>
          </Group>
          <Group gap="xs">
            <Box w={1} h={6} bg={CORES.textoSecundario} />
            <Text size="xs" c="dimmed">
              Risco de corte na régua
            </Text>
          </Group>
        </Group>
      </Parte>

      <Parte titulo="Menu">
        <Box h={150}>
          <Menu opened withinPortal={false} trapFocus={false} position="bottom-start">
            <Menu.Target>
              <ActionIcon variant="subtle" color="gray" aria-label="Ações da aparição">
                <IconDots size={18} />
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item>Corrigir pessoa</Menu.Item>
              <Menu.Item>Corrigir tempos</Menu.Item>
              <Menu.Item leftSection={<IconHistory size={14} />}>Histórico</Menu.Item>
              <Menu.Divider />
              <Menu.Item disabled>Fundir com outra pessoa</Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Box>
      </Parte>

      <Parte titulo="Diálogo">
        <Group>
          <Button variant="default" onClick={() => setDialogo(true)}>
            Abrir o diálogo
          </Button>
        </Group>
        <Modal opened={dialogo} onClose={() => setDialogo(false)} title="Corrigir pessoa" centered>
          <Stack gap="md">
            <TextInput label="Nome" defaultValue="Leão Lobo" />
            <Textarea label="Motivo" placeholder="O GC diz o nome." />
            <Group justify="flex-end" gap="sm">
              <Button variant="default" onClick={() => setDialogo(false)}>
                Cancelar
              </Button>
              <Button onClick={() => setDialogo(false)}>Salvar</Button>
            </Group>
          </Stack>
        </Modal>
      </Parte>

      <Parte titulo="Confirmação na própria linha">
        <Group gap="sm" px="sm" py={6} bg={CORES.superficie} maw={480}>
          <Text size="sm" style={NUMEROS}>
            Apagar a aparição de 03:31?
          </Text>
          <Button size="xs" variant="outline" color={CORES.falhou}>
            Apagar
          </Button>
          <Button size="xs" variant="default">
            Cancelar
          </Button>
        </Group>
      </Parte>

      <Parte titulo="Teclas e a lista do ?">
        <Table withTableBorder maw={560}>
          <Table.Tbody>
            {ATALHOS.map(([teclas, acao]) => (
              <Table.Tr key={acao}>
                <Table.Td w={140}>
                  <Group gap={4}>
                    {teclas.map((tecla) => (
                      <Kbd key={tecla} size="xs">
                        {tecla}
                      </Kbd>
                    ))}
                  </Group>
                </Table.Td>
                <Table.Td>{acao}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Parte>

      <Parte titulo="Estado vazio">
        <Stack gap={4} p="md" bg={CORES.superficie} maw={480}>
          <Text size="sm">Nenhuma marca neste vídeo.</Text>
          <Text size="xs" c="dimmed">
            A decupagem não achou logotipo nem merchandising. Se houver, marque no modo de
            catalogação (E).
          </Text>
        </Stack>
      </Parte>

      <Parte titulo="Alerta de erro com a ação">
        <Alert
          color={CORES.falhou}
          variant="light"
          icon={<IconAlertTriangle size={18} />}
          role="alert"
          maw={560}
        >
          <Stack gap="xs" align="flex-start">
            <Text size="sm">
              Não foi possível carregar a decupagem. Tente de novo em instantes.
            </Text>
            <Text size="xs" c="dimmed">
              Código para o suporte: decupagem_indisponivel
            </Text>
            <Button size="xs" variant="default">
              Tentar de novo
            </Button>
          </Stack>
        </Alert>
      </Parte>

      <Parte titulo="Carregando">
        <Group gap="sm">
          <Loader />
          <Text size="sm" c="dimmed">
            Carregando a decupagem…
          </Text>
        </Group>
      </Parte>
    </Secao>
  )
}

function Acervo() {
  return (
    <Secao titulo="Acervo">
      <Table aria-label="Acervo" highlightOnHover withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Nome</Table.Th>
            <Table.Th>Programa</Table.Th>
            <Table.Th aria-sort="descending">
              <Group gap={4} wrap="nowrap">
                Exibição <IconArrowDown size={14} aria-label="mais recente primeiro" />
              </Group>
            </Table.Th>
            <Table.Th>Duração</Table.Th>
            <Table.Th>Estado</Table.Th>
            <Table.Th>Enviado por</Table.Th>
            <Table.Th w={40}>
              <Text span size="xs" c="dimmed">
                Ações
              </Text>
            </Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {ACERVO.map((video, i) => {
            const estado = ESTADOS_DO_JOB[video.estado]
            const selecionado = i === 3
            return (
              <Table.Tr
                key={video.nome}
                aria-selected={selecionado}
                bg={selecionado ? SELECIONADO : undefined}
                style={{ boxShadow: selecionado ? `inset 3px 0 ${CORES.foco}` : undefined }}
              >
                <Table.Td>{video.nome}</Table.Td>
                <Table.Td>TV Fama</Table.Td>
                <Table.Td style={NUMEROS}>{video.exibicao}</Table.Td>
                <Table.Td style={NUMEROS}>{video.duracao}</Table.Td>
                <Table.Td>
                  <Group gap="xs" wrap="nowrap">
                    <Badge color={estado.cor}>{estado.rotulo}</Badge>
                    {video.estado === 'falhou' && (
                      <Tooltip label="Código para o suporte: codec_nao_suportado">
                        <Text size="xs" c="dimmed" truncate>
                          O vídeo usa um codec que não aceitamos. Envie em H.264.
                        </Text>
                      </Tooltip>
                    )}
                  </Group>
                </Table.Td>
                <Table.Td c="dimmed">{video.enviadoPor}</Table.Td>
                <Table.Td>
                  <Tooltip label="Mais ações">
                    <ActionIcon
                      variant="subtle"
                      color="gray"
                      size="sm"
                      aria-label={`Ações de ${video.nome}`}
                    >
                      <IconDots size={16} />
                    </ActionIcon>
                  </Tooltip>
                </Table.Td>
              </Table.Tr>
            )
          })}
        </Table.Tbody>
      </Table>
    </Secao>
  )
}

const ALTURA_DA_FAIXA = 14
const VAO_ENTRE_FAIXAS = 6
const ALTURA_DA_REGUA = 20
const pct = (s: number) => `${(s / DURACAO) * 100}%`

function LinhaDoTempo() {
  return (
    <Secao titulo="Linha do tempo">
      <Group gap="sm" wrap="nowrap" align="flex-start" p="sm" bg={CORES.superficie}>
        <Stack gap={VAO_ENTRE_FAIXAS} w={130} pt={ALTURA_DA_REGUA + VAO_ENTRE_FAIXAS}>
          {FAIXAS.map(({ tipo, trechos }) => (
            <Group key={tipo} gap={6} h={ALTURA_DA_FAIXA} justify="flex-end" wrap="nowrap">
              <Text size="xs" lh={1}>
                {CORES_DE_OCORRENCIA[tipo].rotulo}
              </Text>
              <Text size="xs" lh={1} c="dimmed" style={NUMEROS}>
                {trechos.length}
              </Text>
            </Group>
          ))}
        </Stack>
        <Box pos="relative" flex={1}>
          {/* Régua: tempo a cada 5 min e um risco a cada corte de plano. */}
          <Box pos="relative" h={ALTURA_DA_REGUA} mb={VAO_ENTRE_FAIXAS}>
            {Array.from({ length: 10 }, (_, i) => i * 300).map((s) => (
              <Text
                key={s}
                size="xs"
                c="dimmed"
                pos="absolute"
                top={0}
                lh={1}
                left={pct(s)}
                style={NUMEROS}
              >
                {tempo(s)}
              </Text>
            ))}
            {CORTES.map((s) => (
              <Box
                key={s}
                pos="absolute"
                bottom={0}
                w={1}
                h={6}
                bg={CORES.textoSecundario}
                left={pct(s)}
              />
            ))}
          </Box>
          <Stack gap={VAO_ENTRE_FAIXAS}>
            {FAIXAS.map(({ tipo, singular, trechos }) => (
              <Box key={tipo} pos="relative" h={ALTURA_DA_FAIXA} bg={CORES.fundo}>
                {trechos.map((t, i) => {
                  const selecionado = tipo === 'aparicao' && t.inicio === 211
                  const nome = tipo === 'fala' ? singular : `${singular} ${t.nome}`
                  return (
                    <UnstyledButton
                      key={i}
                      aria-label={`${nome}, ${tempo(t.inicio)} a ${tempo(t.fim)}`}
                      aria-pressed={selecionado}
                      pos="absolute"
                      top={0}
                      h={ALTURA_DA_FAIXA}
                      bg={CORES_DE_OCORRENCIA[tipo].cor}
                      left={pct(t.inicio)}
                      // 1 px de vão entre blocos encostados.
                      w={`max(2px, calc(${pct(t.fim - t.inicio)} - 1px))`}
                      style={{
                        borderRadius: 2,
                        ...(selecionado ? { ...ANEL, outlineOffset: 1, zIndex: 1 } : {}),
                      }}
                    />
                  )
                })}
              </Box>
            ))}
          </Stack>
          <Box
            role="img"
            aria-label={`Trecho sem decupagem, ${tempo(SEM_DECUPAGEM.inicio)} a ${tempo(SEM_DECUPAGEM.fim)}`}
            pos="absolute"
            top={ALTURA_DA_REGUA + VAO_ENTRE_FAIXAS}
            bottom={0}
            left={pct(SEM_DECUPAGEM.inicio)}
            w={pct(SEM_DECUPAGEM.fim - SEM_DECUPAGEM.inicio)}
            style={{ background: HACHURADO }}
          />
          <Box
            role="img"
            aria-label={`Posição atual, ${tempo(AGORA)}`}
            pos="absolute"
            top={0}
            bottom={0}
            w={2}
            bg={CORES.texto}
            left={pct(AGORA)}
            style={{ zIndex: 2 }}
          />
        </Box>
      </Group>
    </Secao>
  )
}

function Painel() {
  const abas: [string, number][] = [
    ['Pessoas', 4],
    ['Pautas', PAUTAS.length],
    ['Marcas', COMERCIAIS.length],
    ['Objetos', OBJETOS.length],
    ['Fala', FALAS.length],
    ['Texto na tela', TEXTOS.length],
  ]
  return (
    <Secao titulo="Painel">
      <Box
        maw={520}
        bg={CORES.superficie}
        style={{ border: `1px solid ${CORES.borda}`, borderRadius: 6 }}
      >
        <Tabs defaultValue="Pautas" keepMounted={false}>
          <Tabs.List>
            {abas.map(([nome, n]) => (
              <Tabs.Tab
                key={nome}
                value={nome}
                rightSection={
                  <Text size="xs" c="dimmed" style={NUMEROS}>
                    {n}
                  </Text>
                }
              >
                {nome}
              </Tabs.Tab>
            ))}
          </Tabs.List>
          <Tabs.Panel value="Pautas">
            <Stack gap={0} py={4}>
              {PAUTAS.map((p) => (
                <ItemDoPainel
                  key={p.inicio}
                  tempo={tempo(p.inicio)}
                  cor={CORES_DE_OCORRENCIA.pauta.cor}
                  atual={p.inicio <= AGORA && AGORA < p.fim}
                >
                  {p.nome}
                </ItemDoPainel>
              ))}
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="Pessoas">
            <Stack gap="xs" p="sm">
              {[
                ['Flávia Noronha', 'GC e fala'],
                ['Leão Lobo', 'GC'],
                ['Nelson Rubens', 'fala'],
              ].map(([nome, prova]) => (
                <Group key={nome} gap="sm">
                  <Text size="sm">{nome}</Text>
                  <Text size="xs" c="dimmed">
                    prova do nome: {prova}
                  </Text>
                </Group>
              ))}
              <Group gap="sm">
                <Text size="sm" c="dimmed">
                  Não identificado
                </Text>
                <Text size="xs" c="dimmed">
                  mulher de cabelo curto, vestido azul
                </Text>
                <Badge variant="outline" color={CORES.textoSecundario}>
                  não confirmado
                </Badge>
              </Group>
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="Objetos">
            <Stack gap={0} py={4}>
              {OBJETOS.map((o) => (
                <ItemDoPainel
                  key={o.inicio}
                  tempo={tempo(o.inicio)}
                  cor={CORES_DE_OCORRENCIA.objeto.cor}
                >
                  {o.nome}
                </ItemDoPainel>
              ))}
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="Marcas">
            <Stack gap={0} py={4}>
              {COMERCIAIS.map((c) => (
                <ItemDoPainel
                  key={c.inicio}
                  tempo={tempo(c.inicio)}
                  cor={CORES_DE_OCORRENCIA.comercial.cor}
                >
                  {c.nome}
                </ItemDoPainel>
              ))}
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="Texto na tela">
            <Stack gap={0} py={4}>
              {TEXTOS.map((t) => (
                <ItemDoPainel
                  key={t.inicio}
                  tempo={tempo(t.inicio)}
                  cor={CORES_DE_OCORRENCIA.texto_na_tela.cor}
                >
                  {t.nome}
                </ItemDoPainel>
              ))}
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="Fala">
            <Text size="sm" c="dimmed" p="sm">
              A transcrição sincronizada entra no redesenho do Visualizador.
            </Text>
          </Tabs.Panel>
        </Tabs>
      </Box>
    </Secao>
  )
}

export default function Amostra() {
  return (
    <Box bg={CORES.fundo} mih="100vh">
      <Group
        h={44}
        px="lg"
        gap="sm"
        bg={CORES.superficie}
        style={{ borderBottom: `1px solid ${CORES.borda}` }}
      >
        <Badge color={CORES.marca} variant="filled">
          MAM
        </Badge>
        <Title order={1} fz={14}>
          Sistema visual
        </Title>
        <Text size="xs" c="dimmed">
          Amostra com dados de exemplo; não chama a API.
        </Text>
        <Tooltip label="Fechar a amostra">
          <ActionIcon
            component="a"
            href="/"
            variant="subtle"
            color="gray"
            aria-label="Fechar a amostra"
            ml="auto"
          >
            <IconX size={18} />
          </ActionIcon>
        </Tooltip>
      </Group>
      <Stack gap="xl" p="lg" maw={1280} mx="auto">
        <Cores />
        <Tipografia />
        <Espacamentos />
        <Componentes />
        <Acervo />
        <LinhaDoTempo />
        <Painel />
      </Stack>
    </Box>
  )
}
