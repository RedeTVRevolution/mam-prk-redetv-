import { Button, Center, Group, Loader, Select, Stack, Table, Text, TextInput } from '@mantine/core'
import { IconX } from '@tabler/icons-react'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { codigoDoErro, SessaoExpirada, type ClienteDaApi } from './api.ts'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import { useAtalhos, type Atalho } from './atalhos.ts'
import {
  ACOES_DA_AUDITORIA,
  ACOES_DE_ACESSO,
  FILTRO_DE_ACESSOS,
  autorDoRegistro,
  detalhesEmFrases,
  FRASE_DA_ACAO,
  fraseDaAcao,
  haFiltroDaAuditoria,
  periodoInvertido,
  SEM_FILTROS_DA_AUDITORIA,
  type FiltrosDaAuditoria,
  type RegistroDeAuditoria,
} from './auditoria.ts'
import { dataEHora } from './jobs.ts'
import { enderecoDaAuditoria, navegar } from './rotas.ts'
import { CORES } from './tema.ts'

const POR_PAGINA = 50
const TODAS = '__todas__'
const NUMEROS = { fontVariantNumeric: 'tabular-nums' } as const

const ATALHOS: Atalho[] = [{ tecla: 'Enter', acao: 'Na tabela: mostrar ou esconder os detalhes da linha', grupo: 'Auditoria' }]

type Carga =
  | { tipo: 'carregando' }
  | { tipo: 'pronta'; registros: RegistroDeAuditoria[]; proximo: string | null }
  | { tipo: 'erro'; codigo: string }

function irPara(filtros: FiltrosDaAuditoria) {
  navegar(enderecoDaAuditoria(filtros), { substituir: true })
}

function Detalhes({ registro }: { registro: RegistroDeAuditoria }) {
  const frases = detalhesEmFrases(registro)
  if (frases.length === 0) return <Text size="sm" c={CORES.textoSecundario}>Sem detalhes para este registro.</Text>
  return (
    <Stack gap={2}>
      {frases.map((f) => (
        <Text key={f} size="sm">
          {f}
        </Text>
      ))}
    </Stack>
  )
}

function Linha({ registro, aberta, aoAlternar }: { registro: RegistroDeAuditoria; aberta: boolean; aoAlternar: () => void }) {
  function aoTeclar(e: KeyboardEvent<HTMLTableRowElement>) {
    if (e.target !== e.currentTarget || e.key !== 'Enter') return
    e.preventDefault()
    aoAlternar()
  }
  return (
    <Table.Tr tabIndex={0} aria-expanded={aberta} onClick={aoAlternar} onKeyDown={aoTeclar} style={{ cursor: 'pointer' }}>
      <Table.Td style={{ ...NUMEROS, whiteSpace: 'nowrap' }}>{dataEHora(registro.quando)}</Table.Td>
      <Table.Td maw={240}>
        <Text size="sm" truncate>
          {autorDoRegistro(registro)}
        </Text>
      </Table.Td>
      <Table.Td>{fraseDaAcao(registro.acao)}</Table.Td>
      <Table.Td maw={320}>
        <Text size="sm" truncate>
          {registro.alvo_nome}
        </Text>
      </Table.Td>
      <Table.Td maw={280}>{registro.motivo ?? '—'}</Table.Td>
    </Table.Tr>
  )
}

/** `/admin/auditoria`: o que a administração fez, só de leitura. */
export default function Auditoria({ api, filtros }: { api: ClienteDaApi; filtros: FiltrosDaAuditoria }) {
  const [carga, setCarga] = useState<Carga>({ tipo: 'carregando' })
  const [recarga, setRecarga] = useState(0)
  const [carregandoMais, setCarregandoMais] = useState(false)
  const [maisFalhou, setMaisFalhou] = useState<string | null>(null)
  const [abertas, setAbertas] = useState<string[]>([])
  useAtalhos(ATALHOS)

  const chave = JSON.stringify(filtros)
  const filtrosAtuais = useRef(filtros)
  useEffect(() => {
    filtrosAtuais.current = filtros
  })
  // Cada carga da lista abre uma geração; a resposta de uma anterior é descartada.
  const geracao = useRef(0)

  const invertido = periodoInvertido(filtros)

  useEffect(() => {
    let ativo = true
    geracao.current += 1
    // Recomeça a lista quando um filtro muda; a página seguinte em voo é da lista anterior.
    // oxlint-disable-next-line react/set-state-in-effect
    setCarregandoMais(false)
    // oxlint-disable-next-line react/set-state-in-effect
    setMaisFalhou(null)
    if (invertido) return
    // oxlint-disable-next-line react/set-state-in-effect
    setCarga({ tipo: 'carregando' })
    api.auditoria(filtrosAtuais.current, POR_PAGINA).then(
      (pagina) => {
        if (ativo) setCarga({ tipo: 'pronta', ...pagina })
      },
      (erro: unknown) => {
        if (ativo && !(erro instanceof SessaoExpirada)) setCarga({ tipo: 'erro', codigo: codigoDoErro(erro) })
      },
    )
    return () => {
      ativo = false
    }
  }, [api, chave, recarga, invertido])

  async function carregarMais() {
    if (carga.tipo !== 'pronta' || !carga.proximo || carregandoMais) return
    const daVez = geracao.current
    setCarregandoMais(true)
    setMaisFalhou(null)
    try {
      const pagina = await api.auditoria(filtros, POR_PAGINA, carga.proximo)
      if (geracao.current !== daVez) return
      setCarga((c) => (c.tipo === 'pronta' ? { tipo: 'pronta', registros: [...c.registros, ...pagina.registros], proximo: pagina.proximo } : c))
    } catch (erro) {
      if (geracao.current === daVez && !(erro instanceof SessaoExpirada)) setMaisFalhou(codigoDoErro(erro))
    } finally {
      if (geracao.current === daVez) setCarregandoMais(false)
    }
  }

  function alternar(id: string) {
    setAbertas((atuais) => (atuais.includes(id) ? atuais.filter((a) => a !== id) : [...atuais, id]))
  }

  const mudar = (parte: Partial<FiltrosDaAuditoria>) => irPara({ ...filtros, ...parte })
  const registros = carga.tipo === 'pronta' ? carga.registros : []

  return (
    <Stack gap="sm">
      <Group gap="sm" wrap="wrap" align="flex-end">
        <TextInput aria-label="Pessoa" placeholder="E-mail da pessoa" size="xs" w={220} value={filtros.pessoa} onChange={(e) => mudar({ pessoa: e.currentTarget.value })} />
        <TextInput aria-label="Alvo" placeholder="Código do alvo (ex.: um vídeo)" size="xs" w={240} value={filtros.alvo} onChange={(e) => mudar({ alvo: e.currentTarget.value })} />
        <Select
          aria-label="Ação"
          size="xs"
          w={220}
          allowDeselect={false}
          data={[
            { value: TODAS, label: 'Todas as ações' },
            ...ACOES_DA_AUDITORIA.filter((a) => !ACOES_DE_ACESSO.includes(a)).map((a) => ({ value: a, label: FRASE_DA_ACAO[a] })),
            {
              group: 'Acessos',
              items: [
                { value: FILTRO_DE_ACESSOS, label: 'Todos os acessos' },
                ...ACOES_DE_ACESSO.map((a) => ({ value: a, label: FRASE_DA_ACAO[a] })),
              ],
            },
          ]}
          value={filtros.acao || TODAS}
          onChange={(valor) => mudar({ acao: valor && valor !== TODAS ? valor : '' })}
        />
        <TextInput type="date" aria-label="De" size="xs" value={filtros.de} onChange={(e) => mudar({ de: e.currentTarget.value })} />
        <TextInput type="date" aria-label="Até" size="xs" value={filtros.ate} onChange={(e) => mudar({ ate: e.currentTarget.value })} />
        {haFiltroDaAuditoria(filtros) && (
          <Button type="button" variant="subtle" color="gray" size="compact-sm" leftSection={<IconX size={14} aria-hidden />} onClick={() => irPara(SEM_FILTROS_DA_AUDITORIA)}>
            Limpar filtros
          </Button>
        )}
      </Group>
      {maisFalhou !== null && <AlertaDeErro mensagem="Não foi possível carregar mais registros. Tente de novo." codigo={maisFalhou} aoTentar={() => void carregarMais()} />}
      {invertido && <Text size="sm">A data em "De" é depois da data em "Até". Troque uma das duas para ver os registros.</Text>}
      {!invertido && carga.tipo === 'carregando' && (
        <Center py="xl">
          <Loader role="status" aria-label="Carregando a auditoria" size="sm" />
        </Center>
      )}
      {!invertido && carga.tipo === 'erro' && <AlertaDeErro mensagem="Não foi possível carregar a auditoria. Tente de novo." codigo={carga.codigo} aoTentar={() => setRecarga((n) => n + 1)} />}
      {!invertido && carga.tipo === 'pronta' && registros.length === 0 && (
        <Text size="sm">{haFiltroDaAuditoria(filtros) ? 'Nenhum registro com esses filtros.' : 'Nenhum registro ainda.'}</Text>
      )}
      {!invertido && carga.tipo === 'pronta' && registros.length > 0 && (
        <Table aria-label="Auditoria" highlightOnHover verticalSpacing={4}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Quando</Table.Th>
              <Table.Th>Quem</Table.Th>
              <Table.Th>Ação</Table.Th>
              <Table.Th>Alvo</Table.Th>
              <Table.Th>Motivo</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {registros.flatMap((r) => {
              const aberta = abertas.includes(r.id)
              return [
                <Linha key={r.id} registro={r} aberta={aberta} aoAlternar={() => alternar(r.id)} />,
                aberta && (
                  <Table.Tr key={`${r.id}:detalhes`}>
                    <Table.Td colSpan={5}>
                      <Detalhes registro={r} />
                    </Table.Td>
                  </Table.Tr>
                ),
              ]
            })}
          </Table.Tbody>
        </Table>
      )}
      {!invertido && carga.tipo === 'pronta' && carga.proximo !== null && (
        <Group justify="center">
          <Button type="button" size="xs" variant="default" loading={carregandoMais} onClick={() => void carregarMais()}>
            Carregar mais
          </Button>
        </Group>
      )}
    </Stack>
  )
}
