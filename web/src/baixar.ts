/** Entrega a decupagem como arquivo `<nome>.decupagem.json`. */
export function baixarDecupagem(nome: string, decupagem: unknown) {
  const blob = new Blob([JSON.stringify(decupagem, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const ancora = document.createElement('a')
  ancora.href = url
  ancora.download = `${nome.replace(/\.mp4$/i, '')}.decupagem.json`
  ancora.click()
  // Revogar na hora pode cancelar o download em alguns navegadores.
  setTimeout(() => URL.revokeObjectURL(url), 0)
}
