// A frase em português de cada `codigo_falha` de api/jobs.py; o código fica numa dica, para o suporte.
export const FRASES_DE_FALHA: Record<string, string> = {
  formato_invalido: 'O arquivo não é um MP4 válido. Envie um vídeo em MP4.',
  arquivo_corrompido: 'O arquivo está corrompido e não pôde ser lido. Exporte o vídeo de novo e envie.',
  codec_nao_suportado: 'O vídeo usa um codec que não aceitamos. Envie em H.264.',
  duracao_excedida: 'O vídeo é mais longo do que o limite aceito. Envie um vídeo mais curto.',
  upload_expirado: 'O envio não terminou a tempo. Envie o vídeo de novo.',
  analise_falhou: 'Não foi possível decupar o vídeo. Tente enviar de novo; se repetir, chame o suporte.',
  transcricao_falhou: 'Não foi possível transcrever a fala do vídeo. Tente enviar de novo; se repetir, chame o suporte.',
  ocr_falhou: 'Não foi possível ler os textos na tela do vídeo. Tente enviar de novo; se repetir, chame o suporte.',
  processamento_interrompido: 'O processamento parou por um erro interno. Tente enviar de novo; se repetir, chame o suporte.',
}

const GENERICA = 'O processamento do vídeo falhou. Envie de novo; se repetir, chame o suporte.'

/** Nunca devolve o código: um código novo, ainda sem frase, cai na frase genérica. */
export function fraseDaFalha(codigo: string): string {
  return Object.hasOwn(FRASES_DE_FALHA, codigo) ? FRASES_DE_FALHA[codigo] : GENERICA
}
