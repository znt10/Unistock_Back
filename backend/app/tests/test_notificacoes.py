from django.contrib.auth.models import Group, User
from django.core import mail
from django.test import TestCase
from rest_framework.test import APITestCase

from app.models import Categoria, Estoque, Loja, Notificacao, Produto
from app.notifications import notificar_estoque_baixo


class NotificacaoEstoqueBaixoTestCase(TestCase):
    def test_notifica_apenas_responsavel_da_loja_com_estoque_baixo(self):
        grupo_responsavel, _ = Group.objects.get_or_create(name='Responsavel')
        responsavel_loja_1 = User.objects.create_user(
            username='loja1',
            email='loja1@email.com',
            password='123456',
        )
        responsavel_loja_1.groups.add(grupo_responsavel)
        responsavel_loja_2 = User.objects.create_user(
            username='loja2',
            email='loja2@email.com',
            password='123456',
        )
        responsavel_loja_2.groups.add(grupo_responsavel)

        loja_1 = Loja.objects.create(
            nome_loja='Loja 1',
            cidade='Cidade 1',
            endereco='Rua 1',
            responsavel=responsavel_loja_1,
        )
        Loja.objects.create(
            nome_loja='Loja 2',
            cidade='Cidade 2',
            endereco='Rua 2',
            responsavel=responsavel_loja_2,
        )
        categoria = Categoria.objects.get_or_create(nome='Salgados grande')[0]
        produto = Produto.objects.create(
            nome_produto='Coxinha',
            categoria=categoria,
            estoque_minimo_sugerido=5,
        )
        estoque = Estoque.objects.create(
            loja=loja_1,
            produto=produto,
            quantidade_atual=3,
            quantidade_minima=5,
        )

        notificar_estoque_baixo(estoque)

        self.assertTrue(
            Notificacao.objects.filter(
                usuario=responsavel_loja_1,
                tipo='estoque_baixo',
            ).exists()
        )
        self.assertFalse(
            Notificacao.objects.filter(
                usuario=responsavel_loja_2,
                tipo='estoque_baixo',
            ).exists()
        )

    def test_gerente_recebe_notificacao_de_qualquer_loja(self):
        """Gerente ve estoque baixo de todas as lojas, mesmo sem ter editado."""
        grupo_gerente, _ = Group.objects.get_or_create(name='Gerente')
        grupo_responsavel, _ = Group.objects.get_or_create(name='Responsavel')
        gerente = User.objects.create_user(
            username='ger@email.com', email='ger@email.com', password='123456',
        )
        gerente.groups.add(grupo_gerente)
        responsavel = User.objects.create_user(
            username='resp2@email.com', email='resp2@email.com', password='123456',
        )
        responsavel.groups.add(grupo_responsavel)

        loja = Loja.objects.create(
            nome_loja='Loja do Resp', cidade='Patos', endereco='Rua 9',
            responsavel=responsavel,
        )
        categoria = Categoria.objects.get_or_create(nome='Mercado')[0]
        produto = Produto.objects.create(nome_produto='Guarana', categoria=categoria)
        estoque = Estoque.objects.create(
            loja=loja, produto=produto, quantidade_atual=0, quantidade_minima=3,
        )

        # Quem mexeu foi o responsavel, nao o gerente.
        notificar_estoque_baixo(estoque, usuario_editor=responsavel)

        self.assertTrue(
            Notificacao.objects.filter(
                usuario=gerente, tipo='estoque_baixo', estoque=estoque
            ).exists()
        )
        self.assertTrue(
            Notificacao.objects.filter(
                usuario=responsavel, tipo='estoque_baixo', estoque=estoque
            ).exists()
        )

    def test_atualiza_mensagem_quando_estoque_muda_e_segue_baixo(self):
        """Sem spam, mas sem mentir: mesma notificacao, numeros atuais."""
        usuario = User.objects.create_user(
            username='atualiza@email.com', email='a@email.com', password='123456',
        )
        loja = Loja.objects.create(
            nome_loja='Loja Muda', cidade='Patos', endereco='Rua 3',
            responsavel=usuario,
        )
        categoria = Categoria.objects.get_or_create(nome='Mercado')[0]
        produto = Produto.objects.create(nome_produto='Coxinho', categoria=categoria)
        estoque = Estoque.objects.create(
            loja=loja, produto=produto, quantidade_atual=1, quantidade_minima=3,
        )
        notificar_estoque_baixo(estoque)

        # Continua baixo, mas mudou de 1 para 2.
        estoque.quantidade_atual = 2
        estoque.save()
        notificar_estoque_baixo(estoque)

        notificacoes = Notificacao.objects.filter(
            usuario=usuario, tipo='estoque_baixo', estoque=estoque
        )
        self.assertEqual(notificacoes.count(), 1)  # sem duplicar
        self.assertIn('Atual: 2', notificacoes.first().mensagem)
        self.assertNotIn('Atual: 1', notificacoes.first().mensagem)

    def test_nao_duplica_notificacao_do_mesmo_estoque(self):
        usuario = User.objects.create_user(
            username='loja',
            email='loja@email.com',
            password='123456',
        )
        loja = Loja.objects.create(
            nome_loja='Loja',
            cidade='Cidade',
            endereco='Rua',
            responsavel=usuario,
        )
        categoria = Categoria.objects.get_or_create(nome='Esfihas grande')[0]
        produto = Produto.objects.create(
            nome_produto='Esfiha',
            categoria=categoria,
        )
        estoque = Estoque.objects.create(
            loja=loja,
            produto=produto,
            quantidade_atual=1,
            quantidade_minima=2,
        )

        notificar_estoque_baixo(estoque)
        Notificacao.objects.update(lida=True)
        notificar_estoque_baixo(estoque)

        self.assertEqual(
            Notificacao.objects.filter(
                usuario=usuario,
                tipo='estoque_baixo',
            ).count(),
            1,
        )


class NotificacaoAssincronaTests(APITestCase):
    """Confirmacao de conta por email e alerta assincrono de estoque baixo.

    CELERY_TASK_ALWAYS_EAGER esta ativo em testes: .delay() roda na hora e o
    email cai em django.core.mail.outbox.
    """

    def setUp(self):
        Group.objects.get_or_create(name='Responsavel')
        Group.objects.get_or_create(name='Gerente')

    def test_registro_publico_nao_existe_mais(self):
        """Cadastro aberto acabou: loja ganha acesso ao ser criada, gerente so
        por outro gerente/admin. Antes, um anonimo criava conta aqui."""
        response = self.client.post("/api/v1/user/registrar/", {
            "email": "ana@email.com",
            "password": "123456",
            "tipo_usuario": "responsavel",
        })

        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="ana@email.com").exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_token_invalido_400(self):
        response = self.client.get("/api/v1/user/confirmar/token-falso/")
        self.assertEqual(response.status_code, 400)

    def test_alerta_estoque_baixo_nao_envia_email(self):
        """Alerta imediato e so in-app: email de estoque so no digest diario."""
        responsavel = User.objects.create_user(
            username='resp@email.com', email='resp@email.com', password='123456',
        )
        loja = Loja.objects.create(
            nome_loja='Loja Email', cidade='Patos', endereco='Rua 1',
            responsavel=responsavel,
        )
        categoria = Categoria.objects.get_or_create(nome='Mercado')[0]
        produto = Produto.objects.create(nome_produto='Coca', categoria=categoria)
        estoque = Estoque.objects.create(
            loja=loja, produto=produto,
            quantidade_atual=1, quantidade_minima=5,
        )

        notificar_estoque_baixo(estoque)

        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            Notificacao.objects.filter(
                usuario=responsavel, tipo='estoque_baixo'
            ).count(),
            1,
        )


class PreferenciaNotificacaoTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='pref@email.com', email='pref@email.com', password='123456',
        )
        self.client.force_authenticate(self.user)

    def test_get_cria_preferencia_com_defaults(self):
        response = self.client.get('/api/v1/preferencias-notificacao/me/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['email_ativo'])
        self.assertFalse(response.data['whatsapp_ativo'])

    def test_patch_atualiza_preferencia(self):
        response = self.client.patch(
            '/api/v1/preferencias-notificacao/me/',
            {'email_ativo': False, 'telefone_whatsapp': '+55 (83) 9999-0000'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data['email_ativo'])
        self.assertEqual(response.data['telefone_whatsapp'], '558399990000')

    def test_nao_expoe_configuracao_de_digest(self):
        """Digest virou por loja (7h): nao ha mais ajuste por usuario."""
        response = self.client.get('/api/v1/preferencias-notificacao/me/')

        self.assertNotIn('digest_ativo', response.data)
        self.assertNotIn('digest_horario', response.data)
        self.assertNotIn('digest_dias_semana', response.data)
