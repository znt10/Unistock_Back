# UniStock API

Backend do sistema **UniStock**, desenvolvido com Django e Django REST Framework.

A API e responsavel pelo gerenciamento de usuarios, lojas, produtos, estoque e pedidos. A autenticacao do sistema utiliza JWT salvo em cookies HTTP-only.

## Tecnologias

- Python 3.12
- Django
- Django REST Framework
- Simple JWT
- MySQL
- Docker Compose

## Como Rodar

Suba o container:

```powershell
docker compose up --build
```

Ou rode em segundo plano:

```powershell
docker compose up -d --build
```

A API ficara disponivel em:

```text
http://localhost:8000
```

Para parar o container:

```powershell
docker compose down
```

## Banco de Dados

O projeto usa MySQL. As variaveis ficam em `.env`:

```env
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0

CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001
CSRF_TRUSTED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001

SECRET_KEY=<gere-uma-chave-secreta-local-e-nao-commite>

DB_ENGINE=django.db.backends.mysql
DB_NAME=p5
DB_USER=root
DB_PASSWORD=12345
DB_HOST=localhost
DB_PORT=3306

DJANGO_SETTINGS_MODULE=backend.settings

DJANGO_SUPERUSER_EMAIL=<seu-email-de-admin-local>
DJANGO_SUPERUSER_PASSWORD=<defina-uma-senha-forte-local>
```

O usuario admin padrao e criado/atualizado automaticamente ao subir o Docker, usando `DJANGO_SUPERUSER_EMAIL`/`DJANGO_SUPERUSER_PASSWORD` do `.env` (obrigatorias — o container nao cria admin sem elas).

```text
grupo: Admin
is_staff: True
is_superuser: True
```

Admin Django:

```text
http://localhost:8000/admin/
```

## Endpoints Principais

```text
POST /login/
POST /logout/
POST /token/refresh/

GET /api/v1/user/me/
POST /api/v1/user/registrar/

GET /api/v1/lojas/
GET /api/v1/produtos/
GET /api/v1/estoque/
GET /api/v1/pedidos/
```

## Documentacao da API

```text
http://localhost:8000/api/schema/
http://localhost:8000/api/schema/swagger/
```

## Notificacoes assincronas (Celery + Redis)

O compose sobe, alem da API e do MySQL: `redis` (broker), `worker` (Celery) e
`beat` (agendador com django-celery-beat). Notificacoes por email rodam como
tasks assincronas:

- Confirmacao de conta: cadastro publico cria a conta inativa e envia email
  com link de confirmacao (`FRONTEND_URL/confirmar-conta/<token>`, valido por
  3 dias). Endpoint: `GET /api/v1/user/confirmar/<token>/`.
- Alerta de estoque baixo: enviado por email ao responsavel quando o estoque
  cruza o minimo (uma vez por episodio).

Variaveis no `.env` (veja `.env.example`): `CELERY_BROKER_URL`, `EMAIL_HOST`,
`EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`,
`DEFAULT_FROM_EMAIL`, `FRONTEND_URL`. Em `DEBUG=True` os emails saem no
console do worker (nao precisa de SMTP para desenvolver).

## Observacoes

- O projeto usa MySQL como banco de dados.
- As configuracoes do ambiente ficam no arquivo `.env`.
- Ao subir o Docker, o sistema aplica as migrations, carrega os grupos e cria/atualiza o usuario admin padrao automaticamente.
- Usuarios precisam estar em um grupo, como `Admin`, `Gerente` ou `Responsavel`, para acessar o sistema corretamente.
- Se este repositorio for publico, nao deixe senha real nem `SECRET_KEY` no README ou no historico do Git.
