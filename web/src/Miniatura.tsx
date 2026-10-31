import { Box, Tooltip } from '@mantine/core'
import { useEffect, useRef, useState } from 'react'

/** O quadro (16:9) de `url`; sem ele, um retângulo cinza chapado, sem ícone. */
export function Quadro({ url, largura, altura }: { url: string | null | undefined; largura: number; altura: number }) {
  const [falhou, setFalhou] = useState(false)
  // Uma URL nova (o quadro vencido que foi pedido de novo) dá nova chance à imagem.
  const [urlVista, setUrlVista] = useState(url)
  if (url !== urlVista) {
    setUrlVista(url)
    setFalhou(false)
  }
  return (
    <Box
      aria-hidden
      w={largura}
      h={altura}
      bg="dark.5"
      style={{ flex: 'none', overflow: 'hidden', borderRadius: 'var(--mantine-radius-xs)' }}
    >
      {url && !falhou && (
        <img
          src={url}
          alt=""
          loading="lazy"
          width={largura}
          height={altura}
          onError={() => setFalhou(true)}
          style={{ display: 'block', objectFit: 'cover' }}
        />
      )}
    </Box>
  )
}

/**
 * A miniatura de 64×36 de uma linha do painel. A URL assinada só é pedida quando a linha entra na
 * tela; passar o ponteiro mostra o quadro maior (320×180) numa dica. `caminho` nulo é o retângulo.
 */
export function MiniaturaDoPainel({
  caminho,
  urlDoQuadro,
}: {
  caminho: string | null
  urlDoQuadro: ((caminho: string) => Promise<string>) | undefined
}) {
  const raiz = useRef<HTMLDivElement>(null)
  const [visivel, setVisivel] = useState(typeof IntersectionObserver === 'undefined')
  const [url, setUrl] = useState<string | null>(null)

  useEffect(() => {
    const el = raiz.current
    if (visivel || !el) return
    const olho = new IntersectionObserver((entradas) => {
      if (entradas.some((e) => e.isIntersecting)) {
        setVisivel(true)
        olho.disconnect()
      }
    })
    olho.observe(el)
    return () => olho.disconnect()
  }, [visivel])

  useEffect(() => {
    if (!visivel || !caminho || !urlDoQuadro) return
    let ativo = true
    urlDoQuadro(caminho).then(
      (u) => {
        if (ativo) setUrl(u)
      },
      // Sem a URL a linha fica com o retângulo; o quadro não é o que a pessoa veio ver.
      () => undefined,
    )
    return () => {
      ativo = false
    }
  }, [visivel, caminho, urlDoQuadro])

  return (
    <div ref={raiz} style={{ flex: 'none' }}>
      <Tooltip
        disabled={!url}
        withinPortal
        label={<Quadro url={url} largura={320} altura={180} />}
        p={0}
        openDelay={200}
      >
        <div>
          <Quadro url={url} largura={64} altura={36} />
        </div>
      </Tooltip>
    </div>
  )
}
