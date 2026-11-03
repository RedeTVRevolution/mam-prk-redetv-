import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Checkbox,
  CopyButton,
  Group,
  Loader,
  Modal,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
  VisuallyHidden,
} from '@mantine/core'
import { IconPlus, IconTrash } from '@tabler/icons-react'
import { useCallback, useEffect, useState } from 'react'
import { SessaoExpirada, type ChaveDaLista, type ClienteDaApi } from './api.ts'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import { CORES } from './tema.ts'
import { falhaDaAcao, type Falha } from './falhaDaAcao.ts'

/** Os escopos do `api/auth.py`, com o que cada um permite. */
const ESCOPOS = [
  { valor: 'criar', pode: 'cria vídeos para decupar' },
  { valor: 'ler', pode: 'lê a decupagem e o estado dos vídeos' },
  { valor: 'cancelar', pode: 'cancela vídeos em andamento' },
]

function data(iso: string): string {
  return new Date(iso).toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo' })
}

/**
 * Montado só enquanto aberto. A chave emitida vive só no estado deste diálogo: ao fechar,
 * o componente some e ela não fica em nenhum outro lugar.
 */
function EmitirChave({
  aoFechar,
  aoEmitir,
}: {
  aoFechar: () => void
  aoEmitir: (corpo: { sistema: string; escopos: string[] }) => Promise<string>
}) {
  const [sistema, setSistema] = useState('')
  const [escopos, setEscopos] = useState<string[]>([])
  const [chave, setChave] = useState<string | null>(null)
  const [emitindo, setEmitindo] = useState(false)
  const [falha, setFalha] = useState<Falha | null>(null)
  const completa = sistema.trim() !== '' && escopos.length > 0

  async function emitir() {
    setEmitindo(true)
    setFalha(null)
    try {
      setChave(await aoEmitir({ sistema: sistema.trim(), escopos }))
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro))
    } finally {
      setEmitindo(false)
    }
  }

  if (chave !== null) {
    return (
      // Só "Já guardei" fecha: sem X, sem Esc, sem clique fora.
      <Modal opened onClose={() => {}} title="Chave emitida" withCloseButton={false} closeOnEscape={false} closeOnClickOutside={false}>
        <Stack gap="sm">
          <Alert color={CORES.concluido} variant="light">
            Guarde agora: ela não será mostrada de novo.
          </Alert>
          <Group gap="xs" wrap="nowrap" align="flex-end">
            <TextInput label="Chave" readOnly value={chave} style={{ flex: 1 }} styles={{ input: { fontFamily: 'monospace' } }} />
            <CopyButton value={chave}>
              {({ copied, copy }) => (
                <Button type="button" variant="default" onClick={copy}>
                  {copied ? 'Copiada' : 'Copiar'}
                </Button>
              )}
            </CopyButton>
          </Group>
          <Group justify="flex-end">
            <Button type="button" onClick={aoFechar} data-autofocus>
              Já guardei
            </Button>
          </Group>
        </Stack>
      </Modal>
    )
  }

  return (
    <Modal opened onClose={aoFechar} title="Emitir chave">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (completa && !emitindo) void emitir()
        }}
      >
        <Stack gap="sm">
          <TextInput label="Sistema" value={sistema} onChange={(e) => setSistema(e.currentTarget.value)} data-autofocus />
          <Text size="sm" fw={500}>
            Escopos
          </Text>
          <Stack gap="xs">
            {ESCOPOS.map((e) => (
              <Checkbox
                key={e.valor}
                label={e.valor}
                description={`${e.valor}: ${e.pode}`}
                checked={escopos.includes(e.valor)}
                onChange={(ev) =>
                  setEscopos(ESCOPOS.map((q) => q.valor).filter((v) => (v === e.valor ? ev.currentTarget.checked : escopos.includes(v))))
                }
              />
            ))}
          </Stack>
          {falha && <AlertaDeErro mensagem={falha.mensagem} codigo={falha.codigo} />}
          <Group justify="flex-end">
            <Button type="button" variant="default" onClick={aoFechar}>
              Cancelar
            </Button>
            <Button type="submit" disabled={!completa} loading={emitindo}>
              Emitir chave
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  )
}

type Carga = { tipo: 'carregando' } | { tipo: 'pronta' } | { tipo: 'erro'; mensagem: string; codigo: string }

/** `/admin/chaves`: sistemas e chaves de API (docs/design/administracao.md). */
export default function Chaves({ api }: { api: ClienteDaApi }) {
  const [chaves, setChaves] = useState<ChaveDaLista[]>([])
  const [carga, setCarga] = useState<Carga>({ tipo: 'carregando' })
  const [emitindo, setEmitindo] = useState(false)
  const [revogando, setRevogando] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [falha, setFalha] = useState<Falha | null>(null)

  const carregar = useCallback(async () => {
    setCarga({ tipo: 'carregando' })
    try {
      setChaves(await api.chaves.listar())
      setCarga({ tipo: 'pronta' })
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setCarga({ tipo: 'erro', ...falhaDaAcao(erro) })
    }
  }, [api])

  useEffect(() => {
    // Sincroniza com a API, um sistema externo.
    // oxlint-disable-next-line react/set-state-in-effect
    void carregar()
  }, [carregar])

  async function revogar(chave: ChaveDaLista) {
    setRevogando(null)
    setAviso(null)
    setFalha(null)
    try {
      const nova = await api.chaves.revogar(chave.id)
      setChaves((atuais) => atuais.map((c) => (c.id === nova.id ? nova : c)))
      setAviso(`A chave de ${chave.sistema} foi revogada.`)
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro))
    }
  }

  return (
    <Stack gap="sm">
      <Group gap="sm">
        <Button type="button" size="xs" leftSection={<IconPlus size={14} />} ml="auto" onClick={() => setEmitindo(true)}>
          Emitir chave
        </Button>
      </Group>
      {aviso && (
        <Alert color={CORES.concluido} variant="light" role="status">
          {aviso}
        </Alert>
      )}
      {falha && <AlertaDeErro mensagem={falha.mensagem} codigo={falha.codigo} />}
      {carga.tipo === 'carregando' && <Loader role="status" aria-label="Carregando as chaves" size="sm" />}
      {carga.tipo === 'erro' && <AlertaDeErro mensagem={carga.mensagem} codigo={carga.codigo} aoTentar={() => void carregar()} />}
      {carga.tipo === 'pronta' && (
        <Table aria-label="Chaves" highlightOnHover verticalSpacing={4}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Sistema</Table.Th>
              <Table.Th>Escopos</Table.Th>
              <Table.Th>Id</Table.Th>
              <Table.Th>Criada em</Table.Th>
              <Table.Th>Situação</Table.Th>
              <Table.Th>
                <VisuallyHidden>Ações</VisuallyHidden>
              </Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {chaves.map((c) => (
              <LinhaDaChave
                key={c.id}
                chave={c}
                revogando={revogando === c.id}
                aoPedirRevogar={() => setRevogando(c.id)}
                aoCancelar={() => setRevogando(null)}
                aoRevogar={() => void revogar(c)}
              />
            ))}
          </Table.Tbody>
        </Table>
      )}
      {carga.tipo === 'pronta' && chaves.length === 0 && <Text size="sm">Nenhuma chave emitida.</Text>}
      {emitindo && (
        <EmitirChave
          aoFechar={() => setEmitindo(false)}
          aoEmitir={async (corpo) => {
            const { chave, ...registro } = await api.chaves.emitir(corpo)
            setChaves((atuais) => [registro, ...atuais])
            setFalha(null)
            setAviso(null)
            return chave
          }}
        />
      )}
    </Stack>
  )
}

function LinhaDaChave({
  chave,
  revogando,
  aoPedirRevogar,
  aoCancelar,
  aoRevogar,
}: {
  chave: ChaveDaLista
  revogando: boolean
  aoPedirRevogar: () => void
  aoCancelar: () => void
  aoRevogar: () => void
}) {
  const revogada = chave.revogada_em !== null
  return (
    <>
      <Table.Tr>
        <Table.Td>{chave.sistema}</Table.Td>
        <Table.Td>{chave.escopos.join(', ')}</Table.Td>
        <Table.Td style={{ fontFamily: 'monospace' }}>{chave.id}</Table.Td>
        <Table.Td style={{ fontVariantNumeric: 'tabular-nums' }}>{data(chave.criada_em)}</Table.Td>
        <Table.Td>
          {revogada ? (
            <Text size="sm" c={CORES.textoSecundario}>
              {`Revogada em ${data(chave.revogada_em!)}`}
            </Text>
          ) : (
            <Badge variant="light" color={CORES.concluido} radius="sm">
              Ativa
            </Badge>
          )}
        </Table.Td>
        <Table.Td>
          {!revogada && (
            <Tooltip label="Revogar">
              <ActionIcon variant="subtle" color="gray" aria-label={`Revogar a chave de ${chave.sistema}`} onClick={aoPedirRevogar}>
                <IconTrash size={16} aria-hidden />
              </ActionIcon>
            </Tooltip>
          )}
        </Table.Td>
      </Table.Tr>
      {revogando && (
        <Table.Tr
          onKeyDown={(e) => {
            if (e.key === 'Escape') aoCancelar()
          }}
        >
          <Table.Td colSpan={6}>
            <Group gap="sm">
              <Text size="sm">{`Revogar a chave de ${chave.sistema}? Ela para de funcionar na hora.`}</Text>
              <Button type="button" size="xs" variant="outline" color={CORES.falhou} autoFocus onClick={aoRevogar} aria-label="Confirmar revogação">
                Revogar
              </Button>
              <Button type="button" size="xs" variant="default" onClick={aoCancelar}>
                Cancelar
              </Button>
            </Group>
          </Table.Td>
        </Table.Tr>
      )}
    </>
  )
}
