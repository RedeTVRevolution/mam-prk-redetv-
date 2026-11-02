import { Alert, Badge, Button, Drawer, Group, Paper, Select, Stack, Tabs, Text, TextInput, Tooltip, UnstyledButton } from '@mantine/core'
import { IconArrowBackUp, IconCheck, IconX } from '@tabler/icons-react'
import { useEffect, useRef, useState } from 'react'
import { type ClienteDoJob, ConflitoNaApi, SessaoExpirada } from './api.ts'
import { type Atalho, useAtalhos } from './atalhos.ts'
import { type CatalogoDeCorrecoes, rotuloDe } from './catalogo.ts'
import { desfazivel } from './catalogacao.ts'
import type { ItemDaFila, ItemDoHistorico } from './decupagem.ts'
import { relogio } from './linhaDoTempo.ts'
import { CORES } from './tema.ts'

export type AbaDaGaveta = 'historico' | 'fila' | 'aprovacao'

const GRUPO = 'Histórico'
const LARGURA = 'min(32rem, 90vw)'
// O motivo do gesto: a pessoa decide num clique, sem escrever (a recusa é a exceção e pede o motivo).
const MOTIVO_DE_DESFAZER = 'correção desfeita pelo editor'
const MOTIVO_DE_REAPLICAR = 'correção reaplicada pelo editor'
const MOTIVO_DE_DESCARTAR = 'correção descartada pelo editor'

const quando = (iso: string) => new Date(iso).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' })

const COR_DO_ESTADO: Record<ItemDoHistorico['estado'], string> = {
  ativa: CORES.concluido,
  aprovada: CORES.concluido,
  pendente: CORES.andamento,
  recusada: CORES.falhou,
  desfeita: CORES.textoSecundario,
  reaplicada: CORES.textoSecundario,
  descartada: CORES.textoSecundario,
}

function AntesEDepois({ item }: { item: Pick<ItemDoHistorico, 'antes_legivel' | 'depois_legivel'> }) {
  return (
    <>
      <Group gap={4} wrap="nowrap" align="flex-start">
        <Text size="xs" c="dimmed">
          Antes:
        </Text>
        <Text size="sm">{item.antes_legivel}</Text>
      </Group>
      <Group gap={4} wrap="nowrap" align="flex-start">
        <Text size="xs" c="dimmed">
          Depois:
        </Text>
        <Text size="sm" fw={600}>
          {item.depois_legivel}
        </Text>
      </Group>
    </>
  )
}

/** O campo do motivo da recusa na própria linha: Enter recusa e Esc cancela; sem motivo, nada é enviado. */
function RecusaNaLinha({
  limite,
  enviando,
  aoCancelar,
  aoRecusar,
}: {
  limite: number | undefined
  enviando: boolean
  aoCancelar: () => void
  aoRecusar: (motivo: string) => void
}) {
  const [motivo, setMotivo] = useState('')
  const pronto = motivo.trim().length > 0
  return (
    <Stack gap={4}>
      <TextInput
        label="Motivo da recusa"
        size="xs"
        data-autofocus
        value={motivo}
        maxLength={limite}
        onChange={(e) => setMotivo(e.currentTarget.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            // O Esc daqui cancela só o campo, sem fechar a gaveta.
            e.preventDefault()
            aoCancelar()
          } else if (e.key === 'Enter' && pronto && !enviando) aoRecusar(motivo.trim())
        }}
      />
      <Group justify="flex-end" gap="xs">
        <Tooltip label="Esc">
          <Button size="xs" variant="default" onClick={aoCancelar}>
            Cancelar
          </Button>
        </Tooltip>
        <Tooltip label="Enter">
          <Button size="xs" loading={enviando} disabled={!pronto} onClick={() => aoRecusar(motivo.trim())}>
            Recusar
          </Button>
        </Tooltip>
      </Group>
    </Stack>
  )
}

function CabecalhoDaCorrecao({ item, rotulo }: { item: ItemDoHistorico | ItemDaFila; rotulo: string }) {
  return (
    <>
      <Group justify="space-between" wrap="nowrap">
        <Text size="xs" fw={700}>
          {rotulo}
        </Text>
        {'estado' in item && (
          <Badge size="xs" variant="light" color={COR_DO_ESTADO[item.estado]}>
            {item.estado}
          </Badge>
        )}
      </Group>
      <Text size="xs" c="dimmed">
        {item.autor_email}
      </Text>
      <Text size="xs" c="dimmed">
        {quando(item.criada_em)}
      </Text>
    </>
  )
}

/**
 * A gaveta à direita, por cima do painel, com o player à vista: o histórico das correções, a fila das
 * que não casaram depois de reprocessar e a aprovação do Curador. Desfazer, reaplicar, descartar e
 * aprovar são um clique; recusar pede o motivo na própria linha. Nada se apaga: cada decisão acrescenta.
 */
export function Gaveta({
  aberta,
  aba,
  aoTrocarAba,
  aoFechar,
  historico,
  fila,
  podeAprovar,
  api,
  catalogo,
  falhaAoCarregar,
  aoMudar,
  aoSaltar,
  aoRefazerAMao,
}: {
  aberta: boolean
  aba: AbaDaGaveta
  aoTrocarAba: (aba: AbaDaGaveta) => void
  aoFechar: () => void
  historico: ItemDoHistorico[]
  fila: ItemDaFila[]
  podeAprovar: boolean
  api: ClienteDoJob
  catalogo: CatalogoDeCorrecoes | null
  /** O histórico ou a fila não vieram da API. */
  falhaAoCarregar: boolean
  /** Recarrega a decupagem, o histórico e a fila depois de uma decisão. */
  aoMudar: () => void
  /** Salta o player ao item da correção; `false` se o item não está mais na decupagem. */
  aoSaltar: (correcao: ItemDoHistorico) => boolean
  /** Juntar ou dividir pautas que a reprocessagem não reaplicou: refazer na tela das pautas. */
  aoRefazerAMao?: () => void
}) {
  const pendentes = historico.filter((h) => h.estado === 'pendente')
  const [selecionado, setSelecionado] = useState(0)
  const [ocupado, setOcupado] = useState<string | null>(null)
  const [recusando, setRecusando] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const lista = useRef<HTMLDivElement>(null)
  const rotulo = (tipo: string) => (catalogo ? rotuloDe(catalogo.tipos, tipo) : tipo)
  const indice = Math.min(selecionado, Math.max(historico.length - 1, 0))
  const limiteDoMotivo = catalogo?.limites.motivo

  // A linha selecionada fica à vista ao mover a seleção e ao reabrir a gaveta.
  useEffect(() => {
    lista.current?.querySelector('[data-selecionada="true"]')?.scrollIntoView?.({ block: 'nearest' })
  }, [indice, aberta, aba])

  // O Esc fecha a gaveta, menos quando outro elemento já o usou (o formulário de correção no painel, a
  // confirmação na linha, a recusa): eles marcam o evento com `preventDefault` ou param a propagação.
  // O Esc do Mantine não serve: com `trapFocus={false}` ele age em qualquer Esc da janela.
  useEffect(() => {
    if (!aberta) return
    const aoTeclar = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented && !e.isComposing) aoFechar()
    }
    window.addEventListener('keydown', aoTeclar)
    return () => window.removeEventListener('keydown', aoTeclar)
  }, [aberta, aoFechar])

  function trocarAba(nova: string | null) {
    if (nova !== 'historico' && nova !== 'fila' && nova !== 'aprovacao') return
    setAviso(null)
    setErro(null)
    setRecusando(null)
    aoTrocarAba(nova)
  }

  function saltar(i: number) {
    const correcao = historico[i]
    if (!correcao) return
    setSelecionado(i)
    setAviso(aoSaltar(correcao) ? null : 'Este item não está mais na decupagem.')
  }

  const noHistorico = aberta && aba === 'historico'
  const atalhos: Atalho[] = [
    {
      tecla: '↑ ↓',
      acao: 'Na gaveta do histórico: mover a seleção',
      grupo: GRUPO,
      casa: (e) => noHistorico && (e.key === 'ArrowUp' || e.key === 'ArrowDown'),
      executar: (e) => {
        setAviso(null)
        setSelecionado(Math.max(Math.min(indice + (e.key === 'ArrowUp' ? -1 : 1), historico.length - 1), 0))
      },
    },
    {
      tecla: 'Enter',
      acao: 'Na gaveta do histórico: saltar o player ao item',
      grupo: GRUPO,
      // Com o foco num botão ou numa aba, o Enter faz o que o elemento faz.
      casa: (e) =>
        noHistorico &&
        e.key === 'Enter' &&
        !(e.target instanceof HTMLElement && e.target.closest('button, a, [role="tab"]')),
      executar: () => saltar(indice),
    },
  ]
  useAtalhos(atalhos)

  /** Roda a decisão; qualquer que seja o resultado, as listas são recarregadas (outra pessoa pode ter decidido antes). */
  async function decidir(id: string, acao: () => Promise<void>, conflito: string, falha: string) {
    // Uma decisão por vez: o segundo clique, nesta ou noutra linha, espera a primeira terminar.
    if (ocupado) return
    setOcupado(id)
    setErro(null)
    setAviso(null)
    try {
      await acao()
      setRecusando(null)
    } catch (e) {
      setOcupado(null)
      // Com a sessão expirada, o aviso é da casca e recarregar só falharia de novo.
      if (e instanceof SessaoExpirada) return
      setErro(e instanceof ConflitoNaApi ? conflito : falha)
    }
    setOcupado(null)
    aoMudar()
  }

  const desfazer = (c: ItemDoHistorico) =>
    decidir(
      c.id,
      () => api.desfazer(c.id, MOTIVO_DE_DESFAZER),
      'Essa correção já foi desfeita, saiu da fila ou não casa com a versão atual. O histórico foi recarregado.',
      'Não foi possível desfazer a correção. Tente de novo em instantes.',
    )
  const aprovar = (c: ItemDoHistorico) =>
    decidir(
      c.id,
      () => api.aprovar(c.id),
      'Essa correção não está mais pendente. O histórico foi recarregado.',
      'Não foi possível aprovar a correção. Tente de novo em instantes.',
    )
  const recusar = (c: ItemDoHistorico, motivo: string) =>
    decidir(
      c.id,
      () => api.recusar(c.id, motivo),
      'Essa correção não está mais pendente. O histórico foi recarregado.',
      'Não foi possível recusar a correção. Tente de novo em instantes.',
    )

  return (
    <Drawer.Root
      opened={aberta}
      onClose={aoFechar}
      closeOnEscape={false}
      position="right"
      size={LARGURA}
      // Sem sombra sobre o resto da tela: o player e o painel seguem à vista e ao alcance do mouse e do teclado.
      lockScroll={false}
      trapFocus={false}
    >
      <Drawer.Content style={{ background: CORES.elevada }}>
        <Drawer.Header style={{ background: CORES.elevada }}>
          <Drawer.Title fw={700}>Correções do vídeo</Drawer.Title>
          <Tooltip label="Fechar (Esc)">
            <Drawer.CloseButton aria-label="Fechar" icon={<IconX />} />
          </Tooltip>
        </Drawer.Header>
        <Drawer.Body>
          <Tabs value={aba} onChange={trocarAba}>
            <Tabs.List>
              <Tabs.Tab value="historico">Histórico</Tabs.Tab>
              <Tabs.Tab value="fila">{`Fila de revisão (${fila.length})`}</Tabs.Tab>
              {podeAprovar && <Tabs.Tab value="aprovacao">{`Aprovação (${pendentes.length})`}</Tabs.Tab>}
            </Tabs.List>
            <Stack gap="xs" mt="sm" ref={lista}>
              {aviso && (
                <Text size="sm" role="status">
                  {aviso}
                </Text>
              )}
              {erro && (
                <Alert color={CORES.falhou} variant="light" role="alert">
                  {erro}
                </Alert>
              )}
              {falhaAoCarregar && (
                <Alert color={CORES.falhou} variant="light" role="alert">
                  <Stack gap="xs" align="flex-start">
                    <Text size="sm">Não foi possível carregar o histórico e a fila de revisão.</Text>
                    <Button size="xs" variant="default" onClick={aoMudar}>
                      Tentar de novo
                    </Button>
                  </Stack>
                </Alert>
              )}
              {aba === 'historico' && (
                <>
                  {historico.length === 0 && <Text size="sm">Nenhuma correção ainda.</Text>}
                  {historico.map((c, i) => (
                    <Paper
                      key={c.id}
                      withBorder
                      p="sm"
                      data-selecionada={i === indice}
                      style={i === indice ? { borderColor: CORES.foco } : undefined}
                    >
                      <Stack gap={4}>
                        <UnstyledButton
                          aria-label={`Saltar ao item: ${rotulo(c.tipo)}, ${c.depois_legivel}`}
                          onClick={() => saltar(i)}
                        >
                          <Stack gap={4}>
                            <CabecalhoDaCorrecao item={c} rotulo={rotulo(c.tipo)} />
                            <AntesEDepois item={c} />
                            <Text size="sm">{c.motivo}</Text>
                            {c.reaplica && (
                              <Text size="xs" c="dimmed">
                                {`Reaplica a correção de ${quandoDaOriginal(historico, c.reaplica)}`}
                              </Text>
                            )}
                          </Stack>
                        </UnstyledButton>
                        {desfazivel(c) && (
                          <Group justify="flex-end">
                            <Tooltip label="Desfazer esta correção">
                              <Button
                                size="xs"
                                variant="default"
                                leftSection={<IconArrowBackUp size={14} />}
                                loading={ocupado === c.id}
                                onClick={() => void desfazer(c)}
                              >
                                Desfazer
                              </Button>
                            </Tooltip>
                          </Group>
                        )}
                      </Stack>
                    </Paper>
                  ))}
                </>
              )}
              {aba === 'fila' && (
                <>
                  {fila.length === 0 && <Text size="sm">Nada na fila.</Text>}
                  {fila.map((f) => (
                    <ItemDaFilaDeRevisao
                      key={f.id}
                      item={f}
                      rotulo={rotulo(f.tipo)}
                      ocupado={ocupado === f.id}
                      aoRefazerAMao={aoRefazerAMao}
                      aoReaplicar={(candidato) =>
                        void decidir(
                          f.id,
                          () => api.reaplicar(f.id, candidato, MOTIVO_DE_REAPLICAR),
                          'Essa correção não está mais na fila. A fila foi recarregada.',
                          'Não foi possível reaplicar a correção. Tente de novo em instantes.',
                        )
                      }
                      aoDescartar={() =>
                        void decidir(
                          f.id,
                          () => api.descartar(f.id, MOTIVO_DE_DESCARTAR),
                          'Essa correção não está mais na fila. A fila foi recarregada.',
                          'Não foi possível descartar a correção. Tente de novo em instantes.',
                        )
                      }
                    />
                  ))}
                </>
              )}
              {aba === 'aprovacao' && podeAprovar && (
                <>
                  {pendentes.length === 0 && <Text size="sm">Nada aguardando o Curador.</Text>}
                  {pendentes.map((c) => (
                    <Paper key={c.id} withBorder p="sm">
                      <Stack gap={4}>
                        <CabecalhoDaCorrecao item={c} rotulo={rotulo(c.tipo)} />
                        <AntesEDepois item={c} />
                        <Text size="sm">{c.motivo}</Text>
                        {recusando === c.id ? (
                          <RecusaNaLinha
                            limite={limiteDoMotivo}
                            enviando={ocupado === c.id}
                            aoCancelar={() => setRecusando(null)}
                            aoRecusar={(motivo) => void recusar(c, motivo)}
                          />
                        ) : (
                          <Group justify="flex-end" gap="xs">
                            <Tooltip label="Recusar a correção (pede o motivo)">
                              <Button
                                size="xs"
                                variant="default"
                                leftSection={<IconX size={14} />}
                                disabled={ocupado === c.id}
                                onClick={() => setRecusando(c.id)}
                              >
                                Recusar
                              </Button>
                            </Tooltip>
                            <Tooltip label="Aprovar a correção: ela entra na decupagem">
                              <Button
                                size="xs"
                                leftSection={<IconCheck size={14} />}
                                loading={ocupado === c.id}
                                onClick={() => void aprovar(c)}
                              >
                                Aprovar
                              </Button>
                            </Tooltip>
                          </Group>
                        )}
                      </Stack>
                    </Paper>
                  ))}
                </>
              )}
            </Stack>
          </Tabs>
        </Drawer.Body>
      </Drawer.Content>
    </Drawer.Root>
  )
}

/** A data da correção que a reaplicação refaz, para ligar uma à outra. */
function quandoDaOriginal(itens: ItemDoHistorico[], id: string): string {
  const original = itens.find((o) => o.id === id)
  return original ? quando(original.criada_em) : id
}

function ItemDaFilaDeRevisao({
  item,
  rotulo,
  ocupado,
  aoReaplicar,
  aoDescartar,
  aoRefazerAMao,
}: {
  item: ItemDaFila
  rotulo: string
  ocupado: boolean
  aoReaplicar: (candidato: string) => void
  aoDescartar: () => void
  aoRefazerAMao?: () => void
}) {
  const estrutural = item.tipo === 'pauta.juntar' || item.tipo === 'pauta.dividir'
  const [candidato, setCandidato] = useState<string | null>(null)
  const [confirmando, setConfirmando] = useState(false)
  return (
    <Paper withBorder p="sm">
      <Stack gap={4}>
        <CabecalhoDaCorrecao item={item} rotulo={rotulo} />
        {estrutural && (
          <Badge size="xs" variant="light" color={CORES.falhou} style={{ alignSelf: 'flex-start' }}>
            não reaplicada
          </Badge>
        )}
        <AntesEDepois item={item} />
        <Text size="sm">{item.motivo}</Text>
        {estrutural ? (
          <Text size="sm">
            Nenhuma pauta nova corresponde a esta correção: o modelo refez as pautas. Refaça à mão ou descarte.
          </Text>
        ) : (
        <Select
          label="Candidato"
          size="xs"
          placeholder={item.candidatos.length ? 'Escolha o item' : 'Sem candidatos'}
          data={item.candidatos.map((c) => ({
            value: c.item_id,
            label: `${c.nome} (${relogio(c.inicio_ms)}–${relogio(c.fim_ms)})`,
          }))}
          value={candidato}
          onChange={setCandidato}
        />
        )}
        {confirmando ? (
          // Descartar não tem volta: a confirmação fica na própria linha (sistema visual, botão de perigo).
          <Group
            role="group"
            aria-label="Confirmar o descarte"
            justify="space-between"
            gap="xs"
            wrap="nowrap"
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                e.preventDefault()
                setConfirmando(false)
              }
            }}
          >
            <Text size="sm">Descartar esta correção? Ela não volta.</Text>
            <Group gap="xs" wrap="nowrap" style={{ flex: 'none' }}>
              <Tooltip label="Esc">
                <Button size="compact-xs" variant="default" onClick={() => setConfirmando(false)}>
                  Cancelar
                </Button>
              </Tooltip>
              <Button size="compact-xs" variant="outline" color={CORES.falhou} loading={ocupado} onClick={aoDescartar}>
                Descartar
              </Button>
            </Group>
          </Group>
        ) : (
          <Group justify="flex-end" gap="xs">
            <Tooltip label="Descartar a correção: ela não volta (pede confirmação)">
              <Button
                size="xs"
                variant="outline"
                color={CORES.falhou}
                disabled={ocupado}
                onClick={() => setConfirmando(true)}
              >
                Descartar
              </Button>
            </Tooltip>
            {estrutural ? (
              aoRefazerAMao && (
                <Button size="xs" disabled={ocupado} onClick={aoRefazerAMao}>
                  Refazer à mão
                </Button>
              )
            ) : (
              <Tooltip label="Reaplicar no candidato escolhido">
                <Button size="xs" loading={ocupado} disabled={!candidato} onClick={() => candidato && aoReaplicar(candidato)}>
                  Reaplicar
                </Button>
              </Tooltip>
            )}
          </Group>
        )}
      </Stack>
    </Paper>
  )
}
