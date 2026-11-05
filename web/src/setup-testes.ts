// O jsdom não tem estas APIs, que o Mantine usa.
window.matchMedia ??= (consulta: string) =>
  ({
    matches: false,
    media: consulta,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }) as MediaQueryList

// O recharts só desenha quando o ResizeObserver informa um tamanho; o jsdom não mede nada.
globalThis.ResizeObserver ??= class {
  aviso: ResizeObserverCallback
  constructor(aviso: ResizeObserverCallback) {
    this.aviso = aviso
  }
  observe(alvo: Element) {
    const contentRect = { width: 800, height: 400 } as DOMRectReadOnly
    this.aviso([{ target: alvo, contentRect } as ResizeObserverEntry], this as unknown as ResizeObserver)
  }
  unobserve() {}
  disconnect() {}
}

// O Select do Mantine rola até a opção ativa.
window.HTMLElement.prototype.scrollIntoView ??= () => {}
