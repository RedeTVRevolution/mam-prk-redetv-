# Sem organização e sem VPC-SC: o dev vira produção, com os riscos aceitos por escrito

Em 2/11/2026, o Bruno decidiu com o Ilton (#296) que o projeto não nasce numa organização do GCP, que não há VPC Service Controls (VPC-SC) e que o dev vira produção. Só existem dev e produção, sem staging. A segurança fica por IAM e Cloud Armor; em produção, o Cloud Armor só aceita os IPs da RedeTV, e quem está fora entra por VPN.

## Por que

- **Sem organização.** O VPC-SC é configurado no nível da organização; sem ela, não há perímetro a criar.
- **Custo.** Um terceiro projeto (staging) e o perímetro com nível de acesso custariam mais do que a PoC justifica. O staging já saiu do repositório: `infra/ambientes/` só tem `prod`.
- **Um projeto só.** O mesmo projeto, depois de pronto, passa a ser a produção; não há promoção de imagem entre projetos.

## Riscos aceitos

- **URLs assinadas passam por fora do Cloud Armor.** As URLs do Storage (upload, reprodução, quadros, download) não passam pelo balanceador e valem de qualquer IP enquanto não expiram.
- **Sem VPC-SC, uma credencial ou um Job comprometido alcança as APIs do Google** e pode copiar dados para fora do projeto.
- **Sem registros de acesso (Data Access logs) do Storage, do Firestore e do BigQuery.** O Bruno decidiu não ligá-los, pelo custo (#370, fechado em 06/11/2026). Quem leu ou baixou um objeto direto pelas APIs do Google não fica registrado; vale só a auditoria da aplicação.

## Mitigações

- Nenhuma chave de conta de serviço.
- Cabeçalhos de segurança e consulta da busca limitada (#372).
- URL de upload de vida curta, objeto escrito uma vez e uploads abandonados expirados (#369).
- Teto de Jobs por hora por chave e por pessoa (#371).
- Banco Firestore separado para papéis, chaves e auditoria, fora do alcance dos Jobs que abrem vídeo (#368).
- Borda com domínio, IPs da RedeTV e WAF quando o dev virar produção (#366).

## O que muda no Plano

O `docs/Plano_MAM.md` deixa de falar em três projetos, staging e VPC-SC e aponta para esta ADR.
