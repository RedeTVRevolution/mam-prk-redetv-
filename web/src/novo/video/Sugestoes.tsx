import { IconCheck, IconChevronDown, IconChevronRight, IconPencil, IconX } from '@tabler/icons-react'
import { cn } from 'cn'
import { useEffect, useRef, useState } from 'react'
import { type ClienteDoJob, codigoDoErro, NaoEncontrado, PedidoInvalido, SessaoExpirada } from '../../api.ts'
import { type Atalho, emCampoDeTexto, useAtalhos } from '../../atalhos.ts'
import type { Decupagem, Sugestao } from '../../decupagem.ts'
import { relogio } from '../../linhaDoTempo.ts'
import { Button } from '../ui/button.tsx'
import { BotaoDeIcone } from './comum.tsx'
import { CAMPO, CampoDeNome, Rotulo } from './Correcao.tsx'

const GRUPO = 'Sugestões'

/** O catálogo do campo "outro nome", pela correção proposta (só as que trocam um nome); as outras pedem um texto livre. */
const CATALOGO_DO_CAMPO: Record<string, 'pessoas' | 'marcas'> = {
  'pessoa.renomear': 'pessoas',
  'comercial.marca': 'marcas',
}

/** "Vale para as 7 aparições de Leão Lobo neste vídeo": a pessoa é uma entidade e a correção é uma só. */
function valeParaAsAparicoes(s: Sugestao, decupagem: Decupagem | undefined, nome: string): string | null {
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
  if (e instanceof PedidoInvalido && acao === 'aceitar') return { mensagem: 'Esta sugestão pede um valor: use "Outro nome" (R) para informá-lo.', codigo: null }
  return { mensagem: `Não foi possível ${acao} a sugestão. Tente de novo.`, codigo: codigoDoErro(e) }
}

/**
 * A seção "Sugestões (N)" do modo de revisão: cada uma é uma pergunta, o trecho e o contexto, e se resolve
 * com `S` (aceita), `X` (recusa) e `R` (outro nome, com autocompletar) ou pelos botões. Trata qualquer tipo
 * pelo formato da rota; só olha o tipo da correção proposta para escolher o catálogo do campo.
 *
 * O `N` é desta seção enquanto ela existe: o atalho de "próximo momento da busca" não pode casar com
 * o modo de revisão ligado e com sugestões na lista.
 */
export function Sugestoes({
  sugestoes,
  decupagem,
  api,
  aoSaltar,
  aoResolver,
  aoFalhar,
  aoAvisar,
}: {
  sugestoes: Sugestao[]
  decupagem: Decupagem | undefined
  api: Pick<ClienteDoJob, 'aceitarSugestao' | 'recusarSugestao'>
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
  const formulario = useRef<HTMLFormElement>(null)
  const emFoco = sugestoes.find((s) => s.id === foco) ?? sugestoes[0]
  const idDoNome = outroNome?.id
  useEffect(() => {
    if (idDoNome) formulario.current?.querySelector('input')?.focus()
  }, [idDoNome])

  async function decidir(s: Sugestao, acao: 'aceitar' | 'recusar', valor?: string) {
    if (ocupada) return
    setOcupada(true)
    setErro(null)
    try {
      if (acao === 'aceitar') {
        await api.aceitarSugestao(s.id, valor)
        const vale = valeParaAsAparicoes(s, decupagem, valor ?? s.correcao.valor)
        if (vale) aoAvisar(vale)
      } else await api.recusarSugestao(s.id)
      setOutroNome(null)
      aoResolver(s.id)
    } catch (e) {
      setErro(falhaAoDecidir(e, acao))
      aoFalhar()
    } finally {
      setOcupada(false)
    }
  }

  function pedirOutroNome(s: Sugestao) {
    setErro(null)
    setOutroNome({ id: s.id, valor: '' })
  }

  const atalhos: Atalho[] = [
    { tecla: 'S', acao: 'Sugestão em foco: aceitar', grupo: GRUPO, casa: (e) => teclaDe(e, 's'), executar: () => void decidir(emFoco, 'aceitar') },
    { tecla: 'X', acao: 'Sugestão em foco: recusar', grupo: GRUPO, casa: (e) => teclaDe(e, 'x'), executar: () => void decidir(emFoco, 'recusar') },
    {
      tecla: 'R',
      acao: 'Sugestão em foco: outro nome',
      grupo: GRUPO,
      casa: (e) => teclaDe(e, 'r'),
      executar: (e) => {
        e.preventDefault()
        pedirOutroNome(emFoco)
      },
    },
    // As setas são da própria seção (não andam o inspetor); a linha só informa.
    { tecla: '↑ ↓', acao: 'Na seção Sugestões: trocar a sugestão em foco', grupo: GRUPO },
  ]
  useAtalhos(emFoco ? atalhos : [])

  if (!emFoco) return null

  return (
    <section
      aria-label="Sugestões"
      data-sugestoes
      className="max-h-[45dvh] shrink-0 overflow-y-auto border-b"
      onKeyDown={(e) => {
        // ↑ ↓ dentro da seção trocam a sugestão em foco; o inspetor não anda junto.
        if ((e.key !== 'ArrowUp' && e.key !== 'ArrowDown') || emCampoDeTexto(e.target)) return
        e.preventDefault()
        e.stopPropagation()
        const i = sugestoes.findIndex((s) => s.id === emFoco.id) + (e.key === 'ArrowUp' ? -1 : 1)
        setFoco(sugestoes[Math.min(Math.max(i, 0), sugestoes.length - 1)].id)
      }}
    >
      <button
        type="button"
        aria-expanded={!recolhida}
        onClick={() => setRecolhida((r) => !r)}
        className="flex h-9 w-full items-center gap-2 px-3 text-left text-sm font-medium hover:bg-card"
      >
        {recolhida ? <IconChevronRight size={16} aria-hidden /> : <IconChevronDown size={16} aria-hidden />}
        Sugestões ({sugestoes.length})
      </button>
      {!recolhida &&
        sugestoes.map((s) => {
          const emEdicao = outroNome?.id === s.id ? outroNome : null
          const doFoco = s.id === emFoco.id
          const catalogo = CATALOGO_DO_CAMPO[s.correcao.tipo]
          return (
            <div
              key={s.id}
              role="group"
              aria-label={s.pergunta}
              aria-current={doFoco}
              tabIndex={doFoco ? 0 : -1}
              onClick={() => setFoco(s.id)}
              className={cn('flex items-start gap-2 border-t border-border/60 px-3 py-2', doFoco && 'bg-selected')}
            >
              <div className="min-w-0 flex-1">
                {emEdicao ? (
                  <form
                    ref={formulario}
                    className="grid gap-2"
                    onSubmit={(e) => {
                      e.preventDefault()
                      if (emEdicao.valor.trim()) void decidir(s, 'aceitar', emEdicao.valor.trim())
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Escape') {
                        e.stopPropagation()
                        setOutroNome(null)
                      } else if (e.key === 'Enter' && !e.shiftKey && emEdicao.valor.trim()) {
                        e.preventDefault()
                        void decidir(s, 'aceitar', emEdicao.valor.trim())
                      }
                    }}
                  >
                    {catalogo ? (
                      <CampoDeNome rotulo="Outro nome" catalogo={catalogo} valor={emEdicao.valor} aoMudar={(nome) => setOutroNome({ id: s.id, valor: nome })} />
                    ) : (
                      <Rotulo texto="Outro valor">
                        <input className={CAMPO} value={emEdicao.valor} onChange={(e) => setOutroNome({ id: s.id, valor: e.currentTarget.value })} />
                      </Rotulo>
                    )}
                    <div className="flex flex-wrap items-center gap-2">
                      <Button type="submit" size="sm" disabled={ocupada || !emEdicao.valor.trim()}>
                        Salvar
                      </Button>
                      <Button type="button" size="sm" variant="secondary" onClick={() => setOutroNome(null)}>
                        Cancelar
                      </Button>
                      <span className="text-xs text-muted-foreground">Enter aceita com este nome · Esc cancela</span>
                    </div>
                  </form>
                ) : (
                  <>
                    <p className="text-sm font-semibold">{s.pergunta}</p>
                    <button
                      type="button"
                      aria-label={`Saltar a ${relogio(s.inicio_ms)}`}
                      onClick={() => aoSaltar(s.inicio_ms)}
                      className="font-mono text-xs text-link tabular-nums hover:underline"
                    >
                      {relogio(s.inicio_ms)}–{relogio(s.fim_ms)}
                    </button>
                    <p className="text-xs text-muted-foreground">{s.contexto}</p>
                  </>
                )}
              </div>
              {!emEdicao && (
                <div className="flex shrink-0 gap-0.5">
                  <BotaoDeIcone rotulo="Aceitar" atalho="S" disabled={ocupada} onClick={() => void decidir(s, 'aceitar')}>
                    <IconCheck size={16} stroke={1.75} aria-hidden />
                  </BotaoDeIcone>
                  <BotaoDeIcone rotulo="Recusar" atalho="X" disabled={ocupada} onClick={() => void decidir(s, 'recusar')}>
                    <IconX size={16} stroke={1.75} aria-hidden />
                  </BotaoDeIcone>
                  <BotaoDeIcone rotulo="Outro nome" atalho="R" onClick={() => pedirOutroNome(s)}>
                    <IconPencil size={16} stroke={1.75} aria-hidden />
                  </BotaoDeIcone>
                </div>
              )}
            </div>
          )
        })}
      {erro && (
        <div role="alert" className="border-t border-border/60 px-3 py-2">
          <p className="text-xs text-destructive">{erro.mensagem}</p>
          {erro.codigo && <p className="text-xs text-muted-foreground">Código para o suporte: {erro.codigo}</p>}
        </div>
      )}
    </section>
  )
}
