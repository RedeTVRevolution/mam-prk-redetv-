import { urlSegura } from './urlSegura.ts'

/** Entrega a decupagem (o arquivo que o servidor mandou) como `<nome>.decupagem.json`. */
export function baixarDecupagem(nome: string, arquivo: Blob) {
  baixarArquivo(`${nome.replace(/\.mp4$/i, '')}.decupagem.json`, arquivo)
}

/** Inicia o download por uma URL assinada (`Content-Disposition: attachment`), sem sair da página. */
export function baixarPelaUrl(url: string) {
  const segura = urlSegura(url)
  if (!segura) return
  const ancora = document.createElement('a')
  ancora.href = segura
  ancora.download = ''
  ancora.click()
}

/** Entrega um CSV (ou outro arquivo já pronto) com o nome dado. */
export function baixarArquivo(nome: string, conteudo: Blob) {
  const url = URL.createObjectURL(conteudo)
  const ancora = document.createElement('a')
  ancora.href = url
  ancora.download = nome
  ancora.click()
  // Revogar na hora pode cancelar o download em alguns navegadores.
  setTimeout(() => URL.revokeObjectURL(url), 0)
}
