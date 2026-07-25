# Redesenho de alertas de estoque baixo

**Data:** 2026-07-24
**Repositórios:** `Unistock_Back` (Django/DRF/Celery) + `Unistock_Front` (Next.js) — 1 página nova no front.

## Contexto e objetivo

Hoje, cada queda de um produto abaixo do estoque mínimo gera **duas** coisas ao
mesmo tempo: uma notificação in-app (sininho) **e** um e-mail imediato por
produto. O objetivo é:

1. **Alerta imediato = só in-app.** Matar o e-mail por produto.
2. **Gerente enxerga tudo centralizado** — não só o que ele mesmo editou.
3. **Resumo diário por e-mail em PDF, às 7h** (começo do expediente — a loja
   abre 7h), com a lista de produtos abaixo do mínimo. O e-mail vai para o
   **e-mail da loja** (`Loja.email`), não para o e-mail pessoal: quem está no
   turno lê a caixa da loja, o responsável muda mas o e-mail não. **Um e-mail
   separado por loja** (PDF só daquela loja). O **gerente** recebe **um único
   PDF com todas as lojas juntas** (agrupadas por loja). Sem liga/desliga por
   enquanto: toda loja ativa, com e-mail cadastrado e com item baixo, recebe.

## O que já existe (não reconstruir)

- **Notificação in-app de estoque baixo** — `app/notifications/__init__.py`
  `notificar_estoque_baixo()` cria uma `Notificacao` no banco quando um produto
  cai `<=` mínimo. Dedup por episódio via FK `Notificacao.estoque`; quando o
  estoque se recupera, `EstoqueUpdateSerializer` apaga as notificações do
  episódio e uma nova queda volta a notificar.
- **API de notificações** — `NotificacaoViewSet` (listar / `marcar-lida` /
  `todas-lidas` / `limpar`).
- **Front** — página `/notificacoes` (sininho, marcar lida, limpar) já consome a
  API.
- **Digest diário** — `app/notifications/tasks.py` `disparar_digests` (beat a
  cada 15 min, respeita horário/dias/idempotência via `ultimo_digest_em`) +
  `enviar_digest` (hoje manda **texto puro**, só das lojas onde o usuário é
  responsável).
- **Gerador de PDF** — `app/relatorios/pedidos_pdf.py` (WeasyPrint, estilizado)
  — hoje só para relatório de pedidos, retorna `HttpResponse`.
- **Escopo por papel** — `EstoqueViewSet.get_queryset` já devolve todas as lojas
  para gerente/admin e só as próprias para responsável. Helper
  `_is_gerente_ou_admin` em `notifications/__init__.py` e `is_gerente_ou_admin`
  em `viewsets.py`.

## Decisões tomadas

| Decisão | Escolha |
|---|---|
| Formato do resumo diário | **PDF anexo** |
| Gerente vê tudo | **Push no sininho + página de painel** (os dois) |
| Digest — horário | **7h** (início do expediente) |
| Digest — destinatário | **E-mail da loja** (`Loja.email`), 1 e-mail separado por loja; **gerente** = 1 PDF combinado de todas as lojas |
| Digest — liga/desliga | **Sem toggle** por enquanto: toda loja ativa com e-mail e item baixo recebe |
| Caminho do e-mail do digest | **Envio direto** (`EmailMessage`): o destinatário é a loja/gerente, não passa pela preferência por usuário |

## Frentes de implementação

### 1 · Alerta imediato = só in-app (mata o e-mail por produto)

- `app/notifications/__init__.py` `notificar_estoque_baixo`: **remover** a chamada
  `enviar_alerta_estoque_baixo.delay(estoque.id, notificados)`. Mantém o
  `Notificacao.objects.create` (sininho).
- `app/notifications/tasks.py`: **deletar** a task morta
  `enviar_alerta_estoque_baixo` (fica sem chamador).
- Testes: remover/ajustar qualquer teste que asserte e-mail imediato por produto
  (`tests.py` / `tests_seguranca.py`).

### 2 · Gerente no sininho de todas as lojas

- `app/notifications/__init__.py` `notificar_estoque_baixo`: além do
  `estoque.loja.responsavel`, incluir **todos os gerentes/admins** nos
  destinatários — `User.objects.filter(groups__name__in=["Gerente", "Admin"], is_active=True)`
  — independentemente de quem editou. O dedup por `(usuario, estoque)` e a
  limpeza no `EstoqueUpdateSerializer` (filtra por `tipo="estoque_baixo",
  estoque=...`, sem `usuario`) já cobrem o gerente.
- **Zero mudança no front** — cai na página `/notificacoes` que já existe.

### 3 · Painel "estoque baixo (todas as lojas)"

- **Back** — `@action(detail=False, methods=["get"], url_path="baixos")` em
  `EstoqueViewSet`, aplicando o `get_queryset` já escopado (gerente = todas,
  responsável = suas) e filtrando
  `quantidade_minima__gt=0, quantidade_atual__lte=F("quantidade_minima")`,
  ordenado por `loja__nome_loja, produto__nome_produto`. Serializer leve com
  `loja_nome` e `produto_nome` (além de quantidades) para a tela não precisar de
  N requisições.
- **Front** (`Unistock_Front`) — nova página listando os produtos abaixo do
  mínimo agrupados por loja, com `getEstoquesBaixos()` no service (`services/uni.ts`)
  batendo em `/estoque/baixos/`, e link no `Sidebar`.

### 4 · Resumo diário em PDF por loja (7h)

Destinatário deixa de ser o usuário e passa a ser a **loja** (`Loja.email`). O
digest vira um **agendamento diário fixo às 7h** que percorre as lojas e os
gerentes — mais simples que o polling de 15 min + preferência por usuário de hoje.

- **Novo módulo** `app/relatorios/estoque_baixo_pdf.py`:
  `gerar_estoque_baixo_pdf(estoques, *, titulo, subtitulo) -> bytes` — reaproveita
  o padrão/CSS de `pedidos_pdf.py`, agrupa por loja, retorna **bytes**
  (`HTML(string=...).write_pdf()`), não `HttpResponse`. Serve tanto para o PDF de
  uma loja quanto para o combinado (é a mesma função, muda a lista de estoques).
- **Nova task** `enviar_digest_lojas()` (substitui `disparar_digests`/
  `enviar_digest` por usuário):
  - Query base de baixos: `Estoque.objects.filter(loja__ativo=True,
    quantidade_minima__gt=0, quantidade_atual__lte=F("quantidade_minima"))`
    `.select_related("produto", "loja")`, ordenado por loja/produto.
  - **Por loja:** agrupa os baixos por loja; para cada loja que tem `email`
    preenchido e ao menos um item baixo, gera o PDF só daquela loja e envia um
    `EmailMessage` para `loja.email`. Loja sem e-mail é pulada (segue no combinado
    do gerente).
  - **Gerente:** se houver qualquer item baixo, gera **um PDF combinado** (todas
    as lojas) e envia para cada gerente/admin ativo com e-mail
    (`User.objects.filter(groups__name__in=["Gerente","Admin"], is_active=True)`).
  - Se não há nada baixo em lugar nenhum → não envia nada.
- **Envio direto** (`django.core.mail.EmailMessage` + `.attach(nome, bytes,
  "application/pdf")` + `.send()`), respeitando `EMAIL_TIMEOUT`. Não passa por
  `despachar()`/`EmailChannel`: o destinatário é a loja/gerente, não há
  preferência por usuário a respeitar aqui. (A extensão de anexo no `EmailChannel`
  fica **fora de escopo** — não é mais necessária.)
- **Agendamento 7h** — trocar a `PeriodicTask` da migração `0014` de
  `IntervalSchedule(15 min)` → `CrontabSchedule(hour=7, minute=0)` apontando para
  `enviar_digest_lojas`. Nova migração que atualiza o agendamento.
- **Sem toggle / sem catch-up** — dispara uma vez às 7h; se o beat estiver fora
  do ar exatamente nesse minuto, o dia é pulado (aceitável; ver Riscos).

### 5 · Limpeza do digest por usuário (agora morto)

Como o digest passou a ser por loja, o controle "resumo diário" por usuário
morre. Para não deixar botão que mente:

- **Front** — remover os controles de digest (`digest_ativo`, `digest_horario`,
  `digest_dias_semana`) da página `/configuracoes/notificacoes` e do hook
  `usePreferenciasNotificacao`. As preferências de **canal** (`email_ativo`,
  `whatsapp_ativo`) permanecem.
- **Back** — remover os campos de digest do `PreferenciaNotificacaoSerializer` e
  a task antiga `disparar_digests`/`enviar_digest`. Os campos do model
  (`digest_*`, `ultimo_digest_em`) podem ser **removidos numa migração de
  follow-up** (baixa prioridade) ou ficar inertes; o essencial é nenhuma UI expor
  controle sem efeito.

## Testes

- `tests_digest.py` (reescrever para o modelo por loja):
  - Duas lojas com item baixo, ambas com `email` → **dois e-mails**, cada um com
    anexo PDF (`application/pdf`), endereçado ao `Loja.email` respectivo.
  - Loja com item baixo mas **sem e-mail** → não gera e-mail de loja (mas entra
    no combinado do gerente).
  - Gerente/admin ativo com e-mail recebe **um** e-mail com o PDF combinado de
    todas as lojas.
  - Nada abaixo do mínimo em lugar nenhum → `mail.outbox` vazio.
- `app/notifications/`:
  - `notificar_estoque_baixo` cria `Notificacao` para o gerente **mesmo quando
    quem edita é o responsável**, e **`mail.outbox` fica vazio** (sem e-mail
    imediato por produto).
- Endpoint `/estoque/baixos/`: gerente vê todas as lojas, responsável só as
  suas; produtos acima do mínimo não aparecem.
- Self-check no `estoque_baixo_pdf` (assert com dados sintéticos: bytes não
  vazios, começa com `%PDF`).

## Fora de escopo

- Canal de WhatsApp (fase 2 — stub já existe).
- Reescrita do relatório de pedidos.
- Preferência de formato por usuário (PDF é fixo no digest).
- Toggle de liga/desliga do digest (adiado; hoje é sempre-ligado por loja).
- Extensão de anexo no `EmailChannel` (o digest envia direto, não precisa).

## Riscos / observações

- **Container:** não precisa de container novo. O worker roda a **mesma imagem**
  da API, que já tem `weasyprint==66.0` + `libpango`/`libpangoft2` no Dockerfile
  (o relatório de pedidos já gera PDF nela). O digest roda no worker sem ambiente
  extra.
- **Memória do WeasyPrint:** cada PDF consome bastante RAM e às 7h vários saem
  juntos. Gerar em **sequência** (loop na task, PDF descartado entre lojas) e, se
  preciso, limitar `--concurrency` do worker. Não é caso de container à parte.
- **Sem catch-up:** o crontab dispara uma vez às 7h; se o beat estiver fora do ar
  nesse minuto, o digest do dia é pulado (sem reenvio). Aceitável agora; se virar
  problema, voltar ao polling + idempotência por loja.
- **`Loja.email` operacional:** loja sem e-mail cadastrado não recebe o resumo
  (só entra no combinado do gerente). Preencher o e-mail de cada loja é
  pré-requisito para o digest por loja funcionar.
- **Testes de PDF** dependem do WeasyPrint no ambiente de teste — se o CI não
  tiver as deps nativas, pular o self-check fora do container.
- **DAG do git instável** pelos hooks do ruflo — commitar em passos pequenos e
  verificar o branch antes de push.
