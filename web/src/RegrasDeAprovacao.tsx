import { Loader, Stack, Switch, Table, Text } from '@mantine/core'
import { useCallback, useEffect, useState } from 'react'
import { SessaoExpirada, type ClienteDaApi, type RegraDeAprovacao } from './api.ts'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import { falhaDaAcao, type Falha } from './falhaDaAcao.ts'
import { CORES } from './tema.ts'

type Carga = { tipo: 'carregando' } | { tipo: 'pronta' } | { tipo: 'erro'; mensagem: string; codigo: string }

/** `/admin/aprovacao`: quais tipos de correção esperam o Curador (docs/design/administracao.md). */
export default function RegrasDeAprovacao({ api }: { api: ClienteDaApi }) {
  const [regras, setRegras] = useState<RegraDeAprovacao[]>([])
  const [carga, setCarga] = useState<Carga>({ tipo: 'carregando' })
  const [mudando, setMudando] = useState<string | null>(null)
  const [falha, setFalha] = useState<Falha | null>(null)

  const carregar = useCallback(async () => {
    setCarga({ tipo: 'carregando' })
    try {
      setRegras(await api.aprovacao.listar())
      setCarga({ tipo: 'pronta' })
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setCarga({ tipo: 'erro', ...falhaDaAcao(erro, 'Não foi possível carregar as regras de aprovação. Tente de novo.') })
    }
  }, [api])

  useEffect(() => {
    // Sincroniza com a API, um sistema externo.
    // oxlint-disable-next-line react/set-state-in-effect
    void carregar()
  }, [carregar])

  async function mudar(regra: RegraDeAprovacao, exige: boolean) {
    setMudando(regra.tipo)
    setFalha(null)
    try {
      setRegras(await api.aprovacao.mudar(regra.tipo, exige))
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, `Não foi possível mudar a regra de ${regra.nome}. Tente de novo.`))
    } finally {
      setMudando(null)
    }
  }

  return (
    <Stack gap="sm">
      <Text size="sm" c={CORES.textoSecundario}>
        Nos tipos ligados, a correção de um Editor espera a decisão de um Curador. A mudança vale na hora para as correções novas; as pendentes continuam pendentes.
      </Text>
      {falha && <AlertaDeErro mensagem={falha.mensagem} codigo={falha.codigo} />}
      {carga.tipo === 'carregando' && <Loader role="status" aria-label="Carregando as regras" size="sm" />}
      {carga.tipo === 'erro' && <AlertaDeErro mensagem={carga.mensagem} codigo={carga.codigo} aoTentar={() => void carregar()} />}
      {carga.tipo === 'pronta' && (
        <Table aria-label="Regras de aprovação" highlightOnHover verticalSpacing={4}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Tipo de correção</Table.Th>
              <Table.Th>Exige aprovação do Curador</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {regras.map((r) => (
              <Table.Tr key={r.tipo}>
                <Table.Td>{r.nome}</Table.Td>
                <Table.Td>
                  <Switch
                    aria-label={`Exigir aprovação para ${r.nome}`}
                    checked={r.exige_aprovacao}
                    disabled={mudando !== null}
                    onChange={(e) => void mudar(r, e.currentTarget.checked)}
                  />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  )
}
