import { Button, Checkbox, Group, NativeSelect, Stack, Text, Textarea, TextInput, Tooltip } from '@mantine/core'
import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import type { CampoDoEditor, Editor, Valor } from './catalogacao.ts'
import { type Intervalo, tempo } from './linhaDoTempo.ts'

/** O formulário compacto que toma o lugar da linha do item: Enter salva e Esc cancela, sem diálogo. */
export function FormularioDeCorrecao({
  editor,
  rotulo,
  limiteDoMotivo,
  tempos,
  aoSalvar,
  aoCancelar,
}: {
  editor: Editor
  /** O nome acessível do formulário ("Corrigir Leão Lobo"). */
  rotulo: string
  limiteDoMotivo: number
  /** Os tempos que as alças da linha do tempo ajustaram; valem no lugar dos campos de tempo. */
  tempos?: Intervalo | null
  /** Grava os pedidos com o motivo; devolve a mensagem de erro, ou `null` quando gravou. */
  aoSalvar: (pedidos: NonNullable<ReturnType<Editor['pedidos']>>, motivo: string) => Promise<string | null>
  aoCancelar: () => void
}) {
  const [valores, setValores] = useState<Record<string, Valor>>(editor.inicial)
  const [motivo, setMotivo] = useState<string | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [salvando, setSalvando] = useState(false)
  // As alças mandam nos campos de tempo até a pessoa digitar neles.
  const [exatos, setExatos] = useState<Intervalo | null>(null)
  const [temposVistos, setTemposVistos] = useState<Intervalo | null | undefined>(undefined)
  if (tempos !== temposVistos) {
    setTemposVistos(tempos)
    if (tempos) {
      setExatos(tempos)
      setValores((v) => ({ ...v, inicio: tempo(tempos.inicio_ms), fim: tempo(tempos.fim_ms) }))
    }
  }
  const raiz = useRef<HTMLFormElement>(null)
  useEffect(() => {
    raiz.current?.querySelector<HTMLElement>('input, textarea, select')?.focus()
  }, [])

  const pedidos = editor.pedidos(valores, exatos)
  const doGesto = pedidos && pedidos.length > 0 ? editor.motivo(pedidos) : ''

  function mudar(campo: CampoDoEditor, valor: Valor) {
    if (campo.tipo === 'tempo') setExatos(null)
    setValores((v) => ({ ...v, [campo.chave]: valor }))
  }

  async function salvar() {
    if (salvando) return
    if (!pedidos) {
      setErro('Confira os campos: há um valor em branco ou um tempo fora do formato MM:SS.')
      return
    }
    if (pedidos.length === 0) {
      aoCancelar()
      return
    }
    setErro(null)
    setSalvando(true)
    const falha = await aoSalvar(pedidos, (motivo ?? '').trim() || doGesto)
    setSalvando(false)
    if (falha) setErro(falha)
  }

  function aoTeclar(e: KeyboardEvent<HTMLFormElement>) {
    if (e.key === 'Escape') {
      e.preventDefault()
      aoCancelar()
    } else if (e.key === 'Enter' && !(e.target instanceof HTMLButtonElement) && !(e.target instanceof HTMLTextAreaElement && e.shiftKey)) {
      e.preventDefault()
      void salvar()
    }
  }

  function campo(c: CampoDoEditor) {
    if (c.visivel && !c.visivel(valores)) return null
    const valor = valores[c.chave]
    switch (c.tipo) {
      case 'texto':
      case 'tempo':
        return (
          <TextInput
            key={c.chave}
            size="xs"
            label={c.rotulo}
            maxLength={c.limite}
            value={String(valor ?? '')}
            onChange={(e) => mudar(c, e.currentTarget.value)}
          />
        )
      case 'area':
        return (
          <Textarea
            key={c.chave}
            size="xs"
            label={c.rotulo}
            rows={3}
            maxLength={c.limite}
            value={String(valor ?? '')}
            onChange={(e) => mudar(c, e.currentTarget.value)}
          />
        )
      case 'opcoes':
        return (
          <NativeSelect
            key={c.chave}
            size="xs"
            label={c.rotulo}
            data={(c.opcoes ?? []).map((o) => ({ value: o.valor, label: o.rotulo }))}
            value={String(valor ?? '')}
            onChange={(e) => mudar(c, e.currentTarget.value)}
          />
        )
      case 'multiplas':
        return (
          <Checkbox.Group key={c.chave} label={c.rotulo} value={(valor as string[]) ?? []} onChange={(v) => mudar(c, v)}>
            <Group gap="sm" mt={2}>
              {(c.opcoes ?? []).map((o) => (
                <Checkbox key={o.valor} size="xs" value={o.valor} label={o.rotulo} />
              ))}
            </Group>
          </Checkbox.Group>
        )
      case 'booleano':
        return (
          <Checkbox
            key={c.chave}
            size="xs"
            label={c.rotulo}
            checked={valor === true}
            onChange={(e) => mudar(c, e.currentTarget.checked)}
          />
        )
    }
  }

  return (
    <form ref={raiz} aria-label={rotulo} onKeyDown={aoTeclar} onSubmit={(e) => e.preventDefault()}>
      <Stack gap="xs">
        {editor.campos.map(campo)}
        <TextInput
          size="xs"
          label="Motivo (opcional)"
          maxLength={limiteDoMotivo}
          value={motivo ?? doGesto}
          onChange={(e) => setMotivo(e.currentTarget.value)}
        />
        {erro && (
          <Text size="xs" role="alert" c="red.4">
            {erro}
          </Text>
        )}
        <Group gap="xs" justify="space-between">
          <Text size="xs" c="dimmed">
            Enter salva · Esc cancela
          </Text>
          <Group gap="xs">
            <Tooltip label="Esc">
              <Button size="compact-xs" variant="default" onClick={aoCancelar}>
                Cancelar
              </Button>
            </Tooltip>
            <Tooltip label="Enter">
              <Button size="compact-xs" loading={salvando} onClick={() => void salvar()}>
                Salvar
              </Button>
            </Tooltip>
          </Group>
        </Group>
      </Stack>
    </form>
  )
}

/** A confirmação do "não é isto", na própria linha: Enter confirma e Esc cancela. */
export function ConfirmacaoDeRemocao({
  texto,
  aoConfirmar,
  aoCancelar,
}: {
  texto: string
  aoConfirmar: () => void
  aoCancelar: () => void
}) {
  const raiz = useRef<HTMLDivElement>(null)
  useEffect(() => raiz.current?.focus(), [])
  return (
    <Group
      ref={raiz}
      role="group"
      aria-label="Confirmar a remoção"
      tabIndex={-1}
      gap="xs"
      wrap="nowrap"
      justify="space-between"
      style={{ outline: 'none' }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          aoConfirmar()
        } else if (e.key === 'Escape') {
          e.preventDefault()
          aoCancelar()
        }
      }}
    >
      <Text size="sm">{texto}</Text>
      <Group gap="xs" wrap="nowrap" style={{ flex: 'none' }}>
        <Tooltip label="Esc">
          <Button size="compact-xs" variant="default" onClick={aoCancelar}>
            Cancelar
          </Button>
        </Tooltip>
        <Tooltip label="Enter">
          <Button size="compact-xs" color="red" onClick={aoConfirmar}>
            Remover
          </Button>
        </Tooltip>
      </Group>
    </Group>
  )
}
