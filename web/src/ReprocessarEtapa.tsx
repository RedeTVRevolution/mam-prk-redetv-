import { Alert, Button, Group, Paper, Radio, Stack, Text, Textarea } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { useState } from 'react'
import { type ClienteDoJob, ConflitoNaApi, PedidoInvalido, SessaoExpirada, codigoDoErro } from './api.ts'
import { ETAPAS_ESCOLHIVEIS, impactoDoReprocessamento, nomeDaEtapa, type EtapaEscolhivel as Etapa } from './etapas.ts'
import type { Job } from './jobs.ts'
import { CORES } from './tema.ts'

/** A escolha da etapa e do motivo, na própria tela: o Job que a API devolve vai a `aoReprocessar`. */
export function ReprocessarEtapa({
  api,
  aoReprocessar,
  aoCancelar,
}: {
  api: ClienteDoJob
  aoReprocessar: (job: Job, etapa: string) => void
  aoCancelar: () => void
}) {
  const [etapa, setEtapa] = useState<Etapa>('analise')
  const [motivo, setMotivo] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [falha, setFalha] = useState<{ mensagem: string; codigo: string | null } | null>(null)

  async function confirmar() {
    setEnviando(true)
    setFalha(null)
    try {
      aoReprocessar(await api.reprocessar(etapa, motivo.trim()), etapa)
    } catch (e) {
      if (e instanceof SessaoExpirada) return
      setFalha(
        e instanceof ConflitoNaApi || e instanceof PedidoInvalido
          ? { mensagem: e.message, codigo: null }
          : {
              mensagem: 'Não foi possível reprocessar. Tente de novo em instantes.',
              codigo: codigoDoErro(e),
            },
      )
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Paper withBorder p="sm">
      <Stack gap="xs">
        <Radio.Group
          label="Reprocessar a partir de"
          value={etapa}
          onChange={(v) => setEtapa(v as Etapa)}
        >
          <Stack gap={4} mt={4}>
            {ETAPAS_ESCOLHIVEIS.map((e) => (
              <Radio key={e.valor} value={e.valor} label={nomeDaEtapa(e.valor)} description={e.refaz} />
            ))}
          </Stack>
        </Radio.Group>
        <Textarea
          label="Motivo"
          description="Fica na auditoria."
          required
          rows={2}
          maxLength={500}
          value={motivo}
          onChange={(e) => setMotivo(e.currentTarget.value)}
        />
        <Text size="sm">
          {impactoDoReprocessamento(etapa)}
        </Text>
        {falha && (
          <Alert color={CORES.falhou} variant="light" icon={<IconAlertTriangle />} role="alert">
            <Text size="sm">{falha.mensagem}</Text>
            {falha.codigo && (
              <Text size="xs" c={CORES.textoSecundario}>
                Código para o suporte: {falha.codigo}
              </Text>
            )}
          </Alert>
        )}
        <Group gap="xs" justify="flex-end">
          <Button type="button" variant="default" onClick={aoCancelar} disabled={enviando}>
            Cancelar
          </Button>
          <Button
            type="button"
            onClick={() => void confirmar()}
            loading={enviando}
            disabled={motivo.trim() === ''}
          >
            Reprocessar
          </Button>
        </Group>
      </Stack>
    </Paper>
  )
}
