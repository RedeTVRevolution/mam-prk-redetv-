import { ActionIcon, Button, Group, Paper, Text, TextInput, Tooltip, UnstyledButton } from '@mantine/core'
import { IconCheck, IconChevronDown, IconChevronRight, IconPencil, IconX } from '@tabler/icons-react'
import { useState } from 'react'
import { type ClienteDoJob, codigoDoErro, NaoEncontrado, PedidoInvalido, SessaoExpirada } from './api.ts'
import { type Atalho, emCampoDeTexto, useAtalhos } from './atalhos.ts'
import { CampoDeNome } from './CampoDeNome.tsx'
import type { Decupagem, Sugestao } from './decupagem.ts'
import { relogio } from './linhaDoTempo.ts'
import { CORES } from './tema.ts'

const GRUPO = 'Sugestões'

/** O catálogo do campo "outro nome", pela correção proposta (só as que trocam um nome); as outras pedem um texto livre. */
const CATALOGO_DO_CAMPO: Record<string, 'pessoas' | 'marcas'> = {
  'pessoa.renomear': 'pessoas',
  'comercial.marca': 'marcas',
}

/** "Vale para as 7 aparições de Leão Lobo neste vídeo": a pessoa é uma entidade e a correção é uma só. */
function valeParaAsAparicoes(s: Sugestao, decupagem: Decupagem | null, nome: string): string | null {
  if (CATALOGO_DO_CAMPO[s.correcao.tipo] !== 'pessoas') return null
  const pessoa = decupagem?.pessoas.find((p) => p.id === s.correcao.item_id)
  if (!pessoa) return null
  const n = pessoa.na_imagem.length
  return `${n === 1 ? 'Vale para a 1 aparição' : `Vale para as ${n} aparições`} de ${nome} neste vídeo.`
}

const teclaDe = (e: KeyboardEvent, letra: string) => e.key.toLowerCase() === letra && !e.shiftKey

/** A mensagem de uma falha ao decidir: a ação para a pessoa e, se for o caso, o código para o suporte. */
function falhaAoDecidir(e: unknown, acao: 'aceitar' | 'recusar'): { mensagem: string; codigo: string | null } | null {
  if (e instanceof SessaoExpirada) return null
  if (e instanceof NaoEncontrado) return { mensagem: 'Esta sugestão já foi decidida; a lista foi atualizada.', codigo: null }
  if (e instanceof PedidoInvalido && acao === 'aceitar')
    return { mensagem: 'Esta sugestão pede um valor: use "Outro nome" (R) para informá-lo.', codigo: null }
  return { mensagem: `Não foi possível ${acao} a sugestão. Tente de novo.`, codigo: codigoDoErro(e) }
}

/**
 * A seção "Sugestões (N)" acima das abas: cada uma é uma pergunta, o trecho e o contexto, e se resolve com
 * `S` (aceita), `N` (recusa) e `R` (outro nome, com autocompletar) ou pelos botões. Trata qualquer tipo pelo
 * formato da rota; só olha o tipo da correção proposta para escolher o catálogo do campo (`CATALOGO_DO_CAMPO`).
 */
export function Sugestoes({
  sugestoes,
  decupagem,
  api,
  ativo,
  aoSaltar,
  aoResolver,
  aoFalhar,
  aoAvisar,
}: {
  sugestoes: Sugestao[]
  decupagem: Decupagem | null
  api: Pick<ClienteDoJob, 'aceitarSugestao' | 'recusarSugestao'>
  /** O modo de catalogação está ligado: sem ele nada aparece nem age. */
  ativo: boolean
  aoSaltar: (ms: number) => void
  /** A sugestão foi aceita ou recusada: sai da lista, e a decupagem muda. */
  aoResolver: (id: string) => void
  /** A decisão falhou: a lista vem de novo (a sugestão pode já ter sido decidida). */
  aoFalhar: () => void
  aoAvisar: (texto: string) => void
}) {
  const [recolhida, setRecolhida] = useState(false)
  // O foco guarda o id: se a lista vem de novo em outra ordem, as teclas não passam a outra sugestão.
  const [foco, setFoco] = useState<string | null>(null)
  const [outroNome, setOutroNome] = useState<{ id: string; valor: string } | null>(null)
  const [ocupada, setOcupada] = useState(false)
  const [erro, setErro] = useState<{ mensagem: string; codigo: string | null } | null>(null)
  const visivel = ativo && sugestoes.length > 0
  const emFoco = visivel ? (sugestoes.find((s) => s.id === foco) ?? sugestoes[0]) : undefined

  async function aceitar(s: Sugestao, valor?: string) {
    if (ocupada) return
    setOcupada(true)
    setErro(null)
    try {
      await api.aceitarSugestao(s.id, valor)
      const nome = valor ?? s.correcao.valor
      const vale = valeParaAsAparicoes(s, decupagem, nome)
      if (vale) aoAvisar(vale)
      setOutroNome(null)
      aoResolver(s.id)
    } catch (e) {
      setErro(falhaAoDecidir(e, 'aceitar'))
      aoFalhar()
    } finally {
      setOcupada(false)
    }
  }

  async function recusar(s: Sugestao) {
    if (ocupada) return
    setOcupada(true)
    setErro(null)
    try {
      await api.recusarSugestao(s.id)
      setOutroNome(null)
      aoResolver(s.id)
    } catch (e) {
      setErro(falhaAoDecidir(e, 'recusar'))
      aoFalhar()
    } finally {
      setOcupada(false)
    }
  }

  const editando = (s: Sugestao) => (outroNome?.id === s.id ? outroNome : null)

  function pedirOutroNome(s: Sugestao) {
    setErro(null)
    setOutroNome({ id: s.id, valor: '' })
  }

  const atalhos: Atalho[] = [
    {
      tecla: 'S',
      acao: 'Sugestão em foco: aceitar',
      grupo: GRUPO,
      casa: (e) => teclaDe(e, 's'),
      executar: () => emFoco && void aceitar(emFoco),
    },
    {
      tecla: 'N',
      acao: 'Sugestão em foco: recusar',
      grupo: GRUPO,
      casa: (e) => teclaDe(e, 'n'),
      executar: () => emFoco && void recusar(emFoco),
    },
    {
      tecla: 'R',
      acao: 'Sugestão em foco: outro nome',
      grupo: GRUPO,
      casa: (e) => teclaDe(e, 'r'),
      executar: (e) => {
        if (!emFoco) return
        e.preventDefault()
        pedirOutroNome(emFoco)
      },
    },
    // As setas são da própria seção (não andam o painel); a linha só informa.
    { tecla: '↑ ↓', acao: 'Na seção Sugestões: trocar a sugestão em foco', grupo: GRUPO },
  ]
  useAtalhos(ativo ? atalhos : [])

  if (!visivel) return null

  return (
    <Paper
      withBorder
      p="xs"
      mb="xs"
      data-sugestoes
      onKeyDown={(e) => {
        // ↑ ↓ dentro da seção trocam a sugestão em foco; o painel não anda junto.
        if ((e.key !== 'ArrowUp' && e.key !== 'ArrowDown') || emCampoDeTexto(e.target)) return
        e.preventDefault()
        e.stopPropagation()
        const i = sugestoes.findIndex((s) => s.id === emFoco?.id) + (e.key === 'ArrowUp' ? -1 : 1)
        setFoco(sugestoes[Math.min(Math.max(i, 0), sugestoes.length - 1)].id)
      }}
    >
      <UnstyledButton
        aria-expanded={!recolhida}
        onClick={() => setRecolhida((r) => !r)}
        style={{ display: 'flex', alignItems: 'center', gap: 4 }}
      >
        {recolhida ? <IconChevronRight size={14} aria-hidden /> : <IconChevronDown size={14} aria-hidden />}
        <Text size="sm" fw={600}>
          Sugestões ({sugestoes.length})
        </Text>
      </UnstyledButton>
      {!recolhida &&
        sugestoes.map((s) => {
          const emEdicao = editando(s)
          const doFoco = s.id === emFoco?.id
          const catalogo = CATALOGO_DO_CAMPO[s.correcao.tipo]
          return (
            <div
              key={s.id}
              role="group"
              aria-label={s.pergunta}
              aria-current={doFoco}
              tabIndex={doFoco ? 0 : -1}
              onClick={() => setFoco(s.id)}
              style={{
                padding: '4px 6px',
                marginTop: 4,
                borderRadius: 'var(--mantine-radius-sm)',
                background: doFoco ? `${CORES.foco}29` : undefined,
              }}
            >
              <Group justify="space-between" wrap="nowrap" align="flex-start">
                <div style={{ minWidth: 0, flex: 1 }}>
                  {emEdicao ? (
                    <form
                      onSubmit={(e) => {
                        e.preventDefault()
                        if (emEdicao.valor.trim()) void aceitar(s, emEdicao.valor.trim())
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Escape') {
                          e.stopPropagation()
                          setOutroNome(null)
                        } else if (e.key === 'Enter' && !e.shiftKey && emEdicao.valor.trim()) {
                          e.preventDefault()
                          void aceitar(s, emEdicao.valor.trim())
                        }
                      }}
                    >
                      {catalogo ? (
                        <CampoDeNome
                          rotulo="Outro nome"
                          catalogo={catalogo}
                          valor={emEdicao.valor}
                          aoMudar={(nome) => setOutroNome({ id: s.id, valor: nome })}
                        />
                      ) : (
                        <TextInput
                          size="xs"
                          label="Outro valor"
                          value={emEdicao.valor}
                          onChange={(e) => setOutroNome({ id: s.id, valor: e.currentTarget.value })}
                        />
                      )}
                      <Group gap="xs" mt={4}>
                        <Button type="submit" size="compact-xs" disabled={ocupada || !emEdicao.valor.trim()}>
                          Salvar
                        </Button>
                        <Button size="compact-xs" variant="default" onClick={() => setOutroNome(null)}>
                          Cancelar
                        </Button>
                        <Text size="xs" c="dimmed">
                          Enter aceita com este nome · Esc cancela
                        </Text>
                      </Group>
                    </form>
                  ) : (
                    <>
                      <Text size="sm" fw={600}>
                        {s.pergunta}
                      </Text>
                      <UnstyledButton onClick={() => aoSaltar(s.inicio_ms)} aria-label={`Saltar a ${relogio(s.inicio_ms)}`}>
                        <Text size="xs" style={{ fontVariantNumeric: 'tabular-nums' }}>
                          {relogio(s.inicio_ms)}–{relogio(s.fim_ms)}
                        </Text>
                      </UnstyledButton>
                      <Text size="xs" c="dimmed">
                        {s.contexto}
                      </Text>
                    </>
                  )}
                </div>
                {!emEdicao && (
                  <Group gap={4} wrap="nowrap">
                    <Tooltip label="Aceitar (S)">
                      <ActionIcon
                        variant="default"
                        aria-label="Aceitar"
                        disabled={ocupada}
                        onClick={() => void aceitar(s)}
                      >
                        <IconCheck size={16} />
                      </ActionIcon>
                    </Tooltip>
                    <Tooltip label="Recusar (N)">
                      <ActionIcon
                        variant="default"
                        aria-label="Recusar"
                        disabled={ocupada}
                        onClick={() => void recusar(s)}
                      >
                        <IconX size={16} />
                      </ActionIcon>
                    </Tooltip>
                    <Tooltip label="Outro nome (R)">
                      <ActionIcon variant="default" aria-label="Outro nome" onClick={() => pedirOutroNome(s)}>
                        <IconPencil size={16} />
                      </ActionIcon>
                    </Tooltip>
                  </Group>
                )}
              </Group>
            </div>
          )
        })}
      {erro && (
        <div role="alert">
          <Text size="xs" c={CORES.falhou} mt={4}>
            {erro.mensagem}
          </Text>
          {erro.codigo && (
            <Text size="xs" c={CORES.textoSecundario}>
              Código para o suporte: {erro.codigo}
            </Text>
          )}
        </div>
      )}
    </Paper>
  )
}
