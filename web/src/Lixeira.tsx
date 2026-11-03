import {
  Alert,
  Button,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  VisuallyHidden,
} from '@mantine/core'
import { useCallback, useEffect, useState } from 'react'
import { LoginRecenteExigido, SessaoExpirada, type ClienteDaApi, type ItemDaLixeira, type TipoDeItem } from './api.ts'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import { falhaDaAcao, type Falha } from './falhaDaAcao.ts'
import { frasesDoImpacto, purgaEm, rotuloDoTipo } from './lixeira.ts'
import { CORES } from './tema.ts'

const TUDO = '__tudo__'
// A purga que pediu um login novo: ao voltar, a tela reabre o diálogo dela.
const PURGA_PENDENTE = 'mam:purga-pendente'

function quando(iso: string): string {
  return new Date(iso)
    .toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
    .replace(',', '')
}

function pendente(): { tipo: string; id: string } | null {
  try {
    return JSON.parse(sessionStorage.getItem(PURGA_PENDENTE) ?? 'null') as { tipo: string; id: string } | null
  } catch {
    return null
  }
}

function PurgarAgora({
  api,
  item,
  aoFechar,
  aoPurgar,
  aoEntrarDeNovo,
}: {
  api: ClienteDaApi
  item: ItemDaLixeira
  aoFechar: () => void
  aoPurgar: () => void
  aoEntrarDeNovo: () => void
}) {
  const tipo = item.tipo as TipoDeItem
  const [frases, setFrases] = useState<string[] | null>(null)
  const [nome, setNome] = useState('')
  const [purgando, setPurgando] = useState(false)
  const [precisaLogin, setPrecisaLogin] = useState(false)
  const [falha, setFalha] = useState<Falha | null>(null)

  useEffect(() => {
    let ativo = true
    api.lixeira.impacto(tipo, item.id).then(
      (i) => ativo && setFrases(frasesDoImpacto(tipo, i)),
      (erro: unknown) => {
        if (ativo && !(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, 'Não foi possível calcular o que vai junto. Tente de novo.'))
      },
    )
    return () => {
      ativo = false
    }
  }, [api, tipo, item.id])

  async function purgar() {
    setPurgando(true)
    setFalha(null)
    try {
      await api.lixeira.purgar(tipo, item.id, nome)
      sessionStorage.removeItem(PURGA_PENDENTE)
      aoPurgar()
    } catch (erro) {
      if (erro instanceof LoginRecenteExigido) setPrecisaLogin(true)
      else if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, `Não foi possível purgar ${item.nome}. Tente de novo.`))
    } finally {
      setPurgando(false)
    }
  }

  function entrarDeNovo() {
    sessionStorage.setItem(PURGA_PENDENTE, JSON.stringify({ tipo: item.tipo, id: item.id }))
    aoEntrarDeNovo()
  }

  return (
    <Modal opened onClose={purgando ? () => {} : aoFechar} title={`Purgar ${item.nome}`} closeOnEscape={!purgando} closeOnClickOutside={!purgando} withCloseButton={!purgando}>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (nome === item.nome && !purgando && !precisaLogin) void purgar()
        }}
      >
        <Stack gap="sm">
          <Text size="sm">A purga apaga de vez e não tem volta.</Text>
          {frases === null && !falha && <Loader size="sm" role="status" aria-label="Calculando o que vai junto" />}
          {frases?.map((f) => (
            <Text key={f} size="sm">
              {f}
            </Text>
          ))}
          {precisaLogin ? (
            <Alert color="gray" variant="light" role="alert">
              <Stack gap="xs">
                <Text size="sm">Para purgar, é preciso um login recente com o autenticador. Entre de novo e este diálogo volta aberto.</Text>
                <Group>
                  <Button type="button" size="xs" onClick={entrarDeNovo}>
                    Entrar de novo
                  </Button>
                </Group>
              </Stack>
            </Alert>
          ) : (
            <>
              <TextInput label={`Digite o nome do item para confirmar: ${item.nome}`} value={nome} onChange={(e) => setNome(e.currentTarget.value)} data-autofocus />
              {falha && <AlertaDeErro mensagem={falha.mensagem} codigo={falha.codigo} />}
              <Group justify="flex-end">
                <Button type="button" variant="default" onClick={aoFechar} disabled={purgando}>
                  Cancelar
                </Button>
                <Button type="submit" color={CORES.falhou} disabled={nome !== item.nome} loading={purgando}>
                  Purgar
                </Button>
              </Group>
            </>
          )}
        </Stack>
      </form>
    </Modal>
  )
}

type Carga = { tipo: 'carregando' } | { tipo: 'pronta' } | { tipo: 'erro'; mensagem: string; codigo: string }

/** `/admin/lixeira`: restaurar e purgar (docs/design/administracao.md, "Apagar com segurança"). */
export default function Lixeira({ api, aoEntrarDeNovo }: { api: ClienteDaApi; aoEntrarDeNovo: () => void }) {
  const [itens, setItens] = useState<ItemDaLixeira[]>([])
  const [carga, setCarga] = useState<Carga>({ tipo: 'carregando' })
  const [filtro, setFiltro] = useState(TUDO)
  const [restaurando, setRestaurando] = useState<string | null>(null)
  const [purgando, setPurgando] = useState<ItemDaLixeira | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [falha, setFalha] = useState<Falha | null>(null)

  const carregar = useCallback(async () => {
    setCarga({ tipo: 'carregando' })
    try {
      const lista = await api.lixeira.listar()
      setItens(lista)
      const volta = pendente()
      if (volta) setPurgando(lista.find((i) => i.tipo === volta.tipo && i.id === volta.id) ?? null)
      sessionStorage.removeItem(PURGA_PENDENTE)
      setCarga({ tipo: 'pronta' })
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setCarga({ tipo: 'erro', ...falhaDaAcao(erro, 'Não foi possível carregar a lixeira. Tente de novo.') })
    }
  }, [api])

  useEffect(() => {
    // Sincroniza com a API, um sistema externo.
    // oxlint-disable-next-line react/set-state-in-effect
    void carregar()
  }, [carregar])

  const tipos = [...new Set(itens.map((i) => i.tipo))]
  const filtroAtual = tipos.includes(filtro) ? filtro : TUDO
  const visiveis = itens.filter((i) => filtroAtual === TUDO || i.tipo === filtroAtual)

  function sair(item: ItemDaLixeira, frase: string) {
    setItens((atuais) => atuais.filter((i) => !(i.tipo === item.tipo && i.id === item.id)))
    setAviso(frase)
  }

  async function restaurar(item: ItemDaLixeira) {
    setRestaurando(null)
    setAviso(null)
    setFalha(null)
    try {
      await api.lixeira.restaurar(item.tipo as TipoDeItem, item.id)
      sair(item, `${item.nome} voltou.`)
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, `Não foi possível restaurar ${item.nome}. Tente de novo.`))
    }
  }

  return (
    <Stack gap="sm">
      <Group gap="sm">
        <Select
          aria-label="Tipo"
          size="xs"
          w={160}
          ml="auto"
          allowDeselect={false}
          data={[{ value: TUDO, label: 'Tudo' }, ...tipos.map((t) => ({ value: t, label: rotuloDoTipo(t) }))]}
          value={filtroAtual}
          onChange={(v) => setFiltro(v ?? TUDO)}
        />
      </Group>
      {aviso && (
        <Alert color={CORES.concluido} variant="light" role="status">
          {aviso}
        </Alert>
      )}
      {falha && <AlertaDeErro mensagem={falha.mensagem} codigo={falha.codigo} />}
      {carga.tipo === 'carregando' && <Loader role="status" aria-label="Carregando a lixeira" size="sm" />}
      {carga.tipo === 'erro' && <AlertaDeErro mensagem={carga.mensagem} codigo={carga.codigo} aoTentar={() => void carregar()} />}
      {carga.tipo === 'pronta' && visiveis.length > 0 && (
        <Table aria-label="Lixeira" highlightOnHover verticalSpacing={4}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Item</Table.Th>
              <Table.Th>Tipo</Table.Th>
              <Table.Th>Apagado por</Table.Th>
              <Table.Th>Em</Table.Th>
              <Table.Th>Purga em</Table.Th>
              <Table.Th>Motivo</Table.Th>
              <Table.Th>
                <VisuallyHidden>Ações</VisuallyHidden>
              </Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {visiveis.map((item) => (
              <LinhaDoItem
                key={`${item.tipo}/${item.id}`}
                item={item}
                restaurando={restaurando === `${item.tipo}/${item.id}`}
                aoPedirRestaurar={() => setRestaurando(`${item.tipo}/${item.id}`)}
                aoCancelar={() => setRestaurando(null)}
                aoRestaurar={() => void restaurar(item)}
                aoPurgar={() => {
                  setAviso(null)
                  setPurgando(item)
                }}
              />
            ))}
          </Table.Tbody>
        </Table>
      )}
      {carga.tipo === 'pronta' && itens.length === 0 && <Text size="sm">A lixeira está vazia.</Text>}
      {carga.tipo === 'pronta' && itens.length > 0 && visiveis.length === 0 && <Text size="sm">Nada deste tipo na lixeira.</Text>}
      {purgando && (
        <PurgarAgora
          api={api}
          item={purgando}
          aoFechar={() => setPurgando(null)}
          aoPurgar={() => {
            sair(purgando, `${purgando.nome} foi purgad${purgando.tipo === 'video' ? 'o' : 'a'}.`)
            setPurgando(null)
          }}
          aoEntrarDeNovo={aoEntrarDeNovo}
        />
      )}
    </Stack>
  )
}

function LinhaDoItem({
  item,
  restaurando,
  aoPedirRestaurar,
  aoCancelar,
  aoRestaurar,
  aoPurgar,
}: {
  item: ItemDaLixeira
  restaurando: boolean
  aoPedirRestaurar: () => void
  aoCancelar: () => void
  aoRestaurar: () => void
  aoPurgar: () => void
}) {
  return (
    <>
      <Table.Tr>
        <Table.Td>{item.nome}</Table.Td>
        <Table.Td>{rotuloDoTipo(item.tipo)}</Table.Td>
        <Table.Td>{item.enviado_por}</Table.Td>
        <Table.Td style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>{quando(item.enviado_em)}</Table.Td>
        <Table.Td style={{ whiteSpace: 'nowrap' }}>{purgaEm(item.dias_ate_a_purga)}</Table.Td>
        <Table.Td>{item.motivo}</Table.Td>
        <Table.Td>
          <Group gap="xs" wrap="nowrap">
            <Button type="button" size="compact-xs" variant="default" aria-label={`Restaurar ${item.nome}`} onClick={aoPedirRestaurar}>
              Restaurar
            </Button>
            <Button type="button" size="compact-xs" variant="outline" color={CORES.falhou} aria-label={`Purgar agora ${item.nome}`} onClick={aoPurgar}>
              Purgar agora…
            </Button>
          </Group>
        </Table.Td>
      </Table.Tr>
      {restaurando && (
        <Table.Tr
          onKeyDown={(e) => {
            if (e.key === 'Escape') aoCancelar()
          }}
        >
          <Table.Td colSpan={7}>
            <Group gap="sm">
              <Text size="sm">{`Restaurar ${item.nome}? Volta tudo como estava.`}</Text>
              <Button type="button" size="xs" autoFocus onClick={aoRestaurar} aria-label="Confirmar restauração">
                Restaurar
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
