import { Badge, Box, Button, Group, Stack, Text } from '@mantine/core'
import { useEffect, useRef, useState } from 'react'
import { codigoDoErro, type FotoDoNome, type FotosDoNome } from './api.ts'
import { Quadro } from './Miniatura.tsx'
import { CORES } from './tema.ts'

const RESULTADO: Record<NonNullable<FotoDoNome['resultado']>, string> = {
  confere: 'confere',
  nao_confere: 'não confere',
}

type Estado = { fase: 'carregando' } | { fase: 'pronto'; fotos: FotoDoNome[] } | { fase: 'falhou'; codigo: string }

/**
 * A comparação do rosto: o quadro da aparição e as fotos de referência do nome, cada uma com a
 * página de origem e o resultado da conferência em palavras (nunca uma porcentagem). Abre por
 * cima do painel lateral; `Esc` fecha. As fotos são dado sensível (LGPD): vêm por URL assinada.
 */
export function ComparacaoDoRosto({
  nome,
  quadro,
  carregar,
  urlDoQuadro,
  aoFechar,
}: {
  nome: string
  /** O JPEG da aparição (`null` sem quadro). */
  quadro: string | null
  carregar: () => Promise<FotosDoNome>
  urlDoQuadro?: (caminho: string) => Promise<string>
  aoFechar: () => void
}) {
  const [estado, setEstado] = useState<Estado>({ fase: 'carregando' })
  const [urlDoQuadroPronta, setUrlDoQuadro] = useState<string | null>(null)
  const titulo = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    let ativo = true
    carregar().then(
      (r) => ativo && setEstado({ fase: 'pronto', fotos: r.fotos }),
      (e: unknown) => ativo && setEstado({ fase: 'falhou', codigo: codigoDoErro(e) }),
    )
    return () => {
      ativo = false
    }
  }, [carregar])

  useEffect(() => {
    if (!quadro || !urlDoQuadro) return
    let ativo = true
    urlDoQuadro(quadro).then(
      (u) => ativo && setUrlDoQuadro(u),
      // Sem o quadro fica o retângulo: o que a pessoa veio ver são as fotos.
      () => undefined,
    )
    return () => {
      ativo = false
    }
  }, [quadro, urlDoQuadro])

  // O foco vai para o painel ao abrir e volta ao selo que o abriu ao fechar.
  useEffect(() => {
    const aberto = document.activeElement
    titulo.current?.focus()
    return () => {
      if (aberto instanceof HTMLElement && aberto.isConnected) aberto.focus()
    }
  }, [])

  useEffect(() => {
    const aoTeclar = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.preventDefault()
      aoFechar()
    }
    document.addEventListener('keydown', aoTeclar)
    return () => document.removeEventListener('keydown', aoTeclar)
  }, [aoFechar])

  return (
    <Box
      role="dialog"
      aria-label={`Comparação do rosto de ${nome}`}
      p="sm"
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 10,
        overflowY: 'auto',
        background: 'var(--mantine-color-body)',
        borderRadius: 'var(--mantine-radius-md)',
      }}
    >
      <Stack gap="sm">
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Stack gap={0}>
            <Text ref={titulo} tabIndex={-1} fw={600} style={{ outline: 'none' }}>
              {`Comparação do rosto: ${nome}`}
            </Text>
            <Text size="xs" c="dimmed">
              O quadro do vídeo e as fotos de referência do nome.
            </Text>
          </Stack>
          <Button size="compact-xs" variant="default" onClick={aoFechar} aria-label="Fechar a comparação (Esc)">
            Fechar
          </Button>
        </Group>
        <Stack gap={4}>
          <Text size="xs" c="dimmed" fw={600}>
            No vídeo
          </Text>
          <Quadro url={urlDoQuadroPronta} largura={320} altura={180} />
        </Stack>
        <Text size="xs" c="dimmed" fw={600}>
          Fotos de referência
        </Text>
        {estado.fase === 'carregando' && (
          <Text size="sm" c="dimmed">
            Carregando as fotos…
          </Text>
        )}
        {estado.fase === 'falhou' && (
          <Text size="sm" role="alert">
            Não foi possível carregar as fotos de referência. Feche e abra a comparação de novo.{' '}
            <Text span size="xs" c="dimmed">{`Detalhe: ${estado.codigo}`}</Text>
          </Text>
        )}
        {estado.fase === 'pronto' && estado.fotos.length === 0 && (
          <Text size="sm" c="dimmed">
            Este nome não tem fotos de referência guardadas.
          </Text>
        )}
        {estado.fase === 'pronto' &&
          estado.fotos.map((f, i) => (
            <Group key={f.url} gap="sm" wrap="nowrap" align="flex-start">
              <img
                src={f.url}
                alt={`Foto de referência ${i + 1} de ${nome}`}
                width={120}
                height={120}
                style={{ objectFit: 'cover', flex: 'none', borderRadius: 'var(--mantine-radius-sm)' }}
              />
              <Stack gap={4}>
                {f.pagina_url ? (
                  <Text
                    size="sm"
                    component="a"
                    href={f.pagina_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`Página de origem da foto ${i + 1}: ${f.dominio}`}
                  >
                    {f.dominio}
                  </Text>
                ) : (
                  <Text size="sm" c="dimmed">
                    Sem página de origem
                  </Text>
                )}
                <Badge
                  size="sm"
                  variant={f.resultado === 'confere' ? 'light' : 'outline'}
                  color={f.resultado === 'confere' ? CORES.concluido : CORES.textoSecundario}
                >
                  {f.resultado ? RESULTADO[f.resultado] : 'sem resultado'}
                </Badge>
              </Stack>
            </Group>
          ))}
      </Stack>
    </Box>
  )
}
