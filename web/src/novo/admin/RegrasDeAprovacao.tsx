import { IconChecklist } from '@tabler/icons-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { cn } from 'cn'
import { useState } from 'react'
import { SessaoExpirada, codigoDoErro, type RegraDeAprovacao } from '../../api.ts'
import { falhaDaAcao, type Falha } from '../../falhaDaAcao.ts'
import { useApi } from '../consultas.ts'
import { Aba, CABECALHO, CELULA, Carregando, Erro, TABELA, TopoDaAba, Vazio } from './comum.tsx'
import { gravarNaLista } from './listas.ts'

const CHAVE = ['admin', 'aprovacao']

/** A chave liga-desliga: a caixa nativa com papel de switch, desenhada como trilho e botão. */
const CHAVE_LIGA =
  "relative h-5 w-9 shrink-0 cursor-pointer appearance-none rounded-full bg-input transition-colors outline-none before:absolute before:top-0.5 before:left-0.5 before:size-4 before:rounded-full before:bg-muted-foreground before:transition-transform before:content-[''] checked:bg-primary checked:before:translate-x-4 checked:before:bg-primary-foreground focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-default disabled:opacity-50"

/** `/admin/aprovacao`: quais tipos de correção esperam o Curador (docs/design/administracao.md). */
export default function RegrasDeAprovacao() {
  const api = useApi()
  const consultas = useQueryClient()
  const carga = useQuery({ queryKey: CHAVE, queryFn: () => api.aprovacao.listar() })
  const [mudando, setMudando] = useState<string | null>(null)
  const [falha, setFalha] = useState<Falha | null>(null)
  const regras = carga.data ?? []

  async function mudar(regra: RegraDeAprovacao, exige: boolean) {
    setMudando(regra.tipo)
    setFalha(null)
    try {
      const novas = await api.aprovacao.mudar(regra.tipo, exige)
      await gravarNaLista(consultas, CHAVE, () => novas)
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) setFalha(falhaDaAcao(erro, `Não foi possível mudar a regra de ${regra.nome}. Tente de novo.`))
    } finally {
      setMudando(null)
    }
  }

  return (
    <Aba>
      <TopoDaAba titulo="Regras de aprovação" />
      <p className="max-w-3xl text-muted-foreground">
        Nos tipos ligados, a correção de um Editor espera a decisão de um Curador. A mudança vale na hora para as correções novas; as pendentes continuam pendentes.
      </p>
      {falha && <Erro mensagem={falha.mensagem} codigo={falha.codigo} />}
      {carga.isPending && <Carregando rotulo="Carregando as regras" />}
      {carga.isError && (
        <Erro mensagem="Não foi possível carregar as regras de aprovação. Tente de novo." codigo={codigoDoErro(carga.error)} aoTentar={() => void carga.refetch()} />
      )}
      {carga.isSuccess && regras.length === 0 && <Vazio Icone={IconChecklist}>Nenhum tipo de correção para configurar.</Vazio>}
      {carga.isSuccess && regras.length > 0 && (
        <table aria-label="Regras de aprovação" className={cn(TABELA, 'max-w-3xl')}>
          <thead>
            <tr>
              <th className={CABECALHO}>Tipo de correção</th>
              <th className={cn(CABECALHO, 'w-36 sm:w-56')}>Exige aprovação do Curador</th>
            </tr>
          </thead>
          <tbody>
            {regras.map((r) => (
              <tr key={r.tipo} className="hover:bg-card">
                <td className={cn(CELULA, 'truncate')}>{r.nome}</td>
                <td className={CELULA}>
                  <span className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      role="switch"
                      aria-label={`Exigir aprovação para ${r.nome}`}
                      className={CHAVE_LIGA}
                      checked={r.exige_aprovacao}
                      disabled={mudando !== null}
                      onChange={(e) => void mudar(r, e.currentTarget.checked)}
                    />
                    <span aria-hidden className={cn('text-xs', r.exige_aprovacao ? 'text-foreground' : 'text-muted-foreground')}>
                      {r.exige_aprovacao ? 'Sim' : 'Não'}
                    </span>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Aba>
  )
}
