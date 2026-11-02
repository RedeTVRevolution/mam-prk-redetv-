import { Button, Group, Select, TextInput } from '@mantine/core'
import { IconDownload } from '@tabler/icons-react'
import { useEffect, useState, type ReactNode } from 'react'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import type { ClienteDaApi } from './api.ts'
import type { Carga } from './useRelatorio.ts'
import type { FiltrosDoRelatorio } from './tempoDeTela.ts'

// O que as telas de Relatórios têm em comum na tela: filtros de programa e período, o botão de CSV e
// os alertas de erro (o estado vive em `useRelatorio.ts`).

export function ErroDoRelatorio({ carga, aoTentar }: { carga: Carga<unknown>; aoTentar: () => void }) {
  return carga.tipo === 'erro' ? (
    <AlertaDeErro mensagem={carga.mensagem} codigo={carga.codigo} aoTentar={aoTentar} />
  ) : null
}

const TODOS = '__todos__'

/** Programa e período de exibição; `children` são os filtros próprios do relatório e o CSV. */
export function FiltrosDoPeriodo({
  api,
  filtros,
  aoMudar,
  children,
}: {
  api: ClienteDaApi
  filtros: FiltrosDoRelatorio
  aoMudar: (parte: Partial<FiltrosDoRelatorio>) => void
  children?: ReactNode
}) {
  const [programas, setProgramas] = useState<string[]>([])
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

  return (
    <Group gap="sm" align="flex-end" wrap="wrap">
      <Select
        aria-label="Programa"
        size="xs"
        w={200}
        allowDeselect={false}
        data={[{ value: TODOS, label: 'Todos os programas' }, ...programas]}
        value={filtros.programa || TODOS}
        onChange={(valor) => aoMudar({ programa: valor && valor !== TODOS ? valor : '' })}
      />
      <TextInput
        type="date"
        aria-label="Exibido de"
        size="xs"
        value={filtros.de}
        onChange={(e) => aoMudar({ de: e.currentTarget.value })}
      />
      <TextInput
        type="date"
        aria-label="Exibido até"
        size="xs"
        value={filtros.ate}
        onChange={(e) => aoMudar({ ate: e.currentTarget.value })}
      />
      {children}
    </Group>
  )
}

export function BotaoDeCsv({ desligado, aoClicar }: { desligado: boolean; aoClicar: () => void }) {
  return (
    <Button
      type="button"
      size="xs"
      variant="default"
      leftSection={<IconDownload size={14} aria-hidden />}
      disabled={desligado}
      onClick={aoClicar}
    >
      Baixar CSV
    </Button>
  )
}

export function AlertaDoCsv({ falhou }: { falhou: boolean }) {
  return falhou ? <AlertaDeErro mensagem="Não foi possível baixar o CSV agora." codigo="csv" /> : null
}
