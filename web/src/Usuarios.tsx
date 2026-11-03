import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Loader,
  Menu,
  Modal,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from '@mantine/core'
import { IconDots, IconPlus, IconSearch } from '@tabler/icons-react'
import { useCallback, useEffect, useState } from 'react'
import { codigoDoErro, ConflitoNaApi, FalhaNaApi, PedidoInvalido, SessaoExpirada, type ClienteDaApi, type ContaDaLista } from './api.ts'
import type { Usuario } from './App.tsx'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import { CORES } from './tema.ts'

/** Os papéis do `api/papeis.py`, com o que cada um pode, na ordem em que a API os devolve. */
const PAPEIS = [
  { valor: 'consulta', nome: 'Consulta', pode: 'vê a decupagem' },
  { valor: 'operador', nome: 'Operador', pode: 'envia vídeos e reprocessa' },
  { valor: 'editor', nome: 'Editor', pode: 'vê e corrige a decupagem' },
  { valor: 'curador', nome: 'Curador', pode: 'aprova correções, reprocessa etapas e cuida do catálogo' },
  { valor: 'administrador', nome: 'Administrador', pode: 'gere contas, chaves, lixeira e auditoria' },
]

const NOME_DO_PAPEL = Object.fromEntries(PAPEIS.map((p) => [p.valor, p.nome]))
const TODOS = '__todos__'
const SEM_PERMISSAO = 'Você não tem permissão para isto.'

function ultimoAcesso(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo', dateStyle: 'short', timeStyle: 'short' })
}

/** A mensagem em português de uma falha da API; o código interno vai à parte. */
function falhaDaAcao(erro: unknown): { mensagem: string; codigo: string } {
  if (erro instanceof FalhaNaApi && erro.status === 403) return { mensagem: SEM_PERMISSAO, codigo: 'http_403' }
  if (erro instanceof ConflitoNaApi || erro instanceof PedidoInvalido) {
    return { mensagem: erro.message, codigo: codigoDoErro(erro) }
  }
  return { mensagem: 'Não foi possível concluir. Tente de novo.', codigo: codigoDoErro(erro) }
}

function CaixasDePapeis({
  marcados,
  aoMudar,
  travado,
}: {
  marcados: string[]
  aoMudar: (papeis: string[]) => void
  travado?: string
}) {
  return (
    <Stack gap="xs">
      {PAPEIS.map((p) => (
        <Checkbox
          key={p.valor}
          label={p.nome}
          description={`${p.nome}: ${p.pode}`}
          checked={marcados.includes(p.valor)}
          disabled={p.valor === travado}
          onChange={(e) =>
            aoMudar(PAPEIS.map((q) => q.valor).filter((v) => (v === p.valor ? e.currentTarget.checked : marcados.includes(v))))
          }
        />
      ))}
    </Stack>
  )
}

function NovaConta({
  aberta,
  aoFechar,
  aoSalvar,
}: {
  aberta: boolean
  aoFechar: () => void
  aoSalvar: (corpo: { email: string; nome: string; papeis: string[] }) => Promise<void>
}) {
  const [email, setEmail] = useState('')
  const [nome, setNome] = useState('')
  const [papeis, setPapeis] = useState<string[]>([])
  const [salvando, setSalvando] = useState(false)
  const [falha, setFalha] = useState<{ mensagem: string; codigo: string } | null>(null)
  const completa = email.trim() !== '' && nome.trim() !== ''

  async function salvar() {
    setSalvando(true)
    setFalha(null)
    try {
      await aoSalvar({ email: email.trim(), nome: nome.trim(), papeis })
      setEmail('')
      setNome('')
      setPapeis([])
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro))
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Modal opened={aberta} onClose={aoFechar} title="Nova conta">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (completa && !salvando) void salvar()
        }}
      >
        <Stack gap="sm">
          <TextInput label="E-mail" type="email" value={email} onChange={(e) => setEmail(e.currentTarget.value)} data-autofocus />
          <TextInput label="Nome" value={nome} onChange={(e) => setNome(e.currentTarget.value)} />
          <Text size="sm" fw={500}>
            Papéis
          </Text>
          <CaixasDePapeis marcados={papeis} aoMudar={setPapeis} />
          {falha && <AlertaDeErro mensagem={falha.mensagem} codigo={falha.codigo} />}
          <Group justify="flex-end">
            <Button type="button" variant="default" onClick={aoFechar}>
              Cancelar
            </Button>
            <Button type="submit" disabled={!completa} loading={salvando}>
              Criar conta
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  )
}

function EditarPapeis({
  conta,
  propria,
  aoFechar,
  aoSalvar,
}: {
  conta: ContaDaLista
  propria: boolean
  aoFechar: () => void
  aoSalvar: (papeis: string[]) => Promise<void>
}) {
  const [papeis, setPapeis] = useState(conta.papeis)
  const [salvando, setSalvando] = useState(false)
  const [falha, setFalha] = useState<{ mensagem: string; codigo: string } | null>(null)
  const travado = propria && conta.papeis.includes('administrador') ? 'administrador' : undefined

  async function salvar() {
    setSalvando(true)
    setFalha(null)
    try {
      await aoSalvar(papeis)
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro))
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Modal opened onClose={aoFechar} title={`Papéis de ${conta.nome}`}>
      <Stack gap="sm">
        <CaixasDePapeis marcados={papeis} aoMudar={setPapeis} travado={travado} />
        {travado && (
          <Text size="xs" c={CORES.textoSecundario}>
            Você não pode tirar o seu próprio papel de Administrador.
          </Text>
        )}
        {falha && <AlertaDeErro mensagem={falha.mensagem} codigo={falha.codigo} />}
        <Group justify="flex-end">
          <Button type="button" variant="default" onClick={aoFechar}>
            Cancelar
          </Button>
          <Button type="button" loading={salvando} onClick={() => void salvar()}>
            Salvar
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

type Carga = { tipo: 'carregando' } | { tipo: 'pronta' } | { tipo: 'erro'; mensagem: string; codigo: string }

/** `/admin/usuarios`: contas e papéis, em tabela densa (docs/design/administracao.md). */
export default function Usuarios({ api, eu }: { api: ClienteDaApi; eu: Usuario }) {
  const [contas, setContas] = useState<ContaDaLista[]>([])
  const [carga, setCarga] = useState<Carga>({ tipo: 'carregando' })
  const [busca, setBusca] = useState('')
  const [papel, setPapel] = useState(TODOS)
  const [situacao, setSituacao] = useState(TODOS)
  const [criando, setCriando] = useState(false)
  const [editando, setEditando] = useState<string | null>(null)
  const [desativando, setDesativando] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [falha, setFalha] = useState<{ mensagem: string; codigo: string } | null>(null)

  const carregar = useCallback(async () => {
    setCarga({ tipo: 'carregando' })
    try {
      setContas(await api.usuarios.listar())
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

  function trocar(nova: ContaDaLista) {
    setContas((atuais) => atuais.map((c) => (c.uid === nova.uid ? nova : c)))
  }

  /** Roda uma ação da linha: sucesso avisa, falha mostra a mensagem sem derrubar a tela. */
  async function agir(acao: () => Promise<string>) {
    setAviso(null)
    setFalha(null)
    try {
      setAviso(await acao())
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro))
    }
  }

  const termo = busca.trim().toLowerCase()
  const visiveis = contas.filter(
    (c) =>
      (!termo || c.nome.toLowerCase().includes(termo) || c.email.toLowerCase().includes(termo)) &&
      (papel === TODOS || c.papeis.includes(papel)) &&
      (situacao === TODOS || c.situacao === situacao),
  )
  const emEdicao = contas.find((c) => c.uid === editando)

  return (
    <Stack gap="sm">
      <Group gap="sm">
        <TextInput
          aria-label="Buscar por nome ou e-mail"
          placeholder="Buscar por nome ou e-mail…"
          size="xs"
          w={280}
          leftSection={<IconSearch size={14} aria-hidden />}
          value={busca}
          onChange={(e) => setBusca(e.currentTarget.value)}
        />
        <Select
          aria-label="Papel"
          size="xs"
          w={180}
          allowDeselect={false}
          data={[{ value: TODOS, label: 'Todos os papéis' }, ...PAPEIS.map((p) => ({ value: p.valor, label: p.nome }))]}
          value={papel}
          onChange={(v) => setPapel(v ?? TODOS)}
        />
        <Select
          aria-label="Situação"
          size="xs"
          w={160}
          allowDeselect={false}
          data={[
            { value: TODOS, label: 'Todas as situações' },
            { value: 'ativa', label: 'Ativa' },
            { value: 'desativada', label: 'Desativada' },
          ]}
          value={situacao}
          onChange={(v) => setSituacao(v ?? TODOS)}
        />
        <Button type="button" size="xs" leftSection={<IconPlus size={14} />} ml="auto" onClick={() => setCriando(true)}>
          Nova conta
        </Button>
      </Group>
      {aviso && (
        <Alert color={CORES.concluido} variant="light" role="status">
          {aviso}
        </Alert>
      )}
      {falha && <AlertaDeErro mensagem={falha.mensagem} codigo={falha.codigo} />}
      {carga.tipo === 'carregando' && <Loader role="status" aria-label="Carregando as contas" size="sm" />}
      {carga.tipo === 'erro' && <AlertaDeErro mensagem={carga.mensagem} codigo={carga.codigo} aoTentar={() => void carregar()} />}
      {carga.tipo === 'pronta' && (
        <Table aria-label="Usuários" highlightOnHover verticalSpacing={4}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Nome</Table.Th>
              <Table.Th>E-mail</Table.Th>
              <Table.Th>Papéis</Table.Th>
              <Table.Th>Último acesso</Table.Th>
              <Table.Th>Situação</Table.Th>
              <Table.Th>
                <span style={{ position: 'absolute', left: -9999 }}>Ações</span>
              </Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {visiveis.map((c) => {
              const propria = c.uid === eu.uid
              const desativada = c.situacao === 'desativada'
              return (
                <LinhaDaConta
                  key={c.uid}
                  conta={c}
                  propria={propria}
                  desativando={desativando === c.uid}
                  aoEditar={() => setEditando(c.uid)}
                  aoReenviar={() =>
                    void agir(async () => {
                      await api.usuarios.reenviarLink(c.uid)
                      return `Link de senha reenviado para ${c.email}.`
                    })
                  }
                  aoPedirDesativar={() => setDesativando(c.uid)}
                  aoCancelar={() => setDesativando(null)}
                  aoDesativar={() => {
                    setDesativando(null)
                    void agir(async () => {
                      trocar(await api.usuarios.desativar(c.uid))
                      return `${c.nome} foi desativada e saiu do sistema.`
                    })
                  }}
                  aoReativar={() =>
                    void agir(async () => {
                      trocar(await api.usuarios.reativar(c.uid))
                      return `${c.nome} foi reativada.`
                    })
                  }
                  desativada={desativada}
                />
              )
            })}
          </Table.Tbody>
        </Table>
      )}
      {carga.tipo === 'pronta' && visiveis.length === 0 && <Text size="sm">Nenhuma conta neste filtro.</Text>}
      <NovaConta
        aberta={criando}
        aoFechar={() => setCriando(false)}
        aoSalvar={async (corpo) => {
          const nova = await api.usuarios.criar(corpo)
          setContas((atuais) => [...atuais, nova])
          setCriando(false)
          setFalha(null)
          setAviso(`Conta criada. O link para definir a senha foi enviado para ${nova.email}.`)
        }}
      />
      {emEdicao && (
        <EditarPapeis
          key={emEdicao.uid}
          conta={emEdicao}
          propria={emEdicao.uid === eu.uid}
          aoFechar={() => setEditando(null)}
          aoSalvar={async (papeis) => {
            trocar(await api.usuarios.trocarPapeis(emEdicao.uid, papeis))
            setEditando(null)
            setFalha(null)
            setAviso(`Papéis de ${emEdicao.nome} atualizados.`)
          }}
        />
      )}
    </Stack>
  )
}

function LinhaDaConta({
  conta,
  propria,
  desativada,
  desativando,
  aoEditar,
  aoReenviar,
  aoPedirDesativar,
  aoCancelar,
  aoDesativar,
  aoReativar,
}: {
  conta: ContaDaLista
  propria: boolean
  desativada: boolean
  desativando: boolean
  aoEditar: () => void
  aoReenviar: () => void
  aoPedirDesativar: () => void
  aoCancelar: () => void
  aoDesativar: () => void
  aoReativar: () => void
}) {
  return (
    <>
      <Table.Tr>
        <Table.Td>{conta.nome}</Table.Td>
        <Table.Td>{conta.email}</Table.Td>
        <Table.Td>{conta.papeis.map((p) => NOME_DO_PAPEL[p] ?? p).sort().join(', ') || '—'}</Table.Td>
        <Table.Td style={{ fontVariantNumeric: 'tabular-nums' }}>{ultimoAcesso(conta.ultimo_acesso)}</Table.Td>
        <Table.Td>
          <Badge variant="light" color={desativada ? CORES.falhou : CORES.concluido} radius="sm">
            {desativada ? 'Desativada' : 'Ativa'}
          </Badge>
        </Table.Td>
        <Table.Td>
          <Menu position="bottom-end">
            <Menu.Target>
              <Button type="button" variant="subtle" color="gray" size="compact-sm" aria-label={`Ações de ${conta.nome}`}>
                <IconDots size={16} aria-hidden />
              </Button>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item onClick={aoEditar}>Editar papéis</Menu.Item>
              <Menu.Item onClick={aoReenviar}>Reenviar link de senha</Menu.Item>
              {desativada ? (
                <Menu.Item onClick={aoReativar}>Reativar</Menu.Item>
              ) : (
                <>
                  <Menu.Item disabled={propria} onClick={aoPedirDesativar}>
                    Desativar
                  </Menu.Item>
                  {propria && <Menu.Label>Você não pode desativar a própria conta.</Menu.Label>}
                </>
              )}
            </Menu.Dropdown>
          </Menu>
        </Table.Td>
      </Table.Tr>
      {desativando && (
        <Table.Tr
          onKeyDown={(e) => {
            if (e.key === 'Escape') aoCancelar()
          }}
        >
          <Table.Td colSpan={6}>
            <Group gap="sm">
              <Text size="sm">{`Desativar ${conta.nome}? A conta sai na hora. Enter confirma`}</Text>
              <Button type="button" size="compact-sm" color={CORES.falhou} autoFocus onClick={aoDesativar} aria-label="Confirmar desativação">
                Desativar
              </Button>
              <Button type="button" size="compact-sm" variant="default" onClick={aoCancelar}>
                Cancelar
              </Button>
            </Group>
          </Table.Td>
        </Table.Tr>
      )}
    </>
  )
}
