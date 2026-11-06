import { useState } from "react";

interface Estado {
  chave: string;
  cursores: string[];
  aberta: string | null;
  /** Um recorte da linha aberta (o tipo de inserção da célula da matriz); "" é a linha inteira. */
  recorte: string;
}

const COMECO = (chave: string): Estado => ({ chave, cursores: [""], aberta: null, recorte: "" });

/**
 * A página da tabela e a linha aberta. A página é a pilha dos cursores já percorridos (o do topo
 * é o da página atual, "" a primeira), então voltar não guarda nada além disso. Quando a `chave`
 * (os filtros) muda, tudo recomeça, sem efeito.
 */
export function useTabelaPaginada(chave: string) {
  const [estado, definir] = useState<Estado>(() => COMECO(chave));
  let atual = estado;
  if (estado.chave !== chave) {
    // Grava o recomeço (ajuste durante o render, sem efeito): só mascarar o estado velho
    // faria A → B → A voltar à página e à linha aberta de A.
    atual = COMECO(chave);
    definir(atual);
  }
  return {
    cursor: atual.cursores[atual.cursores.length - 1],
    pagina: atual.cursores.length,
    aberta: atual.aberta,
    recorte: atual.recorte,
    avancar: (proximo: string) => definir({ ...atual, cursores: [...atual.cursores, proximo], aberta: null, recorte: "" }),
    voltar: () => definir({ ...atual, cursores: atual.cursores.slice(0, -1), aberta: null, recorte: "" }),
    abrir: (id: string | null, recorte = "") => definir({ ...atual, aberta: id, recorte }),
    /** Do gráfico: a linha está na primeira página, que é de onde o gráfico tira as barras. */
    mostrarNaPrimeira: (id: string, recorte = "") => definir({ ...atual, cursores: [""], aberta: id, recorte }),
  };
}
