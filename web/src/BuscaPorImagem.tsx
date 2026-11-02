import { Button, Group, Loader, Paper, Stack, Text } from '@mantine/core'
import { IconPhotoSearch } from '@tabler/icons-react'
import { useEffect, useRef, useState } from 'react'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import { codigoDoErro, FalhaNaApi, PedidoInvalido, SessaoExpirada, type ClienteDaApi } from './api.ts'
import { enderecoDaBusca } from './rotas.ts'
import { contagemDeVideos, type ConsultaDaBusca, type ResultadoDaBusca } from './busca.ts'
import { GradeDePlanos } from './GradeDePlanos.tsx'
import { CORES } from './tema.ts'

const PLANOS_POR_VEZ = 50

type Carga =
  | { tipo: 'carregando' }
  | { tipo: 'pronta'; resultado: ResultadoDaBusca }
  | { tipo: 'erro'; mensagem: string; codigo: string }

function mensagemDoErro(erro: unknown): string {
  // A API explica o tipo e o tamanho errados em português.
  if (erro instanceof PedidoInvalido) return erro.message
  if (erro instanceof FalhaNaApi && erro.status === 429) return 'Muitas buscas seguidas. Espere alguns segundos.'
  if (erro instanceof FalhaNaApi && erro.status === 503) return 'A busca por imagem não está disponível agora.'
  if (erro instanceof FalhaNaApi && erro.status === 504) return 'A busca demorou demais. Tente de novo.'
  return 'Não foi possível buscar agora. Tente de novo.'
}

/**
 * "Buscar por imagem": a foto vai à API só para a consulta, que a regrava e a descarta; aqui ela
 * fica na memória da página e não entra na URL. O programa e o período da busca valem.
 */
export function BuscaPorImagem({ api, consulta }: { api: ClienteDaApi; consulta: ConsultaDaBusca }) {
  const [foto, setFoto] = useState<File | null>(null)
  const [carga, setCarga] = useState<Carga | null>(null)
  const [tentativas, setTentativas] = useState(0)
  const [arrastando, setArrastando] = useState(false)
  const campo = useRef<HTMLInputElement>(null)

  // Só o programa e o período (e não o texto, os chips ou a ordem) mudam a busca da foto.
  const filtros = enderecoDaBusca({ ...consulta, q: '', evidencias: null, ordem: 'relevancia', modo: 'texto', pessoa: null, marca: null, tipo: null })
  const consultaAtual = useRef(consulta)
  useEffect(() => {
    consultaAtual.current = consulta
  })

  useEffect(() => {
    if (!foto) return
    let ativo = true
    // Cada foto ou filtro novo recomeça pelo carregamento.
    // oxlint-disable-next-line react/set-state-in-effect
    setCarga({ tipo: 'carregando' })
    api.buscarPorImagem(foto, consultaAtual.current, PLANOS_POR_VEZ).then(
      (resultado) => {
        if (ativo) setCarga({ tipo: 'pronta', resultado })
      },
      (erro: unknown) => {
        if (!ativo || erro instanceof SessaoExpirada) return
        setCarga({ tipo: 'erro', mensagem: mensagemDoErro(erro), codigo: codigoDoErro(erro) })
      },
    )
    return () => {
      ativo = false
    }
  }, [api, foto, filtros, tentativas])

  function escolher(arquivo: File | undefined) {
    if (arquivo) setFoto(arquivo)
    if (campo.current) campo.current.value = ''
  }

  const resultado = carga?.tipo === 'pronta' ? carga.resultado : null
  const planos = resultado?.videos.flatMap((v) => v.momentos.filter((m) => m.tipo === 'plano')).length ?? 0

  return (
    <Stack gap="sm" component="section" aria-label="Buscar por imagem">
      <Paper
        withBorder
        p="sm"
        onDragOver={(e) => {
          e.preventDefault()
          setArrastando(true)
        }}
        onDragLeave={() => setArrastando(false)}
        onDrop={(e) => {
          e.preventDefault()
          setArrastando(false)
          escolher(e.dataTransfer.files[0])
        }}
        style={{ borderStyle: 'dashed', borderColor: arrastando ? CORES.foco : undefined }}
      >
        <Group gap="sm">
          <Button
            type="button"
            size="compact-sm"
            variant="default"
            leftSection={<IconPhotoSearch size={16} aria-hidden />}
            onClick={() => campo.current?.click()}
          >
            Buscar por imagem
          </Button>
          <input
            ref={campo}
            type="file"
            accept="image/jpeg,image/png"
            aria-label="Foto para buscar"
            hidden
            onChange={(e) => escolher(e.target.files?.[0])}
          />
          <Text size="sm" c={CORES.textoSecundario}>
            {foto ? foto.name : 'Arraste uma foto (JPEG ou PNG) ou escolha o arquivo.'}
          </Text>
          {foto && (
            <Button
              type="button"
              size="compact-sm"
              variant="subtle"
              onClick={() => {
                setFoto(null)
                setCarga(null)
              }}
            >
              Limpar
            </Button>
          )}
        </Group>
      </Paper>
      {carga?.tipo === 'carregando' && <Loader role="status" aria-label="Buscando pela imagem" />}
      {carga?.tipo === 'erro' && (
        <AlertaDeErro
          mensagem={carga.mensagem}
          codigo={carga.codigo}
          aoTentar={() => setTentativas((n) => n + 1)}
        />
      )}
      {resultado && (
        <Stack gap="sm">
          <Text size="sm" role="status">
            {planos === 0
              ? 'Nenhum plano parecido. Tire um filtro ou tente outra foto.'
              : `${planos} ${planos === 1 ? 'plano parecido' : 'planos parecidos'} em ${contagemDeVideos(resultado.videos.length)}`}
          </Text>
          <GradeDePlanos videos={resultado.videos} busca="" />
        </Stack>
      )}
    </Stack>
  )
}
