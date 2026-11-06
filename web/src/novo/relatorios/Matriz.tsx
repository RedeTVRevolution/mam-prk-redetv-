import { cn } from "cn";
import { duracaoLegivel } from "../../tempoDeTela.ts";
import { nomeDoTipo, TIPOS_DE_INSERCAO, type MarcaResumida } from "../../marcas.ts";
import { passoDaEscala, type Passo } from "./escala.ts";

// Cada passo com o texto que passa no AA sobre ele (tokens.test.ts confere): escuro nos claros, branco nos escuros.
const CLASSE: Record<Passo, string> = {
  100: "bg-seq-100 text-background",
  250: "bg-seq-250 text-background",
  400: "bg-seq-400 text-background",
  500: "bg-seq-500 text-primary-foreground",
  600: "bg-seq-600 text-primary-foreground",
};

/**
 * Tempo por marca e tipo de inserção, com a cor na escala sequencial; coluna sem nenhum valor some, e
 * os tipos que a tela não conhece entram no fim com o código por nome. Clicar numa célula chama `aoEscolher`.
 */
export function Matriz({
  marcas,
  aoEscolher,
}: {
  marcas: MarcaResumida[];
  aoEscolher: (marca: string, tipo: string) => void;
}) {
  const tempo = (m: MarcaResumida, tipo: string) => m.por_tipo.find((t) => t.tipo === tipo)?.tempo_ms ?? 0;
  const tipos = [...new Set([...Object.keys(TIPOS_DE_INSERCAO), ...marcas.flatMap((m) => m.por_tipo.map((t) => t.tipo))])].filter(
    (tipo) => marcas.some((m) => tempo(m, tipo) > 0),
  );
  const maximo = Math.max(0, ...marcas.flatMap((m) => tipos.map((t) => tempo(m, t))));
  return (
    <div className="overflow-x-auto">
      <table aria-label="Tempo por marca e tipo de inserção" className="w-full border-separate border-spacing-0.5 text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr>
            <th scope="col" className="h-8 min-w-28 px-2 text-left font-semibold">
              Marca
            </th>
            {tipos.map((t) => (
              <th key={t} scope="col" className="h-8 min-w-24 px-2 text-center font-semibold">
                {nomeDoTipo(t)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {marcas.map((m) => (
            <tr key={m.marca}>
              <th scope="row" className="h-8 max-w-48 truncate px-2 text-left font-normal" title={m.marca}>
                {m.marca}
              </th>
              {tipos.map((t) => {
                const ms = tempo(m, t);
                const passo = passoDaEscala(ms, maximo);
                return (
                  <td key={t} className="p-0 text-center">
                    {passo && (
                      <button
                        type="button"
                        aria-label={`${m.marca}, ${nomeDoTipo(t)}: ${duracaoLegivel(ms)}`}
                        onClick={() => aoEscolher(m.marca, t)}
                        className={cn("h-8 w-full rounded-xs px-2 text-xs tabular-nums hover:brightness-110", CLASSE[passo])}
                      >
                        {duracaoLegivel(ms)}
                      </button>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
