# UniStock API

Backend do sistema **UniStock**: gestao de lojas, produtos, estoque e pedidos
para uma rede com varias unidades.

Django + Django REST Framework, MySQL, Celery para tarefas assincronas.
A autenticacao usa JWT guardado em cookies HTTP-only — o token nunca vai no
corpo da resposta, para nao ficar acessivel ao JavaScript.

## Sumario

- [Tecnologias](#tecnologias)
- [Como rodar](#como-rodar)
- [Configuracao (.env)](#configuracao-env)
- [Perfis de acesso](#perfis-de-acesso)
- [Endpoints](#endpoints)
- [Notificacoes assincronas](#notificacoes-assincronas-celery--redis)
- [Testes](#testes)
- [Estrutura do projeto](#estrutura-do-projeto)

## Tecnologias

| O que | Usado para |
|---|---|
| Python 3.12 / Django | base do projeto |
| Django REST Framework | API |
| Simple JWT | autenticacao via cookie HTTP-only |
| MySQL 8 | banco |
| Celery + Redis | email assincrono e tarefas agendadas |
| drf-spectacular | schema OpenAPI e Swagger |
| Docker Compose | sobe tudo junto |

## Como rodar

Precisa de Docker. Copie o exemplo de configuracao e preencha:

```powershell
copy .env.example .env
```

Suba os containers:

```powershell
docker compose up --build        # em primeiro plano
docker compose up -d --build     # em segundo plano
docker compose down              # parar
```

O compose sobe oito servicos: `db` (MySQL), `redis`, `api`, `worker` (Celery),
`beat` (agendador) e o trio do bot de WhatsApp — `evolution-db` (Postgres),
`evolution-api` e `evolution-manager` (Evolution API, nao-oficial, baseada em
Baileys).

Ao subir, o `entrypoint` aplica as migrations, carrega os grupos e cria ou
atualiza o usuario admin a partir do `.env`.

| Onde | URL |
|---|---|
| API | http://localhost:8000 |
| Admin Django | http://localhost:8000/admin/ |
| Swagger | http://localhost:8000/api/schema/swagger/ |
| Redoc | http://localhost:8000/api/schema/redoc/ |
| Schema OpenAPI | http://localhost:8000/api/schema/ |
| Evolution Manager (UI, conectar o zap) | http://localhost:3001 |
| Evolution API | http://localhost:8080 |

## Configuracao (.env)

Todas as variaveis, com comentario explicando cada bloco, estao em
[`.env.example`](.env.example). Copie de la — este README nao repete os valores
de proposito, para nao virar uma segunda fonte da verdade que sai do ar.

Pontos que costumam pegar:

- **`SECRET_KEY`** — gere uma propria. Nao commite, nao reaproveite de outro
  ambiente.
- **`DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD`** — obrigatorias.
  O container nao cria o admin sem elas.
- **`DB_ENGINE`** — se ficar vazio, o `settings` cai no SQLite local. Com
  Docker, mantenha o MySQL.
- **`DB_HOST`** — dentro do Docker o compose sobrescreve para `db`. O valor do
  `.env` so vale se voce rodar o Django fora do container.
- **`BOT_SERVICE_TOKEN`** — vazio desativa as rotas do bot de WhatsApp.
- **`EVOLUTION_API_KEY` / `EVOLUTION_POSTGRES_PASSWORD`** — obrigatorias para
  os servicos `evolution-*` subirem. Sem elas o `docker compose up` falha ao
  criar esses containers.
- **`EVOLUTION_INSTANCE`** — nome da instancia criada no Evolution Manager
  (ex.: `Unistock`). Usado tanto pra mandar mensagem quanto pra registrar o
  webhook.
- **`EVOLUTION_WEBHOOK_TOKEN`** — segredo que vai na URL do webhook
  (`/api/v1/bot/webhook/<token>/`). Gere um valor aleatorio e configure a
  mesma URL completa (com o token) como webhook da instancia na Evolution API.
- **`EVOLUTION_API_URL`** — vazio desativa o envio de resposta pelo bot
  (o webhook processa o comando mas nao manda a resposta de volta). Dentro do
  Docker o compose sobrescreve para `http://evolution-api:8080`; o valor do
  `.env` so vale fora do container (ex.: testar via Postman).
- **Email** — com `DEBUG=True` os emails saem no console do worker. Nao precisa
  de SMTP para desenvolver.

## Empresa (Conta) e perfis de acesso

O limite de visibilidade do sistema e a **`Conta`** — a empresa. Loja,
Categoria e Produto pertencem a uma conta, e o usuario entra nela pelo
`PerfilUsuario` (um usuario, uma conta). Quem esta na mesma conta ve as mesmas
lojas e o mesmo catalogo: **dois gerentes numa empresa trabalham juntos**, que
e o caso que o modelo anterior nao sabia representar — ali o dono do dado era
a PESSOA (`Loja.gerente`), entao cada gerente era um silo e a loja perdia o
catalogo se o gerente dela saisse.

O papel continua sendo o grupo do Django, agora so como cargo:

| Grupo | Alcance |
|---|---|
| `Admin` | todas as contas, mais o Django Admin |
| `Gerente` | a propria empresa: lojas, produtos e categorias dela |
| `Responsavel` | a propria loja, com o catalogo da empresa dela |

Todo usuario precisa estar em um grupo. Sem grupo, o login e recusado.

O escopo sai de uma pergunta so, `get_conta_do_usuario` em `permissions.py`, e
e aplicado no `queryset` de cada ViewSet e tambem no `/admin`. Um usuario que
chame a API direto continua vendo so o que e da empresa dele. `None` ali tem
dois sentidos opostos, e quem chama precisa saber a diferenca: Admin nao tem
conta e ve TUDO; usuario sem perfil nao ve NADA.

A conta nunca vem do corpo do request — e sempre derivada de quem esta logado.
Mandar `conta` num POST de loja ou categoria simplesmente nao tem efeito. O
Admin, que nao pertence a nenhuma empresa, e o unico que precisa informar em
qual esta cadastrando.

Isso vale tambem no bot de WhatsApp: `/bot/catalogo/`, `/bot/pedido/` e o PDF
de `/bot/relatorio/` so enxergam a empresa da loja que perguntou.

Contas e vinculos sao criados pelo Admin no `/admin` — nao ha autoatendimento.
A tela da Conta traz os membros num inline, que e onde se poe o segundo
gerente numa empresa.

### Niveis de estoque por loja

Cada linha de `Estoque` e um par (produto, loja) e carrega os DOIS niveis:

| Campo | O que faz |
|---|---|
| `quantidade_minima` | abaixo/igual a ele, alerta de **falta** |
| `quantidade_maxima` | acima dele, alerta de **sobra** |

Os dois sao por LOJA, nao por produto: a Lapa gira muito mais que a Casa Verde
e precisa de niveis maiores; ao mesmo tempo nao pode acumular, porque estraga.
O que o produto guarda (`estoque_minimo_sugerido`, `estoque_maximo_sugerido`) e
so o valor de PARTIDA de uma linha nova, nunca um teto universal.

O maximo e obrigatorio e sempre maior que o minimo. A regra esta no serializer
(400 explicando o campo) e tambem em `CheckConstraint` no banco, porque o bot,
o PDV e o `/admin` escrevem estoque sem passar pela API.

**Pedido que estoura o teto avisa, nao bloqueia.** A primeira tentativa volta
`409` com a lista do que passaria (`produto`, `resultante`, `maximo`, `cabe`);
reenviar com `confirmar_excesso: true` registra assim mesmo. Trava dura
empurraria quem esta na loja a subir o teto para 200 so para conseguir pedir —
e nunca mais abaixar, matando junto o alerta que protege o produto.

Produto que a loja ainda nao estocou nao dispara o aviso: sem linha nao existe
teto DAQUELA loja, e avisar em cima do palpite do catalogo seria o
comportamento universal que este campo veio eliminar. A primeira entrega cria a
linha, e dali em diante o excesso alerta normalmente.

Os niveis se editam na tela da loja (`/lojas/editar/<id>`), com falta e sobra
lado a lado — e assim que da para comparar duas lojas de relance.

### Limites de taxa

Rotas abertas tem teto para nao virarem porta de abuso:

| Escopo | Limite |
|---|---|
| `login` | 10/min |
| `registro` | 20/hora |
| `senha` | 10/hora |
| anonimo (geral) | 60/min |
| autenticado (geral) | 300/min |

O limite de `senha` e contado **pelo email alvo**, nao por quem pede. Contar
por origem deixaria qualquer conta logada inundar a caixa de qualquer loja com
links de redefinicao.

## Endpoints

### Autenticacao

```text
POST /login/               entra e recebe os cookies
POST /logout/              limpa os cookies
POST /token/refresh/       renova o access token pelo cookie
```

### Usuarios

```text
GET   /api/v1/user/me/
POST  /api/v1/user/registrar/                cadastro publico (conta inativa)
GET   /api/v1/user/confirmar/<token>/        confirma a conta pelo link do email
POST  /api/v1/user/esqueci-senha/            pede o link de redefinicao
POST  /api/v1/user/definir-senha/<token>/    define a senha nova
```

### Dominio

```text
/api/v1/lojas/
/api/v1/produtos/
/api/v1/estoque/                 + GET /estoque/baixos/
/api/v1/movimentacoes/
/api/v1/pedidos/                 + PATCH /pedidos/<public_id>/status/
/api/v1/itens-pedido/
/api/v1/vendas/
/api/v1/notificacoes/            + PATCH /<public_id>/marcar-lida/
                                 + PATCH /todas-lidas/  + DELETE /limpar/
/api/v1/preferencias-notificacao/me/
```

```text
GET /gerar_pdf/?periodo=dia|semana|mes&data=AAAA-MM-DD
```

Relatorio de pedidos das lojas da empresa. Restrito a gerente/admin — um
responsavel nao deve enxergar os pedidos das outras unidades. O Admin, que nao
pertence a nenhuma empresa, recebe o relatorio global.

### Bot de WhatsApp

Autenticadas por `BOT_SERVICE_TOKEN`, nao por JWT.

```text
POST /api/v1/bot/contato/
GET  /api/v1/bot/catalogo/?telefone=...
POST /api/v1/bot/pedido/
POST /api/v1/bot/pedido/<numero>/confirmar/
POST /api/v1/bot/estoque/remover/
GET  /api/v1/bot/relatorio/
POST /api/v1/bot/webhook/<token>/    recebido da Evolution API, nao chamado direto
```

Os recursos usam `public_id` (UUID) na URL, nao o id sequencial.

O webhook (`app/api/v1/whatsapp_webhook.py`) e quem transforma o texto que a
loja digita no WhatsApp em chamada pras rotas acima — comandos tipo `catalogo`,
`pedido 12x2 7x1`, `confirmar 45`, `remover 12x1`. O `<token>` na URL e o
`EVOLUTION_WEBHOOK_TOKEN`: precisa ser configurado como URL do webhook na
instancia da Evolution API (Evolution Manager, ou `POST /webhook/instance` na
propria Evolution API) — sem isso, mensagem recebida no WhatsApp nao chega aqui.

## Notificacoes assincronas (Celery + Redis)

Emails saem como task, fora do ciclo da requisicao:

- **Confirmacao de conta** — o cadastro publico cria a conta inativa e manda o
  link (`FRONTEND_URL/confirmar-conta/<token>`, valido por 3 dias).
- **Alerta de estoque baixo** — email ao responsavel quando o estoque cruza o
  minimo, uma vez por episodio (nao repete enquanto continuar baixo).

Para ver as tasks rodando:

```powershell
docker compose logs -f worker
```

## Testes

```powershell
docker exec unistock python manage.py test app
```

Rodar um arquivo so:

```powershell
docker exec unistock python manage.py test app.tests.test_permissoes
```

Os testes ficam em `backend/app/tests/`, um arquivo por assunto. Ao adicionar
um arquivo novo, confira o **numero** de testes na saida (`Ran N tests`), nao
so o `OK`: sem `__init__.py` na pasta o runner nao acha nada e ainda assim
imprime `OK`.

## Estrutura do projeto

```text
backend/
  app/
    api/v1/
      views/          um arquivo por dominio (pedidos, estoque, lojas...)
      serializers.py
      router.py
      throttles.py
      bot.py          rotas do bot, autenticadas por token de servico
    tests/            um arquivo por assunto; loja_login/ tem os fluxos de conta
    tasks/            tasks Celery (email, digest)
    relatorios/       geracao de PDF
    models.py
    permissions.py
    views.py          login, logout, refresh, relatorio
  backend/
    settings.py
    urls.py
```

## Observacoes

- Sem `DB_ENGINE` definido o projeto cai no SQLite — util para rodar fora do
  Docker, mas nao e o ambiente de verdade.
- Este repositorio e **publico**. Nao coloque senha real, `SECRET_KEY` ou token
  de servico no README, no codigo ou no historico do Git.
