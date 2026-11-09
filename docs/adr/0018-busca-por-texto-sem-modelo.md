# Busca por texto sem interpretação pelo modelo

Em 9/11/2026, o Bruno decidiu retirar o Gemini e o Model Armor da busca por texto (#517). O entendimento consumia toda a frase em filtros automáticos: “tapete vermelho” virava objeto e cor, e “tarde é sua” virava programa, deixando de achar falas já indexadas. Esses filtros não justificavam o custo nem a perda de resultados.

A frase saneada segue inteira para a busca por palavra e por significado, como no antigo plano B. As aspas continuam delimitando a frase exata (`separar_aspas`). O código reconhece nomes inteiros do catálogo de pessoas na frase, sem diferenciar acento ou maiúscula, e acrescenta as cláusulas de imagem, fala e GC; não completa nomes parciais nem corrige grafia.

Programa, período, pessoa, marca e tipo são filtros escolhidos na tela. Os botões de evidência também restringem o texto livre: Imagem corresponde a `plano`, Fala a `fala` e GC a `texto_na_tela`; sem seleção, todos os tipos entram. O texto nunca monta nomes de campos ou operadores de filtros, e as permissões e a lixeira continuam impostas pelo servidor.

Na busca por imagem, o Gemini só descreve o objeto da foto em um termo curto. Esse termo passa pelo mesmo caminho local do texto, sem segunda chamada ao modelo nem Model Armor. Isso substitui o entendimento e as duas chamadas em série descritos nos ADRs 0013 e 0015; a foto continua validada e regravada, e falha na descrição continua respondendo 503.

Saem a instrução, o esquema, a montagem e o cache do entendimento (#489). A cópia curta compartilhada do catálogo e a lista paginada de resultados continuam. O manifesto da decupagem deixa de listar a consulta como etapa; a versão fixada passa a `2026.11.8`, sem mudança nos modelos; a instrução da decupagem ganhou uma frase (toda pessoa citada numa pauta precisa estar em `pessoas`), o que muda só o hash dela. A resposta mantém `entendida` por compatibilidade, agora com os filtros da tela e o termo da foto, e `plano_b` fica `false`. A tela usa apenas os filtros da URL e permite desligar todos os botões. Embedding do índice e Ranking API continuam no caminho da busca.
