# Redesenho de alertas de estoque baixo

**Data:** 2026-07-24
**Repositórios:** `Unistock_Back` (Django/DRF/Celery) + `Unistock_Front` (Next.js) — 1 página nova no front.

## Contexto e objetivo

Hoje, cada queda de um produto abaixo do estoque mínimo gera **duas** coisas ao
mesmo tempo: uma notificação in-app (sininho) **e** um e-mail imediato por
produto. O objetivo é:

1. **Alerta imediato = só in-app.** Matar o e-mail por produto.
2. **Gerente enxerga tudo centralizado** — não só o que ele mesmo editou.
3. **Resumo diário por e-mail em PDF**, às 6h, com a lista de produtos abaixo do
   mínimo. O gerente recebe **um único PDF com todas as lojas juntas**
   (agrupadas por loja no documento); cada responsável recebe o PDF só das lojas
   dele.

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
| Digest — horário/escopo | **6h**; responsável = suas lojas, gerente = **todas num só PDF** |
| Digest automático? | **Sim** — `digest_ativo` nasce `True`, backfill nas preferências existentes; dá pra desligar nas configurações |
| Caminho do anexo | Estender `EmailChannel` para anexos, via `despachar()` (respeita `email_ativo`) |

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

### 4 · Resumo diário em PDF (6h, gerente = 1 PDF de tudo)

- **Novo módulo** `app/relatorios/estoque_baixo_pdf.py`:
  `gerar_estoque_baixo_pdf(estoques, *, titulo, subtitulo) -> bytes` — reaproveita
  o padrão/CSS de `pedidos_pdf.py`, agrupa por loja, retorna **bytes**
  (`HTML(string=...).write_pdf()`), não `HttpResponse`.
- `app/notifications/tasks.py` `enviar_digest(user_id)`:
  - Escopo por papel: se `_is_gerente_ou_admin(usuario)` → todas as lojas ativas
    (`Estoque.objects.filter(loja__ativo=True, ...)`); senão → só
    `loja__responsavel=usuario`.
  - Query de baixos (mesma condição de mínimo), `select_related("produto","loja")`,
    ordenado por loja/produto.
  - Se vazio → não envia (comportamento atual preservado).
  - Gera o PDF e envia **como anexo** via `despachar(usuario, titulo, mensagem,
    contexto={"anexos": [(nome_arquivo, pdf_bytes, "application/pdf")]})`.
- **Anexo via canal** — `app/notifications/channels.py` `EmailChannel.send`:
  quando `contexto["anexos"]` existir, montar um `django.core.mail.EmailMessage`
  (from/to/subject/body), `.attach(nome, bytes, mime)` para cada anexo e
  `.send()`; sem anexos, mantém o `send_mail` atual. `WhatsAppChannel` ignora o
  anexo (fase 2). `despachar` já repassa o `contexto`.
- **Horário 6h** — migração de model: `PreferenciaNotificacao.digest_horario`
  default `datetime.time(6, 0)`. O beat de 15 min dispara sozinho depois das 6h.

### 5 · Digest automático (opt-out em vez de opt-in)

- `PreferenciaNotificacao.digest_ativo` default → `True`.
- **Data migration** (backfill): para as `PreferenciaNotificacao` existentes,
  setar `digest_ativo=True` e `digest_horario=time(6,0)` **apenas onde ainda
  estiver no default antigo** (`time(18,0)`), preservando horário que alguém já
  tenha escolhido de propósito.
- **Cobertura de novos/atuais usuários** — o loop do digest itera sobre linhas
  de `PreferenciaNotificacao` (criadas sob demanda). Para o "automático" valer:
  - Backfill cria a linha para todos os usuários ativos existentes
    (`get_or_create` no migration).
  - No cadastro de usuário (`UsuarioViewSet.registrar`/`create`), garantir
    `PreferenciaNotificacao.objects.get_or_create(usuario=user)` (1 linha), para
    todo novo usuário já ter preferência.

## Testes

- `tests_digest.py`:
  - Atualizar `test_digest_envia_um_email_com_itens_baixos` para checar que o
    e-mail tem **anexo PDF** (`mail.outbox[0].attachments` não vazio, mime
    `application/pdf`).
  - Novo: gerente recebe **1 PDF com todas as lojas**; responsável recebe só as
    suas.
- `app/notifications/`:
  - `notificar_estoque_baixo` cria `Notificacao` para o gerente **mesmo quando
    quem edita é o responsável**, e **`mail.outbox` fica vazio** (sem e-mail
    imediato).
- Endpoint `/estoque/baixos/`: gerente vê todas as lojas, responsável só as
  suas; produtos acima do mínimo não aparecem.
- Self-check no `estoque_baixo_pdf` (assert com dados sintéticos: bytes não
  vazios, começa com `%PDF`).

## Fora de escopo

- Canal de WhatsApp (fase 2 — stub já existe).
- Reescrita do relatório de pedidos.
- Preferência de formato por usuário (PDF é fixo no digest).

## Riscos / observações

- **WeasyPrint só roda no container** (deps nativas). O digest roda no worker
  (que já tem o ambiente); testes de PDF dependem do WeasyPrint instalado no
  ambiente de teste — se o CI não tiver, marcar o self-check para pular fora do
  container.
- **Volume no sininho do gerente** — em operação com muitas lojas, o gerente
  pode acumular notificações; mitigado pelo dedup por episódio e pelos botões
  `todas-lidas`/`limpar` já existentes.
- **DAG do git instável** pelos hooks do ruflo — commitar em passos pequenos e
  verificar o branch antes de push.
