import { Box, Button, Stack, Text, UnstyledButton } from '@mantine/core'
import { useEffect, useRef, useState } from 'react'
import { relogio } from './linhaDoTempo.ts'
import { inventarioDeDestaque, inventarioPorCategoria, maiorCaixa, type ObjetoDoVideo } from './painel.ts'
import type { CaixaDoQuadro, ObjetoDoInventario } from './decupagem.ts'

/** O objeto sob o mouse (ou o foco): o nome e a caixa do quadro onde ela foi medida. */
export interface ObjetoApontado {
  nome: string
  caixa: CaixaDoQuadro
  /** Largura sobre altura do vídeo, que o Visualizador põe ao receber o objeto; sem ela, 16:9. */
  proporcao?: number
}

const LARGURA_DO_QUADRO = 1000
const PROPORCAO_PADRAO = 16 / 9

/** Apontar (mouse ou foco) avisa `aoApontar`; o botão que some apontado não recebe o mouse sair nem o blur. */
function useApontar(nome: string, caixa: CaixaDoQuadro, aoApontar: (o: ObjetoApontado | null) => void) {
  const apontado = useRef(false)
  useEffect(
    () => () => {
      if (apontado.current) aoApontar(null)
    },
    [aoApontar],
  )
  const apontar = () => {
    apontado.current = true
    aoApontar({ nome, caixa })
  }
  const soltar = () => {
    apontado.current = false
    aoApontar(null)
  }
  return { onMouseEnter: apontar, onMouseLeave: soltar, onFocus: apontar, onBlur: soltar }
}

function Objeto({
  objeto,
  aoApontar,
}: {
  objeto: ObjetoDoInventario
  aoApontar: (o: ObjetoApontado | null) => void
}) {
  const detalhes = [objeto.cor, objeto.marca].filter(Boolean).join(' · ')
  const eventos = useApontar(objeto.nome, maiorCaixa(objeto), aoApontar)
  return (
    <UnstyledButton {...eventos} style={{ display: 'block', textAlign: 'left', padding: '2px 4px' }}>
      <Text span size="sm">
        {objeto.nome}
      </Text>
      {detalhes && (
        <Text span size="xs" c="dimmed">
          {' '}
          ({detalhes})
        </Text>
      )}
    </UnstyledButton>
  )
}

/**
 * O inventário de um plano: os objetos de destaque 3 primeiro e, sob demanda, todos, por categoria.
 * Passar o mouse (ou focar) num objeto avisa `aoApontar`, e o Visualizador mostra o quadro com a caixa.
 */
export function InventarioDoPlano({
  inventario,
  plano,
  aoApontar,
}: {
  inventario: ObjetoDoInventario[]
  /** O título do plano, para os nomes dos grupos. */
  plano: string
  aoApontar: (o: ObjetoApontado | null) => void
}) {
  const [aberto, setAberto] = useState(false)
  const destaques = inventarioDeDestaque(inventario)
  return (
    <Stack gap={4} mt={4} ml={16}>
      {destaques.length > 0 && (
        <Stack gap={0} role="group" aria-label={`Objetos de destaque do plano ${plano}`}>
          {destaques.map((o, i) => (
            <Objeto key={`${o.nome}-${i}`} objeto={o} aoApontar={aoApontar} />
          ))}
        </Stack>
      )}
      <Button
        size="compact-xs"
        variant="default"
        style={{ alignSelf: 'flex-start' }}
        aria-expanded={aberto}
        onClick={() => setAberto((a) => !a)}
      >
        {aberto ? 'Ocultar os objetos do plano' : `Ver todos os objetos do plano (${inventario.length})`}
      </Button>
      {aberto &&
        inventarioPorCategoria(inventario).map((g) => (
          <Stack key={g.categoria} gap={0} role="region" aria-label={`${g.nome} do plano ${plano}`}>
            <Text component="h4" size="xs" c="dimmed" fw={600} style={{ textTransform: 'uppercase' }}>
              {g.nome}
            </Text>
            {g.objetos.map((o, i) => (
              <Objeto key={`${o.nome}-${i}`} objeto={o} aoApontar={aoApontar} />
            ))}
          </Stack>
        ))}
    </Stack>
  )
}

/**
 * O quadro-chave onde a caixa do objeto foi medida, com a caixa por cima, sobre o player.
 * A caixa é fração do quadro, então o SVG a desenha no mesmo sistema de coordenadas da imagem
 * e acompanha o tamanho do player.
 */
export function QuadroDoObjeto({
  objeto,
  urlDoQuadro,
}: {
  objeto: ObjetoApontado
  urlDoQuadro: (caminho: string) => Promise<string>
}) {
  const { proporcao } = objeto
  const [pronto, setPronto] = useState<{ quadro: string; url: string } | null>(null)
  const { caixa } = objeto
  useEffect(() => {
    let vivo = true
    urlDoQuadro(caixa.quadro).then(
      (url) => vivo && setPronto({ quadro: caixa.quadro, url }),
      () => {},
    )
    return () => {
      vivo = false
    }
  }, [caixa.quadro, urlDoQuadro])
  // Enquanto a URL do quadro novo não chega, o quadro do objeto anterior não aparece.
  if (pronto?.quadro !== caixa.quadro) return null
  const { url } = pronto
  const altura = LARGURA_DO_QUADRO / (proporcao && proporcao > 0 ? proporcao : PROPORCAO_PADRAO)
  return (
    <Box style={{ position: 'absolute', inset: 0, background: 'var(--mantine-color-black)', pointerEvents: 'none' }}>
      <svg
        role="img"
        aria-label={`Quadro com a caixa de ${objeto.nome}`}
        viewBox={`0 0 ${LARGURA_DO_QUADRO} ${altura}`}
        preserveAspectRatio="xMidYMid meet"
        style={{ width: '100%', height: '100%' }}
      >
        <image href={url} x={0} y={0} width={LARGURA_DO_QUADRO} height={altura} preserveAspectRatio="none" />
        <rect
          x={caixa.x * LARGURA_DO_QUADRO}
          y={caixa.y * altura}
          width={caixa.largura * LARGURA_DO_QUADRO}
          height={caixa.altura * altura}
          fill="none"
          stroke="var(--mantine-color-yellow-4)"
          strokeWidth={6}
        />
      </svg>
    </Box>
  )
}

/**
 * Um objeto de cena do vídeo inteiro: apontar mostra o quadro com a caixa, clicar leva ao primeiro plano
 * e abre a lista dos planos em que aparece.
 */
function ObjetoDoVideoNaLista({
  objeto,
  aoSaltar,
  aoApontar,
}: {
  objeto: ObjetoDoVideo
  aoSaltar: (ms: number) => void
  aoApontar: (o: ObjetoApontado | null) => void
}) {
  const [aberto, setAberto] = useState(false)
  const eventos = useApontar(objeto.nome, objeto.caixa, aoApontar)
  const detalhes = [objeto.cor, objeto.marca].filter(Boolean).join(' · ')
  const quantos = `${objeto.planos.length} ${objeto.planos.length === 1 ? 'plano' : 'planos'}`
  return (
    <Stack gap={0}>
      <UnstyledButton
        {...eventos}
        aria-expanded={aberto}
        onClick={() => {
          setAberto((a) => !a)
          aoSaltar(objeto.planos[0].inicio_ms)
        }}
        style={{ display: 'block', textAlign: 'left', padding: '2px 4px' }}
      >
        <Text span size="sm">
          {objeto.nome}
        </Text>
        {detalhes && (
          <Text span size="xs" c="dimmed">
            {' '}
            ({detalhes})
          </Text>
        )}
        <Text span size="xs" c="dimmed" ml="xs">
          {quantos}
        </Text>
      </UnstyledButton>
      {aberto && (
        <Stack gap={0} ml="md">
          {objeto.planos.map((p) => (
            <UnstyledButton
              key={p.inicio_ms}
              onClick={() => aoSaltar(p.inicio_ms)}
              style={{ textAlign: 'left', padding: '1px 4px' }}
            >
              <Text size="xs" c="dimmed">
                {p.ambiente} · {relogio(p.inicio_ms)}
              </Text>
            </UnstyledButton>
          ))}
        </Stack>
      )}
    </Stack>
  )
}

/** O inventário de objetos de cena do vídeo inteiro, por categoria (aba Objetos). */
export function InventarioDoVideo({
  grupos,
  aoSaltar,
  aoApontar,
}: {
  grupos: { categoria: string; nome: string; objetos: ObjetoDoVideo[] }[]
  aoSaltar: (ms: number) => void
  aoApontar: (o: ObjetoApontado | null) => void
}) {
  return (
    <>
      {grupos.map((g) => (
        <Stack key={g.categoria} gap={0} role="region" aria-label={`${g.nome} do vídeo`}>
          <Text component="h4" size="xs" c="dimmed" fw={600} style={{ textTransform: 'uppercase' }}>
            {g.nome}
          </Text>
          {g.objetos.map((o) => (
            <ObjetoDoVideoNaLista key={o.chave} objeto={o} aoSaltar={aoSaltar} aoApontar={aoApontar} />
          ))}
        </Stack>
      ))}
    </>
  )
}
