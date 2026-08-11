# A Loja Vira o Login — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o acesso de uma loja ser a própria loja (login = e-mail da loja) em vez de uma pessoa, com senha definida no 1º acesso por link enviado ao e-mail da loja.

**Architecture:** `Loja.responsavel` continua sendo a chave de escopo do sistema — o que muda é que ela aponta para um `User` cujo `username`/`email` é o `Loja.email`, criado automaticamente ao criar a loja. Reaproveita o mecanismo de token assinado (`django.core.signing`) já usado na confirmação de conta, generalizado para "definir senha". Auditoria (`Pedido.responsavel`, `MovimentacaoEstoque.usuario`) e todo o escopo por `loja__responsavel` ficam intactos.

**Tech Stack:** Django 6 / DRF / Simple JWT (cookies HTTP-only), Celery + Redis, MySQL, Next.js 15 + TypeScript + TanStack Query.

**Spec:** `docs/superpowers/specs/2026-07-25-loja-como-login-design.md`

**Branches:** `feature/loja-como-login` nos dois repositórios (já criadas, a partir de `dev-local`). PRs vão para `dev-local` — **nunca** para `dev-producao` ou `main`.

---

## Contexto de ambiente (leia antes de começar)

Os testes rodam **dentro do container Docker**, não na máquina host (não há Python/Django local):

```bash
# Da raiz de Unistock_Back
docker compose up -d api          # se não estiver rodando
docker exec unistock python manage.py test app
```

**IMPORTANTE — armadilha conhecida:** a API roda gunicorn **sem `--reload`**. Os
*models* são importados uma vez no start do container; as *views* são importadas
na primeira requisição. Se você mudar `models.py` ou rodar migração, **reinicie**:

```bash
docker compose restart api worker beat
```

Sem isso você vê erros fantasma do tipo "coluna não existe" ou "atributo não existe"
com o código correto no disco.

## Estrutura de arquivos

### Backend (`Unistock_Back`)

| Arquivo | Responsabilidade | Ação |
|---|---|---|
| `backend/app/notifications/tokens.py` | Gerar/validar tokens assinados de senha (uso único). Isolado por ser lógica de segurança que merece teste próprio | **Criar** |
| `backend/app/notifications/tasks.py` | Nova task `enviar_email_definir_senha` | Modificar |
| `backend/app/api/v1/serializers/lojas.py` | Criar o User da loja no `create`; sincronizar e-mail no `update`; validar e-mail único | Modificar |
| `backend/app/api/v1/viewsets.py` | Actions `definir-senha` e `esqueci-senha` no `UsuarioViewSet` | Modificar |
| `backend/backend/settings.py` | Taxa de throttle `senha` | Modificar |
| `backend/app/migrations/0017_converter_responsaveis_para_email_loja.py` | Data migration de conversão | **Criar** |
| `backend/app/tests_loja_login.py` | Todos os testes desta feature | **Criar** |

Arquivo de testes separado (`tests_loja_login.py`) seguindo o padrão do projeto,
que já tem `tests_digest.py`, `tests_bot.py`, `tests_seguranca.py`.

### Frontend (`Unistock_Front`)

| Arquivo | Responsabilidade | Ação |
|---|---|---|
| `frontend/services/auth.ts` | `definirSenha()` e `esqueciSenha()` | Modificar |
| `frontend/app/esqueci-senha/page.tsx` | Ligar à API real (hoje é casca falsa) | Modificar |
| `frontend/app/redefinir-senha/page.tsx` | Ler token da URL e enviar senha nova | Modificar |
| `frontend/components/usuarios/CadastroUsuarioForm.tsx` | Remover a opção "Responsável" | Modificar |
| `frontend/app/lojas/editar/[id]/page.tsx` | Campo responsável vira somente leitura | Modificar |

---

## Task 1: Token de definir senha (uso único)

**Files:**
- Create: `backend/app/notifications/tokens.py`
- Test: `backend/app/tests_loja_login.py`

O token é assinado (`django.core.signing`), vale 3 dias e é de **uso único**: o
payload carrega um trecho do hash da senha atual, que muda quando a senha é
definida, invalidando o link.

- [ ] **Step 1: Escreva o teste que falha**

Crie `backend/app/tests_loja_login.py`:

```python
"""A loja como login: token de senha, criacao de acesso e migracao."""

from django.contrib.auth.models import User
from django.core import signing
from django.test import TestCase


class TokenSenhaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='loja@teste.com', email='loja@teste.com', password='senha-antiga-123',
        )

    def test_token_valido_devolve_o_usuario(self):
        from app.notifications.tokens import gerar_token_senha, validar_token_senha

        token = gerar_token_senha(self.user)

        self.assertEqual(validar_token_senha(token), self.user.id)

    def test_token_deixa_de_valer_depois_que_a_senha_muda(self):
        """Uso unico: link usado (ou vazado) nao serve duas vezes."""
        from app.notifications.tokens import gerar_token_senha, validar_token_senha

        token = gerar_token_senha(self.user)
        self.user.set_password('senha-nova-456')
        self.user.save()

        with self.assertRaises(signing.BadSignature):
            validar_token_senha(token)

    def test_token_adulterado_e_recusado(self):
        from app.notifications.tokens import gerar_token_senha, validar_token_senha

        token = gerar_token_senha(self.user) + 'xx'

        with self.assertRaises(signing.BadSignature):
            validar_token_senha(token)
```

- [ ] **Step 2: Rode o teste e confirme que falha**

```bash
docker exec unistock python manage.py test app.tests_loja_login.TokenSenhaTests
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'app.notifications.tokens'`

- [ ] **Step 3: Implemente o mínimo**

Crie `backend/app/notifications/tokens.py`:

```python
"""Tokens assinados para definir senha (1o acesso e 'esqueci a senha').

Uso unico: o payload carrega um trecho do hash da senha atual. Ao definir a
senha o hash muda, entao o link para de funcionar — um link vazado nao continua
valido pelos 3 dias.
"""

from django.core import signing

SALT_SENHA = "unistock-definir-senha"
VALIDADE_TOKEN_SEGUNDOS = 60 * 60 * 24 * 3  # 3 dias


def _marca_da_senha(usuario):
    """Trecho do hash atual da senha. Muda quando a senha muda."""
    return (usuario.password or "")[-12:]


def gerar_token_senha(usuario):
    return signing.dumps(
        {"user_id": usuario.id, "marca": _marca_da_senha(usuario)},
        salt=SALT_SENHA,
    )


def validar_token_senha(token):
    """Devolve o user_id do token.

    Levanta signing.SignatureExpired se passou da validade, ou
    signing.BadSignature se foi adulterado ou ja foi usado.
    """
    from django.contrib.auth.models import User

    dados = signing.loads(token, salt=SALT_SENHA, max_age=VALIDADE_TOKEN_SEGUNDOS)

    usuario = User.objects.filter(id=dados["user_id"]).first()
    if not usuario or _marca_da_senha(usuario) != dados.get("marca"):
        raise signing.BadSignature("Token ja utilizado ou usuario inexistente.")

    return usuario.id
```

- [ ] **Step 4: Rode o teste e confirme que passa**

```bash
docker exec unistock python manage.py test app.tests_loja_login.TokenSenhaTests
```

Esperado: `Ran 3 tests` / `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/notifications/tokens.py backend/app/tests_loja_login.py
git commit -m "feat(auth): token de uso unico para definir senha"
```

---

## Task 2: Task de e-mail "defina sua senha"

**Files:**
- Modify: `backend/app/notifications/tasks.py`
- Test: `backend/app/tests_loja_login.py`

- [ ] **Step 1: Escreva o teste que falha**

Adicione ao fim de `backend/app/tests_loja_login.py`:

```python
class EmailDefinirSenhaTests(TestCase):
    def test_envia_link_de_definir_senha(self):
        from django.core import mail

        from app.notifications.tasks import enviar_email_definir_senha

        user = User.objects.create_user(
            username='lapa@unistock.com', email='lapa@unistock.com',
        )

        enviado = enviar_email_definir_senha(user.id)

        self.assertTrue(enviado)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['lapa@unistock.com'])
        self.assertIn('/redefinir-senha/', mail.outbox[0].body)

    def test_usuario_inexistente_nao_envia(self):
        from django.core import mail

        from app.notifications.tasks import enviar_email_definir_senha

        self.assertFalse(enviar_email_definir_senha(99999))
        self.assertEqual(len(mail.outbox), 0)

    def test_usuario_sem_email_nao_envia(self):
        from django.core import mail

        from app.notifications.tasks import enviar_email_definir_senha

        user = User.objects.create_user(username='sem-email')

        self.assertFalse(enviar_email_definir_senha(user.id))
        self.assertEqual(len(mail.outbox), 0)
```

- [ ] **Step 2: Rode o teste e confirme que falha**

```bash
docker exec unistock python manage.py test app.tests_loja_login.EmailDefinirSenhaTests
```

Esperado: FAIL com `ImportError: cannot import name 'enviar_email_definir_senha'`

- [ ] **Step 3: Implemente o mínimo**

Em `backend/app/notifications/tasks.py`, adicione logo após a função
`enviar_email_confirmacao` (mantenha os imports existentes no topo do arquivo):

```python
@shared_task
def enviar_email_definir_senha(user_id):
    """Manda o link de definir senha (1o acesso da loja ou 'esqueci a senha')."""
    from django.core.mail import send_mail

    from .tokens import gerar_token_senha

    usuario = User.objects.filter(id=user_id).first()
    if not usuario or not usuario.email:
        return False

    link = f"{settings.FRONTEND_URL}/redefinir-senha/{gerar_token_senha(usuario)}"
    mensagem = (
        "Ola!\n\n"
        "Para acessar o Unistock, defina a senha desta conta pelo link:\n"
        f"{link}\n\n"
        "O link vale por 3 dias e pode ser usado uma unica vez.\n"
        "Se voce nao pediu isso, ignore este email."
    )
    send_mail(
        "Defina a senha da sua conta no Unistock",
        mensagem,
        settings.DEFAULT_FROM_EMAIL,
        [usuario.email],
        fail_silently=False,
    )
    return True
```

Envio direto (`send_mail`), não via `despachar()`: quem recebe é a loja, e uma
preferência de notificação não pode impedir alguém de recuperar o próprio acesso.

- [ ] **Step 4: Rode o teste e confirme que passa**

```bash
docker exec unistock python manage.py test app.tests_loja_login.EmailDefinirSenhaTests
```

Esperado: `Ran 3 tests` / `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/notifications/tasks.py backend/app/tests_loja_login.py
git commit -m "feat(auth): task de email para definir senha"
```

---

## Task 3: Criar a loja cria o acesso

**Files:**
- Modify: `backend/app/api/v1/serializers/lojas.py`
- Test: `backend/app/tests_loja_login.py`

Ao criar uma loja com e-mail, nasce junto um `User` inativo, sem senha
utilizável, no grupo `Responsavel`, vinculado em `Loja.responsavel`, e o e-mail
de definir senha é disparado.

- [ ] **Step 1: Escreva o teste que falha**

Adicione ao fim de `backend/app/tests_loja_login.py`:

```python
from django.contrib.auth.models import Group
from rest_framework.test import APITestCase

from app.models import Loja


class CriarLojaCriaAcessoTests(APITestCase):
    def setUp(self):
        Group.objects.get_or_create(name='Responsavel')
        grupo_gerente, _ = Group.objects.get_or_create(name='Gerente')
        self.gerente = User.objects.create_user(username='ger', password='123')
        self.gerente.groups.add(grupo_gerente)
        self.client.force_authenticate(self.gerente)

    def _payload(self, **extra):
        dados = {
            'nome_loja': 'Lapa', 'cidade': 'Patos', 'endereco': 'Rua 1',
            'email': 'lapa@unistock.com',
        }
        dados.update(extra)
        return dados

    def test_loja_com_email_ganha_login_proprio(self):
        from django.core import mail

        response = self.client.post('/api/v1/lojas/', self._payload(), format='json')

        self.assertEqual(response.status_code, 201, response.data)
        loja = Loja.objects.get(nome_loja='Lapa')
        self.assertIsNotNone(loja.responsavel)
        acesso = loja.responsavel
        self.assertEqual(acesso.username, 'lapa@unistock.com')
        self.assertEqual(acesso.email, 'lapa@unistock.com')
        self.assertFalse(acesso.is_active)
        self.assertFalse(acesso.has_usable_password())
        self.assertTrue(acesso.groups.filter(name='Responsavel').exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['lapa@unistock.com'])

    def test_loja_sem_email_nao_cria_login(self):
        from django.core import mail

        response = self.client.post(
            '/api/v1/lojas/', self._payload(email=''), format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        loja = Loja.objects.get(nome_loja='Lapa')
        self.assertIsNone(loja.responsavel)
        self.assertEqual(len(mail.outbox), 0)

    def test_duas_lojas_com_o_mesmo_email_e_recusado(self):
        self.client.post('/api/v1/lojas/', self._payload(), format='json')

        response = self.client.post(
            '/api/v1/lojas/', self._payload(nome_loja='Outra'), format='json',
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('email', response.data)
```

- [ ] **Step 2: Rode o teste e confirme que falha**

```bash
docker exec unistock python manage.py test app.tests_loja_login.CriarLojaCriaAcessoTests
```

Esperado: FAIL — `AssertionError: None is not... ` (a loja nasce sem `responsavel`)

- [ ] **Step 3: Implemente o mínimo**

Substitua o conteúdo de `backend/app/api/v1/serializers/lojas.py` por:

```python
import re

from django.contrib.auth.models import Group, User
from rest_framework import serializers

from app.models import Loja


def criar_acesso_da_loja(loja):
    """Cria o login da loja (username = email da loja) e manda definir senha.

    O acesso nasce inativo e sem senha utilizavel: so passa a valer quando a
    loja define a senha pelo link. Sem email cadastrado, a loja fica sem acesso.
    """
    from app.notifications.tasks import enviar_email_definir_senha

    if not loja.email:
        return None

    acesso = User.objects.create(username=loja.email, email=loja.email)
    acesso.set_unusable_password()
    acesso.is_active = False
    acesso.save()

    grupo, _ = Group.objects.get_or_create(name="Responsavel")
    acesso.groups.add(grupo)

    loja.responsavel = acesso
    loja.save(update_fields=["responsavel", "updated_at"])

    enviar_email_definir_senha.delay(acesso.id)
    return acesso


class LojaSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    responsavel_nome = serializers.CharField(
        source="responsavel.first_name",
        read_only=True,
    )
    # O acesso da loja e criado pelo sistema a partir do email — nao se escolhe
    # uma pessoa. Exposto so para leitura (mostra o email de acesso na tela).
    responsavel = serializers.PrimaryKeyRelatedField(read_only=True)
    email_acesso = serializers.EmailField(
        source="responsavel.email", read_only=True
    )

    class Meta:
        model = Loja
        fields = [
            "id",
            "nome_loja",
            "tipo",
            "cidade",
            "endereco",
            "responsavel",
            "responsavel_nome",
            "email_acesso",
            "ativo",
            "telefone_whatsapp",
            "email",
        ]

    def validate_telefone_whatsapp(self, value):
        if not value:
            return None
        # Normaliza para apenas digitos (aceita +55 (83) 99999-8888).
        digitos = re.sub(r"\D", "", value)
        if len(digitos) < 10:
            raise serializers.ValidationError(
                "Informe o numero com DDD (minimo 10 digitos)."
            )
        return digitos

    def validate_email(self, value):
        """Email da loja e o login dela: precisa ser unico entre lojas."""
        if not value:
            return value

        outras = Loja.objects.filter(email=value)
        if self.instance:
            outras = outras.exclude(pk=self.instance.pk)
        if outras.exists():
            raise serializers.ValidationError(
                "Ja existe uma loja com este email."
            )
        return value

    def create(self, validated_data):
        loja = super().create(validated_data)
        criar_acesso_da_loja(loja)
        return loja
```

- [ ] **Step 4: Rode o teste e confirme que passa**

```bash
docker exec unistock python manage.py test app.tests_loja_login.CriarLojaCriaAcessoTests
```

Esperado: `Ran 3 tests` / `OK`

- [ ] **Step 5: Rode a suíte inteira (a mudança mexe em serializer usado por outros testes)**

```bash
docker exec unistock python manage.py test app
```

Esperado: `OK`. Se algum teste antigo mandava `responsavel` no POST de loja
(ex.: `test_fluxo_completo_gerente` em `tests.py`), ele agora ignora esse campo —
o teste continua válido porque só checa `status_code == 201`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/serializers/lojas.py backend/app/tests_loja_login.py
git commit -m "feat(loja): criar loja cria o acesso com o email da loja"
```

---

## Task 4: Trocar o e-mail da loja troca o login junto

**Files:**
- Modify: `backend/app/api/v1/serializers/lojas.py`
- Test: `backend/app/tests_loja_login.py`

Sem isto, a loja perde o acesso na primeira edição de cadastro.

- [ ] **Step 1: Escreva o teste que falha**

Adicione ao fim de `backend/app/tests_loja_login.py`:

```python
class TrocarEmailDaLojaTests(APITestCase):
    def setUp(self):
        Group.objects.get_or_create(name='Responsavel')
        grupo_gerente, _ = Group.objects.get_or_create(name='Gerente')
        self.gerente = User.objects.create_user(username='ger2', password='123')
        self.gerente.groups.add(grupo_gerente)
        self.client.force_authenticate(self.gerente)
        self.client.post('/api/v1/lojas/', {
            'nome_loja': 'Lapa', 'cidade': 'Patos', 'endereco': 'Rua 1',
            'email': 'antigo@unistock.com',
        }, format='json')
        self.loja = Loja.objects.get(nome_loja='Lapa')

    def test_login_acompanha_o_novo_email(self):
        response = self.client.patch(
            f'/api/v1/lojas/{self.loja.public_id}/',
            {'email': 'novo@unistock.com'},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.loja.refresh_from_db()
        acesso = self.loja.responsavel
        acesso.refresh_from_db()
        self.assertEqual(acesso.username, 'novo@unistock.com')
        self.assertEqual(acesso.email, 'novo@unistock.com')

    def test_loja_que_ganha_email_depois_ganha_acesso(self):
        loja_sem = Loja.objects.create(
            nome_loja='Sem Email', cidade='Patos', endereco='Rua 2',
        )

        response = self.client.patch(
            f'/api/v1/lojas/{loja_sem.public_id}/',
            {'email': 'depois@unistock.com'},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        loja_sem.refresh_from_db()
        self.assertIsNotNone(loja_sem.responsavel)
        self.assertEqual(loja_sem.responsavel.username, 'depois@unistock.com')
```

- [ ] **Step 2: Rode o teste e confirme que falha**

```bash
docker exec unistock python manage.py test app.tests_loja_login.TrocarEmailDaLojaTests
```

Esperado: FAIL — `AssertionError: 'antigo@unistock.com' != 'novo@unistock.com'`

- [ ] **Step 3: Implemente o mínimo**

Em `backend/app/api/v1/serializers/lojas.py`, adicione o método `update` na classe
`LojaSerializer`, logo depois do `create`:

```python
    def update(self, instance, validated_data):
        email_anterior = instance.email
        loja = super().update(instance, validated_data)

        if loja.email == email_anterior:
            return loja

        if loja.responsavel_id:
            # O login E o email da loja: se um muda, o outro acompanha, senao a
            # loja perde o acesso na primeira edicao de cadastro.
            acesso = loja.responsavel
            acesso.username = loja.email
            acesso.email = loja.email
            acesso.save(update_fields=["username", "email"])
        else:
            # Loja que nao tinha email agora tem: ganha acesso.
            criar_acesso_da_loja(loja)

        return loja
```

- [ ] **Step 4: Rode o teste e confirme que passa**

```bash
docker exec unistock python manage.py test app.tests_loja_login.TrocarEmailDaLojaTests
```

Esperado: `Ran 2 tests` / `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/serializers/lojas.py backend/app/tests_loja_login.py
git commit -m "feat(loja): trocar o email da loja atualiza o login"
```

---

## Task 5: Endpoint de definir senha

**Files:**
- Modify: `backend/app/api/v1/viewsets.py`
- Test: `backend/app/tests_loja_login.py`

- [ ] **Step 1: Escreva o teste que falha**

Adicione ao fim de `backend/app/tests_loja_login.py`:

```python
class DefinirSenhaTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='lapa@unistock.com', email='lapa@unistock.com',
        )
        self.user.set_unusable_password()
        self.user.is_active = False
        self.user.save()

    def _token(self):
        from app.notifications.tokens import gerar_token_senha

        return gerar_token_senha(self.user)

    def test_define_a_senha_e_ativa_a_conta(self):
        response = self.client.post(
            f'/api/v1/user/definir-senha/{self._token()}/',
            {'password': 'SenhaForte#2026'},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertTrue(self.user.check_password('SenhaForte#2026'))

    def test_token_invalido_400(self):
        response = self.client.post(
            '/api/v1/user/definir-senha/token-falso/',
            {'password': 'SenhaForte#2026'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_senha_fraca_400(self):
        response = self.client.post(
            f'/api/v1/user/definir-senha/{self._token()}/',
            {'password': '123'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())

    def test_mesmo_token_nao_serve_duas_vezes(self):
        token = self._token()
        self.client.post(
            f'/api/v1/user/definir-senha/{token}/',
            {'password': 'SenhaForte#2026'}, format='json',
        )

        response = self.client.post(
            f'/api/v1/user/definir-senha/{token}/',
            {'password': 'OutraSenha#2026'}, format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('SenhaForte#2026'))
```

- [ ] **Step 2: Rode o teste e confirme que falha**

```bash
docker exec unistock python manage.py test app.tests_loja_login.DefinirSenhaTests
```

Esperado: FAIL — `404 != 200` (a rota não existe)

- [ ] **Step 3: Implemente o mínimo**

Em `backend/app/api/v1/viewsets.py`, dentro da classe `UsuarioViewSet`, adicione
depois da action `confirmar`:

```python
    @action(
        detail=False,
        methods=['post'],
        url_path=r'definir-senha/(?P<token>[^/]+)',
        permission_classes=[AllowAny],
    )
    def definir_senha(self, request, token=None):
        """POST /api/v1/user/definir-senha/<token>/ — define a senha e ativa."""
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        from app.notifications.tokens import validar_token_senha

        try:
            user_id = validar_token_senha(token)
        except signing.SignatureExpired:
            return Response(
                {"error": "Link expirado. Peca um novo em 'Esqueci a senha'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except signing.BadSignature:
            return Response(
                {"error": "Link invalido ou ja utilizado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        senha = request.data.get('password') or ''
        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response(
                {"error": "Link invalido."}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            validate_password(senha, user)
        except ValidationError as erro:
            return Response(
                {"password": list(erro.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(senha)
        user.is_active = True
        user.save(update_fields=['password', 'is_active'])
        return Response({"detail": "Senha definida. Voce ja pode entrar."})
```

- [ ] **Step 4: Rode o teste e confirme que passa**

```bash
docker exec unistock python manage.py test app.tests_loja_login.DefinirSenhaTests
```

Esperado: `Ran 4 tests` / `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/viewsets.py backend/app/tests_loja_login.py
git commit -m "feat(auth): endpoint de definir senha por token"
```

---

## Task 6: Endpoint de esqueci a senha

**Files:**
- Modify: `backend/backend/settings.py`
- Modify: `backend/app/api/v1/viewsets.py`
- Test: `backend/app/tests_loja_login.py`

Responde 200 mesmo para e-mail inexistente — responder 404 revelaria quais
e-mails estão cadastrados.

- [ ] **Step 1: Escreva o teste que falha**

Adicione ao fim de `backend/app/tests_loja_login.py`:

```python
class EsqueciSenhaTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='lapa@unistock.com', email='lapa@unistock.com',
            password='qualquer-123',
        )

    def test_email_existente_recebe_link(self):
        from django.core import mail

        response = self.client.post(
            '/api/v1/user/esqueci-senha/',
            {'email': 'lapa@unistock.com'}, format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['lapa@unistock.com'])

    def test_email_inexistente_responde_igual_sem_enviar(self):
        """Nao vazar quais emails estao cadastrados."""
        from django.core import mail

        response = self.client.post(
            '/api/v1/user/esqueci-senha/',
            {'email': 'naoexiste@unistock.com'}, format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
```

- [ ] **Step 2: Rode o teste e confirme que falha**

```bash
docker exec unistock python manage.py test app.tests_loja_login.EsqueciSenhaTests
```

Esperado: FAIL — `404 != 200`

- [ ] **Step 3a: Adicione a taxa de throttle**

Em `backend/backend/settings.py`, no dicionário `DEFAULT_THROTTLE_RATES` (por
volta da linha 161), acrescente a linha `"senha"`:

```python
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "300/min",
        "login": "10/min",
        "registro": "20/hour",
        "senha": "10/hour",
    },
```

- [ ] **Step 3b: Implemente o endpoint**

Em `backend/app/api/v1/viewsets.py`, junto das outras classes de throttle (perto
da linha 69, onde está `RegistroRateThrottle`), adicione:

```python
class SenhaRateThrottle(AnonRateThrottle):
    """Limita o pedido de link de senha: evita varredura de emails."""

    scope = "senha"
```

E dentro de `UsuarioViewSet`, depois da action `definir_senha`:

```python
    @action(
        detail=False,
        methods=['post'],
        url_path='esqueci-senha',
        permission_classes=[AllowAny],
        throttle_classes=[SenhaRateThrottle],
    )
    def esqueci_senha(self, request):
        """POST /api/v1/user/esqueci-senha/ — manda o link de definir senha.

        Responde 200 exista ou nao o email: responder 404 revelaria quais
        emails estao cadastrados.
        """
        from app.notifications.tasks import enviar_email_definir_senha

        email = (request.data.get('email') or '').strip()
        if email:
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if user:
                enviar_email_definir_senha.delay(user.id)

        return Response(
            {"detail": "Se este email estiver cadastrado, enviamos o link."}
        )
```

- [ ] **Step 4: Rode o teste e confirme que passa**

```bash
docker exec unistock python manage.py test app.tests_loja_login.EsqueciSenhaTests
```

Esperado: `Ran 2 tests` / `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/backend/settings.py backend/app/api/v1/viewsets.py backend/app/tests_loja_login.py
git commit -m "feat(auth): endpoint de esqueci a senha"
```

---

## Task 7: Migração dos responsáveis existentes

**Files:**
- Create: `backend/app/migrations/0017_converter_responsaveis_para_email_loja.py`
- Test: `backend/app/tests_loja_login.py`

Converte o login dos responsáveis atuais para o e-mail da loja. É o **mesmo**
`User`, então `Pedido.responsavel` e `MovimentacaoEstoque.usuario` continuam
apontando certo — o histórico não se perde.

- [ ] **Step 1: Escreva o teste da função de conversão**

A lógica fica numa função importável para poder ser testada (migração em si é
difícil de testar). Adicione ao fim de `backend/app/tests_loja_login.py`:

```python
class ConverterResponsaveisTests(TestCase):
    def test_converte_login_para_o_email_da_loja(self):
        from app.migracoes_loja_login import converter_responsaveis

        pessoa = User.objects.create_user(
            username='joao@gmail.com', email='joao@gmail.com', password='123',
        )
        loja = Loja.objects.create(
            nome_loja='Lapa', cidade='Patos', endereco='Rua 1',
            email='lapa@unistock.com', responsavel=pessoa,
        )

        convertidos, pulados = converter_responsaveis(User, Loja)

        pessoa.refresh_from_db()
        self.assertEqual(pessoa.username, 'lapa@unistock.com')
        self.assertEqual(pessoa.email, 'lapa@unistock.com')
        self.assertEqual(convertidos, 1)
        self.assertEqual(pulados, [])
        self.assertEqual(loja.responsavel_id, pessoa.id)  # mesmo usuario

    def test_pula_loja_sem_email(self):
        from app.migracoes_loja_login import converter_responsaveis

        pessoa = User.objects.create_user(username='maria@gmail.com', password='123')
        Loja.objects.create(
            nome_loja='Sem Email', cidade='Patos', endereco='Rua 2',
            responsavel=pessoa,
        )

        convertidos, pulados = converter_responsaveis(User, Loja)

        pessoa.refresh_from_db()
        self.assertEqual(pessoa.username, 'maria@gmail.com')  # intacto
        self.assertEqual(convertidos, 0)
        self.assertEqual(len(pulados), 1)

    def test_pula_quando_o_email_ja_pertence_a_outro_usuario(self):
        from app.migracoes_loja_login import converter_responsaveis

        User.objects.create_user(username='lapa@unistock.com', password='123')
        pessoa = User.objects.create_user(username='pedro@gmail.com', password='123')
        Loja.objects.create(
            nome_loja='Lapa', cidade='Patos', endereco='Rua 1',
            email='lapa@unistock.com', responsavel=pessoa,
        )

        convertidos, pulados = converter_responsaveis(User, Loja)

        pessoa.refresh_from_db()
        self.assertEqual(pessoa.username, 'pedro@gmail.com')  # intacto
        self.assertEqual(convertidos, 0)
        self.assertEqual(len(pulados), 1)

    def test_nao_mexe_em_loja_sem_responsavel(self):
        from app.migracoes_loja_login import converter_responsaveis

        Loja.objects.create(
            nome_loja='Vazia', cidade='Patos', endereco='Rua 3',
            email='vazia@unistock.com',
        )

        convertidos, pulados = converter_responsaveis(User, Loja)

        self.assertEqual(convertidos, 0)
        self.assertEqual(pulados, [])
```

- [ ] **Step 2: Rode o teste e confirme que falha**

```bash
docker exec unistock python manage.py test app.tests_loja_login.ConverterResponsaveisTests
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'app.migracoes_loja_login'`

- [ ] **Step 3a: Implemente a função de conversão**

Crie `backend/app/migracoes_loja_login.py`:

```python
"""Conversao dos responsaveis pessoais para o login da loja.

Fica fora do arquivo de migracao para poder ser testada. Recebe os models por
parametro para funcionar tanto com os models reais quanto com os historicos que
a migracao entrega via apps.get_model.
"""


def converter_responsaveis(User, Loja):
    """Troca o login do responsavel de cada loja para o email da loja.

    E o MESMO usuario: pedidos e movimentacoes antigos continuam apontando para
    ele. Devolve (quantos_convertidos, lista_de_pulados_com_motivo).
    """
    convertidos = 0
    pulados = []

    for loja in Loja.objects.exclude(responsavel=None).select_related("responsavel"):
        if not loja.email:
            pulados.append((loja.nome_loja, "loja sem email cadastrado"))
            continue

        acesso = loja.responsavel
        if acesso.username == loja.email:
            continue  # ja convertida

        if User.objects.filter(username=loja.email).exclude(pk=acesso.pk).exists():
            pulados.append((loja.nome_loja, f"email {loja.email} ja em uso"))
            continue

        acesso.username = loja.email
        acesso.email = loja.email
        acesso.save(update_fields=["username", "email"])
        convertidos += 1

    return convertidos, pulados
```

- [ ] **Step 3b: Crie a migração**

Crie `backend/app/migrations/0017_converter_responsaveis_para_email_loja.py`:

```python
# O acesso da loja passa a ser a propria loja: o login do responsavel vira o
# email da loja. E o mesmo usuario, entao o historico (Pedido.responsavel,
# MovimentacaoEstoque.usuario) continua intacto.
from django.db import migrations

from app.migracoes_loja_login import converter_responsaveis


def converter(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Loja = apps.get_model("app", "Loja")

    convertidos, pulados = converter_responsaveis(User, Loja)
    print(f"\n  Lojas convertidas para login proprio: {convertidos}")
    for nome, motivo in pulados:
        print(f"  PULADA: {nome} — {motivo}")


def reverter(apps, schema_editor):
    # Sem volta: o email pessoal anterior nao fica guardado em lugar nenhum.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0016_remove_preferencianotificacao_digest_ativo_and_more"),
    ]

    operations = [
        migrations.RunPython(converter, reverter),
    ]
```

- [ ] **Step 4: Rode o teste e confirme que passa**

```bash
docker exec unistock python manage.py test app.tests_loja_login.ConverterResponsaveisTests
```

Esperado: `Ran 4 tests` / `OK`

- [ ] **Step 5: Rode a migração e reinicie**

```bash
docker exec unistock python manage.py migrate app
docker compose restart api worker beat
```

Esperado: `Applying app.0017_converter_responsaveis_para_email_loja... OK`, com o
relatório de convertidas/puladas impresso.

- [ ] **Step 6: Rode a suíte inteira**

```bash
docker exec unistock python manage.py test app
```

Esperado: `OK`

- [ ] **Step 7: Commit**

```bash
git add backend/app/migracoes_loja_login.py backend/app/migrations/0017_converter_responsaveis_para_email_loja.py backend/app/tests_loja_login.py
git commit -m "feat(loja): migra responsaveis existentes para o login da loja"
```

---

## Task 8: Abrir o PR do backend

- [ ] **Step 1: Confirme que está na branch certa e que a suíte passa**

```bash
git branch --show-current      # esperado: feature/loja-como-login
docker exec unistock python manage.py test app
```

- [ ] **Step 2: Push e PR para `dev-local`**

```bash
git push -u origin feature/loja-como-login
gh pr create --base dev-local --head feature/loja-como-login \
  --title "A loja vira o login (fim do responsavel pessoal)" \
  --body "Implementa docs/superpowers/specs/2026-07-25-loja-como-login-design.md

O acesso da loja deixa de ser uma pessoa e passa a ser a propria loja:
Loja.responsavel aponta para um usuario cujo login e o email da loja.

- Criar a loja cria o acesso (inativo, sem senha) e manda o link de definir senha
- Trocar o email da loja atualiza o login junto
- Endpoints de definir senha (token de uso unico) e esqueci a senha
- Migracao converte os responsaveis existentes, preservando o historico

Base: dev-local. NAO mandar para dev-producao/main."
```

**IMPORTANTE:** os hooks do ruflo às vezes já criaram o PR. Antes de criar,
confira com `gh pr list --head feature/loja-como-login`. Se já existir, use
`gh pr edit <n> --body "..."` em vez de criar outro.

---

## Task 9: Front — serviços de senha

**Files:**
- Modify: `frontend/services/auth.ts`

Daqui em diante, trabalhe no repositório `Unistock_Front`, branch
`feature/loja-como-login` (já criada).

- [ ] **Step 1: Adicione as funções**

Em `frontend/services/auth.ts`, no fim do arquivo:

```typescript
// A loja define a senha no 1o acesso (link enviado pro email da loja) e usa o
// mesmo fluxo quando esquece a senha.
export const definirSenha = async (token: string, password: string) => {
  const response = await apiV1(
    `/user/definir-senha/${encodeURIComponent(token)}/`,
    {
      method: "POST",
      body: JSON.stringify({ password }),
    },
  );

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const erro =
      (Array.isArray(data.password) ? data.password[0] : data.error) ??
      "Nao foi possivel definir a senha.";
    throw new Error(erro);
  }
  return data;
};

export const esqueciSenha = async (email: string) => {
  const response = await apiV1("/user/esqueci-senha/", {
    method: "POST",
    body: JSON.stringify({ email }),
  });

  if (!response.ok) {
    throw new Error("Nao foi possivel enviar o link. Tente novamente.");
  }
  return response.json().catch(() => ({}));
};
```

- [ ] **Step 2: Verifique que compila**

```bash
cd frontend && npx tsc --noEmit
```

Esperado: sem saída (sucesso). Se acusar `apiV1` não definido, confira o import
no topo do arquivo — `confirmarConta` já usa `apiV1`, então ele existe.

- [ ] **Step 3: Commit**

```bash
git add frontend/services/auth.ts
git commit -m "feat(auth): servicos de definir e recuperar senha"
```

---

## Task 10: Front — tela de esqueci a senha

**Files:**
- Modify: `frontend/app/esqueci-senha/page.tsx`

Hoje o `handleSubmit` só faz `router.push("/redefinir-senha")` — não chama API
nenhuma. Ligar de verdade.

- [ ] **Step 1: Substitua o handleSubmit**

Em `frontend/app/esqueci-senha/page.tsx`, troque o `handleSubmit` atual por:

```typescript
  const [enviando, setEnviando] = useState(false);
  const [enviado, setEnviado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      await esqueciSenha(email.trim());
      setEnviado(true);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao enviar o link.");
    } finally {
      setEnviando(false);
    }
  };
```

Adicione o import no topo:

```typescript
import { esqueciSenha } from "@/services/auth";
```

E remova o `useRouter`/`router` se ficarem sem uso (o TypeScript acusa).

- [ ] **Step 2: Mostre o resultado na tela**

Dentro do `<form>`, logo antes do botão de enviar, insira:

```tsx
              {enviado && (
                <p className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-sm font-medium text-emerald-500">
                  Se este e-mail estiver cadastrado, enviamos o link para
                  definir a senha. Confira a caixa de entrada.
                </p>
              )}
              {erro && (
                <p className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm font-medium text-red-500">
                  {erro}
                </p>
              )}
```

E no botão de enviar, troque o texto por `{enviando ? "Enviando..." : "Enviar link"}`
e adicione `disabled={enviando}`.

- [ ] **Step 3: Verifique que compila**

```bash
cd frontend && npx tsc --noEmit
```

Esperado: sem saída.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/esqueci-senha/page.tsx
git commit -m "feat(auth): tela de esqueci a senha passa a chamar a API"
```

---

## Task 11: Front — tela de definir senha

**Files:**
- Modify: `frontend/app/redefinir-senha/page.tsx`

A tela precisa ler o token da URL. O link do e-mail é
`{FRONTEND_URL}/redefinir-senha/{token}`, então a rota vira dinâmica.

- [ ] **Step 1: Transforme em rota dinâmica**

```bash
cd frontend
mkdir -p "app/redefinir-senha/[token]"
git mv app/redefinir-senha/page.tsx "app/redefinir-senha/[token]/page.tsx"
```

- [ ] **Step 2: Ligue o formulário à API**

O arquivo já tem os states `password`, `confirmPassword`, `error` e `success` —
**use esses nomes, não crie novos**. O `handleSubmit` atual (linha ~22) só valida
e não chama API.

Adicione os imports no topo:

```typescript
import { useParams, useRouter } from "next/navigation";
import { definirSenha } from "@/services/auth";
```

Adicione um state de envio junto dos outros (depois de `const [success, setSuccess] = useState(false);`):

```typescript
  const [salvando, setSalvando] = useState(false);
  const params = useParams<{ token: string }>();
  const router = useRouter();
```

Substitua o `handleSubmit` inteiro por:

```typescript
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(false);

    if (password.length < 6) {
      setError("A senha precisa ter pelo menos 6 caracteres.");
      return;
    }

    if (password !== confirmPassword) {
      setError("As senhas não conferem.");
      return;
    }

    setSalvando(true);
    try {
      await definirSenha(params.token, password);
      setSuccess(true);
      // Deixa a mensagem de sucesso aparecer antes de sair da tela.
      setTimeout(() => router.push("/login"), 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao definir a senha.");
    } finally {
      setSalvando(false);
    }
  };
```

A validação de 6 caracteres é só cortesia — o backend valida de verdade com os
`AUTH_PASSWORD_VALIDATORS` e devolve a mensagem, que cai no `setError`.

- [ ] **Step 3: Desabilite o botão enquanto salva**

No botão de submit do formulário, adicione `disabled={salvando}` e troque o texto
por `{salvando ? "Salvando..." : "Salvar senha"}`. Os blocos de `error` e
`success` já existem na tela — não precisa criar.

- [ ] **Step 4: Verifique que compila e builda**

```bash
npx tsc --noEmit && npm run build
```

Esperado: build OK, com a rota `/redefinir-senha/[token]` listada como dinâmica (ƒ).

- [ ] **Step 5: Commit**

```bash
git add frontend/app/redefinir-senha
git commit -m "feat(auth): tela de definir senha por token"
```

---

## Task 12: Front — limpar o que não faz mais sentido

**Files:**
- Modify: `frontend/components/usuarios/CadastroUsuarioForm.tsx`
- Modify: `frontend/app/lojas/editar/[id]/page.tsx`

- [ ] **Step 1: Remova a opção "Responsável" do cadastro de usuário**

Em `frontend/components/usuarios/CadastroUsuarioForm.tsx`, remova a opção
`responsavel` do seletor de tipo de usuário e o campo de seleção de loja que só
aparecia para responsável. O formulário passa a criar **apenas Gerente**.

Ajuste o texto de apoio para explicar a mudança, por exemplo:

```tsx
<p className="mt-1 text-xs font-medium text-theme-text-sub">
  Responsaveis nao sao mais cadastrados aqui: cada loja tem o proprio acesso,
  criado junto com a loja e usando o e-mail dela.
</p>
```

- [ ] **Step 2a: Adicione `email_acesso` ao tipo Loja**

O tipo de leitura fica em `frontend/hooks/useLoja.ts` (interface `Loja`, linha 7)
— **não** em `services/uni.ts`. Acrescente o campo:

```typescript
  email_acesso?: string | null;
```

- [ ] **Step 2b: Remova `responsavel` do payload de escrita**

Em `frontend/services/uni.ts`, no tipo `LojaUpdateData` (linha ~53), apague a
linha `responsavel: number | null;`. A API não aceita mais escrita nesse campo.

- [ ] **Step 2c: Campo responsável vira somente leitura**

Em `frontend/app/lojas/editar/[id]/page.tsx`, troque o `<select>` de responsável
por um bloco de leitura:

```tsx
              <div>
                <label className="text-xs font-black uppercase tracking-[2px] text-theme-text-sub">
                  Acesso da loja
                </label>
                <p className="mt-2 rounded-lg border border-theme-border bg-theme-header px-4 py-3 text-sm font-bold text-theme-text-title">
                  {emailAcesso || "Sem acesso — cadastre um e-mail para a loja"}
                </p>
                <p className="mt-1 text-xs font-medium text-theme-text-sub">
                  A loja entra no sistema com este e-mail. Ele acompanha o e-mail
                  do cadastro acima.
                </p>
              </div>
```

Troque o state `const [responsavel, setResponsavel] = useState("");` (linha ~70)
por `const [emailAcesso, setEmailAcesso] = useState("");` e, onde a tela carrega a
loja, preencha com `setEmailAcesso(dados.email_acesso ?? "")` em vez de
`setResponsavel(...)`.

Remova também o state `usuarios` (`useState<UsuarioResumo[]>([])`, linha ~71), a
chamada a `getUsuarios()` e o import de `UsuarioResumo`/`getUsuarios` — a tela não
lista mais pessoas. E tire `responsavel` do objeto enviado no `patchLoja`.

- [ ] **Step 3: Verifique que compila e builda**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

Esperado: build OK. Corrija os erros de tipo que aparecerem por causa da remoção
de `responsavel` — são exatamente os pontos que precisavam mudar.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/usuarios/CadastroUsuarioForm.tsx frontend/app/lojas/editar frontend/services/uni.ts
git commit -m "feat(loja): remove cadastro de responsavel e mostra o acesso da loja"
```

---

## Task 13: Abrir o PR do frontend

- [ ] **Step 1: Confirme branch e build**

```bash
git branch --show-current      # esperado: feature/loja-como-login
cd frontend && npx tsc --noEmit && npm run build
```

- [ ] **Step 2: Push e PR para `dev-local`**

```bash
git push -u origin feature/loja-como-login
gh pr create --base dev-local --head feature/loja-como-login \
  --title "A loja vira o login — telas de senha e limpeza" \
  --body "Front do PR Unistock_Back (a loja vira o login). Precisa que o back entre junto.

- /esqueci-senha deixa de ser casca e chama a API
- /redefinir-senha/[token] define a senha do 1o acesso
- Cadastro de usuario passa a criar so Gerente
- Edicao de loja mostra o e-mail de acesso (somente leitura)

Base: dev-local. NAO mandar para dev-producao/main."
```

Mesma ressalva da Task 8: confira antes se os hooks já criaram o PR.

---

## Teste manual de ponta a ponta (depois dos merges)

1. Crie uma loja com um e-mail que você consiga acessar.
2. Confira que chegou o e-mail "Defina a senha da sua conta no Unistock".
3. Abra o link, defina uma senha forte.
4. Faça login com o **e-mail da loja** e a senha nova.
5. Confirme que essa sessão vê **só** o estoque e os pedidos daquela loja.
6. Abra o mesmo link de novo — deve recusar (uso único).
7. Use "Esqueci a senha" com o e-mail da loja e confirme que chega um link novo.
