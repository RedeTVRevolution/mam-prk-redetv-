import { Button, Group, Stack, Text, TextInput, Tooltip } from '@mantine/core'
import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import type { AndamentoDaRenomeacao, ClienteDaRenomeacao, ImpactoDaRenomeacao } from './api.ts'
import { falhaDaAcao } from './falhaDaAcao.ts'

const plural = (n: number, um: string, varios: string) => `${n} ${n === 1 ? um : varios}`

/** O efeito da renomeação, na frase que a pessoa lê antes de confirmar. */
function efeito(i: ImpactoDaRenomeacao): string {
  return `${i.nome_antigo} passa a ser ${i.nome_novo} em ${plural(i.videos, 'vídeo', 'vídeos')} (${i.momentos_afetados} momento${i.momentos_afetados === 1 ? '' : 's'}). Enter confirma · Esc cancela.`
}

function frase(a: AndamentoDaRenomeacao): string {
  if (a.estado === 'concluida') return `Pronto: ${a.nome_novo} em ${plural(a.total, 'vídeo', 'vídeos')}, busca atualizada.`
  if (a.estado === 'falhou')
    return `A busca ainda tem o nome antigo em ${plural(a.total - a.feitos, 'vídeo', 'vídeos')}. O nome novo já vale nas decupagens.`
  return `Atualizando a busca: ${a.feitos} de ${a.total} vídeos.`
}

/**
 * "Renomear em todos os vídeos" na linha da pessoa (Curador): o nome novo, a prévia do efeito, a confirmação
 * com Enter e o andamento da reindexação, com "Tentar de novo" se ela não terminou.
 */
export function RenomeacaoEmLote({
  pessoaId,
  nomeAtual,
  renomeacao,
  aoRenomear,
  aoFechar,
  intervaloMs = 1500,
}: {
  /** O id da pessoa no catálogo. */
  pessoaId: string
  nomeAtual: string
  renomeacao: ClienteDaRenomeacao
  /** Chamado quando o nome novo passa a valer, para a tela recarregar a Decupagem. */
  aoRenomear: () => void
  aoFechar: () => void
  intervaloMs?: number
}) {
  const [nome, setNome] = useState(nomeAtual)
  const [impacto, setImpacto] = useState<ImpactoDaRenomeacao | null>(null)
  const [andamento, setAndamento] = useState<AndamentoDaRenomeacao | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const raiz = useRef<HTMLFormElement>(null)

  useEffect(() => raiz.current?.querySelector('input')?.focus(), [])

  // Enquanto a busca é atualizada, pergunta de tempos em tempos até terminar ou falhar.
  const acompanhando = andamento?.estado === 'em_andamento'
  useEffect(() => {
    if (!acompanhando) return
    let ativo = true
    const id = setInterval(() => {
      renomeacao.andamento(pessoaId).then(
        (a) => ativo && setAndamento(a),
        () => undefined,
      )
    }, intervaloMs)
    return () => {
      ativo = false
      clearInterval(id)
    }
  }, [acompanhando, renomeacao, pessoaId, intervaloMs])

  function mudar(valor: string) {
    setNome(valor)
    setImpacto(null)
    setErro(null)
  }

  async function ver() {
    const novo = nome.trim()
    if (!novo || ocupado) return
    setOcupado(true)
    setErro(null)
    try {
      setImpacto(await renomeacao.previa(pessoaId, novo))
    } catch (e) {
      setErro(falhaDaAcao(e, 'Não foi possível calcular o efeito. Tente de novo.').mensagem)
    } finally {
      setOcupado(false)
    }
  }

  async function confirmar() {
    if (!impacto || ocupado) return
    setOcupado(true)
    setErro(null)
    try {
      await renomeacao.renomear(pessoaId, impacto.nome_novo)
      aoRenomear()
      setAndamento(await renomeacao.andamento(pessoaId))
    } catch (e) {
      setErro(falhaDaAcao(e, 'Não foi possível renomear. Tente de novo.').mensagem)
    } finally {
      setOcupado(false)
    }
  }

  async function tentarDeNovo() {
    setErro(null)
    try {
      setAndamento(await renomeacao.retomar(pessoaId))
    } catch (e) {
      setErro(falhaDaAcao(e, 'Não foi possível retomar. Tente de novo.').mensagem)
    }
  }

  function aoTeclar(e: KeyboardEvent<HTMLFormElement>) {
    if (e.key === 'Escape') {
      e.preventDefault()
      aoFechar()
    } else if (e.key === 'Enter' && !(e.target instanceof HTMLButtonElement) && !andamento) {
      e.preventDefault()
      void (impacto ? confirmar() : ver())
    }
  }

  return (
    <form ref={raiz} aria-label={`Renomear ${nomeAtual} em todos os vídeos`} onKeyDown={aoTeclar} onSubmit={(e) => e.preventDefault()}>
      <Stack gap="xs">
        {!andamento && (
          <TextInput size="xs" label="Novo nome" value={nome} maxLength={200} onChange={(e) => mudar(e.currentTarget.value)} />
        )}
        {impacto && !andamento && <Text size="xs">{efeito(impacto)}</Text>}
        {andamento && (
          <Text size="xs" role="status">
            {frase(andamento)}
          </Text>
        )}
        {erro && (
          <Text size="xs" role="alert" c="red.4">
            {erro}
          </Text>
        )}
        <Group gap="xs" justify="flex-end">
          <Tooltip label="Esc">
            <Button size="compact-xs" variant="default" onClick={aoFechar}>
              {andamento ? 'Fechar' : 'Cancelar'}
            </Button>
          </Tooltip>
          {andamento?.estado === 'falhou' && (
            <Button size="compact-xs" onClick={() => void tentarDeNovo()}>
              Tentar de novo
            </Button>
          )}
          {!andamento && !impacto && (
            <Tooltip label="Enter">
              <Button size="compact-xs" loading={ocupado} disabled={nome.trim().length === 0} onClick={() => void ver()}>
                Ver o efeito
              </Button>
            </Tooltip>
          )}
          {!andamento && impacto && (
            <Tooltip label="Enter">
              <Button size="compact-xs" loading={ocupado} onClick={() => void confirmar()}>
                Renomear
              </Button>
            </Tooltip>
          )}
        </Group>
      </Stack>
    </form>
  )
}
