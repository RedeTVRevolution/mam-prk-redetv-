import { Alert, Button, FileButton, Modal, Progress, Select, Stack, Text, TextInput } from '@mantine/core'
import { IconAlertTriangle, IconUpload } from '@tabler/icons-react'
import { useRef, useState } from 'react'
import { type ClienteDaApi, PedidoInvalido } from './api.ts'
import { CORES } from './tema.ts'
import { validarArquivo } from './envio/arquivo.ts'
import { enviarRetomavel } from './envio/upload.ts'

type Envio =
  | { tipo: 'parado' }
  | { tipo: 'enviando'; fracao: number }
  | { tipo: 'concluido' }
  | { tipo: 'erro'; mensagem: string }

/** Hoje, no fuso da emissora: a API recusa data de exibição no futuro. */
function hoje(): string {
  return new Date().toLocaleDateString('sv-SE', { timeZone: 'America/Sao_Paulo' })
}

function mensagemDoErro(erro: unknown): string {
  if (erro instanceof PedidoInvalido && erro.message === 'Data de exibição no futuro') {
    return 'A data de exibição não pode ser no futuro. Corrija a data e envie de novo.'
  }
  return 'Não foi possível enviar o vídeo. Tente de novo.'
}

/** O diálogo de envio: programa e data de exibição antes, o arquivo por último (ele inicia o envio). */
export default function EnvioDeVideo({
  api,
  programas,
  aberto,
  aoFechar,
  aoCriar,
}: {
  api: ClienteDaApi
  programas: string[]
  aberto: boolean
  aoFechar: () => void
  /** O Job já existe; a tabela o mostra no topo enquanto o upload segue. */
  aoCriar: () => void
}) {
  const [envio, setEnvio] = useState<Envio>({ tipo: 'parado' })
  const [programa, setPrograma] = useState<string | null>(null)
  const [data, setData] = useState('')
  const limparSeletor = useRef<() => void>(null)
  const enviando = envio.tipo === 'enviando'

  // Reabrir o diálogo começa um envio novo, sem o aviso nem os campos do anterior.
  function fechar() {
    setEnvio({ tipo: 'parado' })
    setPrograma(null)
    setData('')
    aoFechar()
  }

  async function escolher(arquivo: File | null) {
    if (!arquivo) return
    // Sem isso, escolher de novo o mesmo arquivo não dispara a troca.
    limparSeletor.current?.()
    const motivo = await validarArquivo(arquivo)
    if (motivo) {
      setEnvio({ tipo: 'erro', mensagem: motivo })
      return
    }
    setEnvio({ tipo: 'enviando', fracao: 0 })
    try {
      const criado = await api.criarJob({
        nome: arquivo.name,
        tamanho_bytes: arquivo.size,
        tipo: arquivo.type,
        ...(programa ? { programa } : {}),
        ...(data ? { data_exibicao: data } : {}),
      })
      aoCriar()
      await enviarRetomavel(criado.url_de_upload, arquivo, {
        aoProgresso: (fracao) => setEnvio({ tipo: 'enviando', fracao }),
      })
      setEnvio({ tipo: 'concluido' })
    } catch (erro) {
      setEnvio({ tipo: 'erro', mensagem: mensagemDoErro(erro) })
    }
  }

  return (
    <Modal
      opened={aberto}
      onClose={fechar}
      title="Enviar vídeo"
      closeOnEscape={!enviando}
      closeOnClickOutside={!enviando}
      withCloseButton={!enviando}
    >
      <Stack gap="sm">
        {programas.length > 0 && (
          <Select
            label="Programa"
            placeholder="Sem programa"
            clearable
            data={programas}
            value={programa}
            onChange={setPrograma}
            disabled={enviando}
          />
        )}
        <TextInput
          type="date"
          label="Data de exibição (opcional)"
          value={data}
          max={hoje()}
          onChange={(e) => setData(e.currentTarget.value)}
          disabled={enviando}
        />
        <FileButton
          accept=".mp4,video/mp4"
          onChange={(arquivo) => void escolher(arquivo)}
          resetRef={limparSeletor}
          disabled={enviando}
          inputProps={{ 'aria-label': 'Arquivo MP4', disabled: enviando }}
        >
          {(props) => (
            <Button {...props} leftSection={<IconUpload size={16} />} disabled={enviando}>
              Escolher o MP4 e enviar
            </Button>
          )}
        </FileButton>
        {envio.tipo === 'enviando' && (
          <Progress aria-label="Progresso do envio" value={envio.fracao * 100} />
        )}
        {envio.tipo === 'concluido' && (
          <Text size="sm" c={CORES.concluido}>
            Envio concluído. O vídeo já aparece no acervo.
          </Text>
        )}
        {envio.tipo === 'erro' && (
          <Alert color={CORES.falhou} variant="light" icon={<IconAlertTriangle />} role="alert">
            {envio.mensagem}
          </Alert>
        )}
      </Stack>
    </Modal>
  )
}
