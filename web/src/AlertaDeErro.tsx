import { Alert, Button, Group, Text } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { CORES } from './tema.ts'

/** Alerta de erro do sistema visual: frase com a ação, código para o suporte e o botão. */
export function AlertaDeErro({
  mensagem,
  codigo,
  aoTentar,
}: {
  mensagem: string
  codigo: string
  aoTentar?: () => void
}) {
  return (
    <Alert color={CORES.falhou} variant="light" icon={<IconAlertTriangle />} role="alert">
      <Group gap="sm">
        <Text size="sm">{mensagem}</Text>
        <Text size="xs" c={CORES.textoSecundario}>
          Código para o suporte: {codigo}
        </Text>
        {aoTentar && (
          <Button type="button" size="xs" variant="default" onClick={aoTentar}>
            Tentar de novo
          </Button>
        )}
      </Group>
    </Alert>
  )
}
