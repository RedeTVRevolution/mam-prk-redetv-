import { Badge, Box, Group, Paper, Select, Stack, Text, UnstyledButton } from '@mantine/core'
import { useEffect, useState } from 'react'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import { type ClienteDoJob, codigoDoErro, SessaoExpirada } from './api.ts'
import { relogio } from './linhaDoTempo.ts'
import type { ComparacaoDaPassada, ItemMarcado, ResumoDaPassada } from './passadas.ts'
import { CORES } from './tema.ts'

const TITULOS: Record<string, string> = {
  famosos: 'Famosos',
  mencoes: 'Menções',
  pautas: 'Pautas',
  broll_limpos: 'B-roll: planos limpos',
  broll_descricoes: 'B-roll: descrições',
  comerciais: 'Comerciais',
}

const DATA = new Intl.DateTimeFormat('pt-BR', { timeZone: 'America/Sao_Paulo' })

/** O seletor "Comparar com": `null` volta ao painel de sempre. */
export function SeletorDePassada({
  passadas,
  valor,
  aoEscolher,
}: {
  passadas: ResumoDaPassada[]
  valor: string | null
  aoEscolher: (id: string | null) => void
}) {
  return (
    <Select
      size="xs"
      aria-label="Comparar com"
      placeholder="Comparar com"
      clearable
      data={passadas.map((p) => ({
        value: p.id,
        label: `${p.modelo} · ${DATA.format(new Date(p.criada_em))}`,
      }))}
      value={valor}
      onChange={aoEscolher}
      w={260}
    />
  )
}

function dinheiro(usd: number | null): string {
  return usd === null ? 'n/d' : `US$ ${usd.toFixed(2).replace('.', ',')} por hora`
}

function duracao(segundos: number): string {
  return relogio(segundos * 1000)
}

function marcaDoItem(i: ItemMarcado): string | null {
  if (i.marca === 'so_aqui') return 'só neste lado'
  if (i.marca === 'difere') return `difere: ${i.motivos.join(', ')}`
  return null
}

function Lado({
  rotulo,
  itens,
  aoSaltar,
}: {
  rotulo: string
  itens: ItemMarcado[]
  aoSaltar: (ms: number) => void
}) {
  return (
    <Stack gap={2} flex={1} miw={0}>
      {itens.length === 0 && (
        <Text size="xs" c="dimmed">
          Nada
        </Text>
      )}
      {itens.map((i) => {
        const marca = marcaDoItem(i)
        return (
          <UnstyledButton
            key={`${i.inicio_ms}-${i.fim_ms}-${i.identidade}`}
            onClick={() => aoSaltar(i.inicio_ms)}
            aria-label={`${rotulo}: ${i.identidade} ${relogio(i.inicio_ms)}`}
            style={{ textAlign: 'left' }}
          >
            <Group gap="xs" wrap="nowrap" align="flex-start">
              <Text size="xs" c="dimmed" ff="monospace">
                {relogio(i.inicio_ms)}
              </Text>
              <Text size="sm" style={{ flex: 1, minWidth: 0 }}>
                {i.identidade || '(sem descrição)'}
                {i.detalhe ? ` [${i.detalhe}]` : ''}
              </Text>
              {marca && (
                // Diferença não é estado do Job: selo neutro, e a palavra diz o que é (P3).
                <Badge size="xs" variant="light" color={CORES.textoSecundario}>
                  {marca}
                </Badge>
              )}
            </Group>
          </UnstyledButton>
        )
      })}
    </Stack>
  )
}

/**
 * As duas decupagens do mesmo vídeo lado a lado: a do Job (à esquerda) e a da passada. Só
 * leitura: clicar num item leva o player ao início dele, e nada aqui corrige a passada.
 */
export function ComparacaoDePassada({
  api,
  passadaId,
  aoSaltar,
}: {
  api: ClienteDoJob
  passadaId: string
  aoSaltar: (ms: number) => void
}) {
  const [carga, setCarga] = useState<{ id: string; comparacao: ComparacaoDaPassada } | { id: string; codigo: string } | null>(null)
  const [tentativas, setTentativas] = useState(0)

  useEffect(() => {
    let vivo = true
    api.comparacao(passadaId).then(
      (comparacao) => {
        if (vivo) setCarga({ id: passadaId, comparacao })
      },
      (erro: unknown) => {
        if (vivo && !(erro instanceof SessaoExpirada)) setCarga({ id: passadaId, codigo: codigoDoErro(erro) })
      },
    )
    return () => {
      vivo = false
    }
  }, [api, passadaId, tentativas])

  if (!carga || carga.id !== passadaId) {
    return (
      <Text size="sm" c="dimmed">
        Carregando a comparação…
      </Text>
    )
  }
  if ('codigo' in carga) {
    return (
      <AlertaDeErro
        mensagem="Não foi possível carregar a comparação. Tente de novo em instantes."
        codigo={carga.codigo}
        aoTentar={() => {
          setCarga(null)
          setTentativas((n) => n + 1)
        }}
      />
    )
  }
  const { comparacao: c } = carga
  return (
    <Stack gap="sm" style={{ minHeight: 0, overflowY: 'auto' }}>
      <Paper withBorder p="xs" component="section" aria-label="Custo e tempo">
        <Group grow align="flex-start">
          <Stack gap={0}>
            <Text size="sm" fw={600}>
              Job ({c.modelo_do_job})
            </Text>
            <Text size="xs">{dinheiro(c.a.custo_por_hora_usd)}</Text>
            <Text size="xs">Tempo: {duracao(c.a.tempo_total_s)}</Text>
          </Stack>
          <Stack gap={0}>
            <Text size="sm" fw={600}>
              Passada ({c.modelo})
            </Text>
            <Text size="xs">{dinheiro(c.b.custo_por_hora_usd)}</Text>
            <Text size="xs">Tempo: {duracao(c.b.tempo_total_s)}</Text>
          </Stack>
        </Group>
      </Paper>
      <Group gap="sm" align="flex-start" wrap="nowrap">
        <Box component="section" aria-label="Decupagem do Job" flex={1} miw={0}>
          <Text size="sm" fw={600} mb={4}>
            Job
          </Text>
          <Requisitos c={c} lado="a" rotulo="Job" aoSaltar={aoSaltar} />
        </Box>
        <Box component="section" aria-label="Decupagem da passada" flex={1} miw={0}>
          <Text size="sm" fw={600} mb={4}>
            Passada
          </Text>
          <Requisitos c={c} lado="b" rotulo="Passada" aoSaltar={aoSaltar} />
        </Box>
      </Group>
    </Stack>
  )
}

function Requisitos({
  c,
  lado,
  rotulo,
  aoSaltar,
}: {
  c: ComparacaoDaPassada
  lado: 'a' | 'b'
  rotulo: string
  aoSaltar: (ms: number) => void
}) {
  return (
    <Stack gap="sm">
      {c.requisitos.map((r) => (
        <Stack gap={2} key={r.nome}>
          <Text size="xs" fw={600} c="dimmed">
            {TITULOS[r.nome] ?? r.nome}
          </Text>
          <Lado rotulo={rotulo} itens={r[lado]} aoSaltar={aoSaltar} />
        </Stack>
      ))}
    </Stack>
  )
}
