# Lixeira e purga: a única exceção a "nunca apagar"

O repositório de correções (`api/correcoes.py`) só acrescenta, e o glossário diz que a saída do modelo nunca é apagada. Essas regras valem para o trabalho do dia a dia e continuam valendo.

**A lixeira não apaga nada.** Mandar um vídeo para a lixeira só grava no Job `lixeira` (quando, quem, motivo). O vídeo some na hora para quem não é Administrador: a lista, as rotas do Job (404), a busca e o que um sistema enviou. A restauração desfaz o campo e tudo volta como estava. Cada envio e restauração grava um registro na auditoria, com o motivo e os números do impacto.

**A purga é a única exceção.** Passados 30 dias na lixeira, ou antes por decisão do Administrador, só o processo da purga (#145) apaga decupagem, correções, arquivos do Storage e momentos do índice, e deixa o próprio registro na auditoria, que ninguém altera. Nenhuma outra rota apaga correção nem saída do modelo.

**Conteúdo repartido.** Dois Jobs com o mesmo arquivo (mesma chave de conteúdo, o SHA-256) dividem o processamento. A lixeira e a purga de um Job não tocam no processamento enquanto outro Job apontar para ele; o impacto lista esses outros Jobs.

**Rostos saem cedo (LGPD).** Pessoa do catálogo tem dado biométrico: as referências de rosto dela saem já no envio para a lixeira, sem esperar os 30 dias. A regra é aplicada no #151.
