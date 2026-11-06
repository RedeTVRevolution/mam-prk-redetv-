import { IconDownload } from "@tabler/icons-react";
import { useId, type ReactNode } from "react";
import { useBaixarCsv } from "../../useRelatorio.ts";
import { Button } from "../ui/button.tsx";
import { Falha } from "./Falha.tsx";

// O que os relatórios (Tempo de tela, Marcas e o Painel da diretoria) têm em comum na tela.

/** Um campo de filtro com o rótulo pequeno em cima; `children` recebe o id para o `htmlFor`. */
export function Campo({
  rotulo,
  children,
}: {
  rotulo: string;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <div className="grid min-w-0 gap-1">
      <label htmlFor={id} className="text-xs text-muted-foreground">
        {rotulo}
      </label>
      {children(id)}
    </div>
  );
}

/** O CSV do relatório. Montado com `key`, a falha (ou um pedido ainda no ar) não passa para o próximo. */
export function BaixarCsv({
  arquivo,
  pedir,
  desligado,
}: {
  arquivo: string;
  pedir: () => Promise<Blob>;
  desligado: boolean;
}) {
  const csv = useBaixarCsv(arquivo, pedir);
  return (
    <>
      <Button
        type="button"
        variant="secondary"
        className="ml-auto"
        disabled={desligado}
        onClick={() => void csv.baixar()}
      >
        <IconDownload size={16} stroke={1.75} aria-hidden /> Baixar CSV
      </Button>
      {csv.falhou && (
        <div className="basis-full">
          <Falha
            mensagem="Não foi possível baixar o CSV agora."
            codigo="csv"
          />
        </div>
      )}
    </>
  );
}
