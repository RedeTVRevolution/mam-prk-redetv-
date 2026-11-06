import { IconCircleCheck, IconCloudUpload } from '@tabler/icons-react'
import { cn } from 'cn'
import { useId, useRef, useState } from 'react'
import { hoje, mensagemDoErroDoEnvio, validarArquivo } from '../envio/arquivo.ts'
import { enviarRetomavel } from '../envio/upload.ts'
import { Falha } from './comum/Falha.tsx'
import { useApi, useProgramas } from './consultas.ts'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from './ui/dialog.tsx'

type Envio = { tipo: 'parado' } | { tipo: 'enviando'; fracao: number } | { tipo: 'concluido' } | { tipo: 'erro'; mensagem: string }

/**
 * O envio: programa e data de exibição antes, o arquivo por último (ele inicia o envio). As
 * regras são as da interface atual: o MP4 é conferido antes de chamar a API, sem data não se
 * envia, e o Job já existe (`aoCriar`) enquanto o upload segue.
 */
export function EnvioDeVideo({ aberto, aoMudar, aoCriar }: { aberto: boolean; aoMudar: (aberto: boolean) => void; aoCriar: () => void }) {
  return (
    <Dialog open={aberto} onOpenChange={aoMudar}>
      {/* Montado a cada abertura: reabrir começa um envio novo, sem o aviso nem os campos do anterior. */}
      {aberto && <Corpo aoCriar={aoCriar} />}
    </Dialog>
  )
}

function Corpo({ aoCriar }: { aoCriar: () => void }) {
  const api = useApi()
  const programas = useProgramas()
  const ids = useId()
  const [envio, setEnvio] = useState<Envio>({ tipo: 'parado' })
  const [programa, setPrograma] = useState('')
  const [data, setData] = useState('')
  const [arrastando, setArrastando] = useState(false)
  const enviando = envio.tipo === 'enviando'
  // Ligada antes do primeiro await: dois arquivos soltos seguidos não criam dois Jobs, e o
  // diálogo não fecha enquanto o arquivo é conferido (o estado ainda não diz "enviando").
  const ocupado = useRef(false)

  async function escolher(arquivo: File | undefined) {
    if (!arquivo || ocupado.current) return
    ocupado.current = true
    try {
      await enviar(arquivo)
    } finally {
      ocupado.current = false
    }
  }

  async function enviar(arquivo: File) {
    const motivo = await validarArquivo(arquivo)
    if (motivo) return setEnvio({ tipo: 'erro', mensagem: motivo })
    if (!data) return setEnvio({ tipo: 'erro', mensagem: 'Informe a data de exibição antes de escolher o arquivo.' })
    setEnvio({ tipo: 'enviando', fracao: 0 })
    try {
      const criado = await api.criarJob({
        nome: arquivo.name,
        tamanho_bytes: arquivo.size,
        tipo: arquivo.type,
        ...(programa ? { programa } : {}),
        data_exibicao: data,
      })
      aoCriar()
      await enviarRetomavel(criado.url_de_upload, arquivo, { aoProgresso: (fracao) => setEnvio({ tipo: 'enviando', fracao }) })
      setEnvio({ tipo: 'concluido' })
    } catch (erro) {
      setEnvio({ tipo: 'erro', mensagem: mensagemDoErroDoEnvio(erro) })
    }
  }

  const segurar = (e: Event) => ocupado.current && e.preventDefault()
  const campo = 'h-8 w-full rounded-sm border border-strong bg-input px-2 text-sm font-normal disabled:opacity-50'
  return (
    <DialogContent className="sm:max-w-lg" mostrarFechar={!enviando} onEscapeKeyDown={segurar} onPointerDownOutside={segurar} onInteractOutside={segurar}>
      <DialogTitle className="flex items-center gap-2">
        <IconCloudUpload size={20} stroke={1.75} className="text-muted-foreground" aria-hidden /> Enviar vídeo
      </DialogTitle>
      <DialogDescription>O vídeo entra na fila de decupagem assim que o envio termina.</DialogDescription>
      <div className="grid gap-3 sm:grid-cols-2">
        {programas.length > 0 && (
          <label className="grid gap-1 text-xs font-medium">
            Programa
            <select value={programa} onChange={(e) => setPrograma(e.target.value)} disabled={enviando} className={campo}>
              <option value="">Sem programa</option>
              {programas.map((p) => (
                <option key={p}>{p}</option>
              ))}
            </select>
          </label>
        )}
        <label className="grid gap-1 text-xs font-medium">
          <span>
            Data de exibição <span className="text-destructive">*</span>
          </span>
          <input type="date" required value={data} max={hoje()} onChange={(e) => setData(e.target.value)} disabled={enviando} className={cn(campo, 'scheme-dark')} />
        </label>
      </div>
      <label
        onDragOver={(e) => {
          e.preventDefault()
          if (!enviando) setArrastando(true)
        }}
        onDragLeave={() => setArrastando(false)}
        onDrop={(e) => {
          e.preventDefault()
          setArrastando(false)
          void escolher(e.dataTransfer.files[0])
        }}
        className={cn(
          'flex flex-col items-center gap-2 rounded-sm border border-dashed px-4 py-6 text-center transition-colors has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-ring',
          enviando ? 'cursor-not-allowed border-strong opacity-50' : arrastando ? 'cursor-pointer border-primary bg-selected' : 'cursor-pointer border-strong hover:bg-card',
        )}
      >
        <input
          type="file"
          accept=".mp4,video/mp4"
          aria-label="Arquivo MP4"
          disabled={enviando}
          className="sr-only"
          onChange={(e) => {
            const arquivo = e.target.files?.[0]
            // Sem limpar, escolher de novo o mesmo arquivo não dispara a troca.
            e.target.value = ''
            void escolher(arquivo)
          }}
        />
        <IconCloudUpload size={24} stroke={1.5} className="text-muted-foreground" aria-hidden />
        <span className="text-sm">Arraste o MP4 aqui ou escolha o arquivo</span>
        <span className="text-xs text-muted-foreground">H.264, até 4 GB. O envio começa ao escolher.</span>
      </label>
      {envio.tipo === 'enviando' && (
        <div
          role="progressbar"
          aria-label="Progresso do envio"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(envio.fracao * 100)}
          aria-describedby={`${ids}-pct`}
          className="flex items-center gap-2"
        >
          <span className="h-1 flex-1 overflow-hidden rounded-full bg-secondary">
            <span className="block h-full bg-primary" style={{ width: `${envio.fracao * 100}%` }} />
          </span>
          <span id={`${ids}-pct`} className="w-10 text-right text-xs text-muted-foreground tabular-nums">
            {Math.round(envio.fracao * 100)}%
          </span>
        </div>
      )}
      {envio.tipo === 'concluido' && (
        <p role="status" className="flex items-center gap-2 text-ok">
          <IconCircleCheck size={16} stroke={1.75} aria-hidden /> Envio concluído. O vídeo já aparece no acervo.
        </p>
      )}
      {envio.tipo === 'erro' && <Falha mensagem={envio.mensagem} />}
    </DialogContent>
  )
}
