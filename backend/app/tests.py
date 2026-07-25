import re

from django.core import mail
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.contrib.auth.models import User, Group,Permission
from django.contrib.contenttypes.models import ContentType
from app.models import Loja, MovimentacaoEstoque, Produto, Pedido, ItemPedido, Estoque, Notificacao
from app.notifications import notificar_estoque_baixo
from rest_framework.test import APITestCase
from rest_framework.test import APIClient
from django.urls import reverse


from rest_framework.test import APITestCase, APIClient
from django.urls import reverse
from django.contrib.auth.models import User, Group
from app.models import Loja


class PedidoAPITestCase(APITestCase):

    def setUp(self):
        self.client = APIClient()

        # Criar grupos
        self.grupo_responsavel, _ = Group.objects.get_or_create(name='Responsavel')
        self.grupo_gerente, _ = Group.objects.get_or_create(name='Gerente')

        # Usuário responsável
        self.responsavel = User.objects.create_user(
            username='teste',
            password='123'
        )
        self.responsavel.groups.add(self.grupo_responsavel)

        # Usuário gerente
        self.gerente = User.objects.create_user(
            username='admin',
            password='123'
        )
        self.gerente.groups.add(self.grupo_gerente)

    
        self.produto = Produto.objects.create(
            nome_produto="coxinha",
            unidade_medida="QUILO",
            categoria="SALGADOS_GDE",
        )
        # Loja
        self.loja = Loja.objects.create(
            nome_loja='Loja A',
            endereco='Rua 1',
            responsavel=self.responsavel
        )



    def test_registro_e_login(self):
        # registra (conta nasce inativa; email de confirmacao no outbox)
        self.client.post("/api/v1/user/registrar/", {
            "email": "novo@email.com",
            "password": "123456",
            "tipo_usuario": "responsavel"
        })

        # antes de confirmar, login e recusado com mensagem clara
        response = self.client.post("/login/", {
            "email": "novo@email.com",
            "password": "123456"
        })
        self.assertEqual(response.status_code, 403)

        # confirma pelo link do email
        token = re.search(r"/confirmar-conta/(\S+)", mail.outbox[-1].body).group(1)
        response = self.client.get(f"/api/v1/user/confirmar/{token}/")
        self.assertEqual(response.status_code, 200)

        # login
        response = self.client.post("/login/", {
            "email": "novo@email.com",
            "password": "123456"
        })
        self.assertEqual(response.status_code, 200)




    

    def test_login_sucesso(self):
        url = "/login/"

        data = {
            "email": "teste",
            "password": "123"
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)

        # valida cookies JWT
        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)


    def test_fluxo_completo_gerente(self):
        # login como gerente
        self.client.force_authenticate(user=self.gerente)

        # cria produto
        url_produto = reverse('produto-list')

        produto_data = {
            "nome_produto": "Produto X",
            "unidade_medida": "UNIDADE",
            "categoria": "MERCADO",
        }

        response = self.client.post(url_produto, produto_data)
        self.assertEqual(response.status_code, 201)

        # cria loja
        url_loja = reverse('loja-list')

        loja_data = {
            "nome_loja": "Loja Gerente",
            "cidade": "Patos",
            "endereco": "Rua 1",
            "responsavel": self.gerente.id
        }

        response = self.client.post(url_loja, loja_data)
        self.assertEqual(response.status_code, 201)

    def test_responsavel_cria_pedido(self):
        self.client.force_authenticate(user=self.responsavel)

        url = "/api/v1/pedidos/"

        data = {
            "loja": str(self.loja.public_id),
            "itens": [
                {
                    "produto": str(self.produto.public_id),
                    "quantidade": 2
                }
            ]
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertIn("id", response.data)


    def test_user_nao_pode_criar_produto(self):
        self.client.force_authenticate(user=self.responsavel)
        

        url = reverse('produto-list')

        data = {
            "nome_produto": "Produto Teste",
            "unidade_medida": "UNIDADE",
            "categoria": "MERCADO",
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 403)

    def test_responsavel_nao_pode_criar_loja(self):
        self.client.force_authenticate(user=self.responsavel)

        url = reverse('loja-list')

        data = {
            "nome_loja": "Loja Teste",
            "endereco": "Rua 2",
            "responsavel": self.responsavel.id
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 403)
    
 
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
        produto = Produto.objects.create(
            nome_produto='Coxinha',
            categoria='SALGADOS_GDE',
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
        produto = Produto.objects.create(nome_produto='Guarana', categoria='MERCADO')
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
        produto = Produto.objects.create(nome_produto='Coxinho', categoria='MERCADO')
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
        produto = Produto.objects.create(
            nome_produto='Esfiha',
            categoria='ESFIHAS_GDE',
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


class EstoqueBaixosTests(APITestCase):
    """Painel de estoque baixo: /estoque/baixos/ (gerente ve todas as lojas)."""

    def setUp(self):
        grupo_gerente, _ = Group.objects.get_or_create(name='Gerente')
        self.gerente = User.objects.create_user(username='ger', password='123')
        self.gerente.groups.add(grupo_gerente)
        self.resp_a = User.objects.create_user(username='respa', password='123')

        self.loja_a = Loja.objects.create(
            nome_loja='Loja A', cidade='Patos', endereco='Rua 1',
            responsavel=self.resp_a,
        )
        self.loja_b = Loja.objects.create(
            nome_loja='Loja B', cidade='Patos', endereco='Rua 2',
        )
        coxinha = Produto.objects.create(
            nome_produto='Coxinha', categoria='SALGADOS_GDE',
        )
        coca = Produto.objects.create(nome_produto='Coca', categoria='MERCADO')

        # Baixo na loja A, baixo na loja B, e um em dia na loja A.
        Estoque.objects.create(
            loja=self.loja_a, produto=coxinha,
            quantidade_atual=1, quantidade_minima=5,
        )
        Estoque.objects.create(
            loja=self.loja_b, produto=coxinha,
            quantidade_atual=0, quantidade_minima=3,
        )
        Estoque.objects.create(
            loja=self.loja_a, produto=coca,
            quantidade_atual=50, quantidade_minima=5,
        )

    def test_gerente_ve_baixos_de_todas_as_lojas(self):
        self.client.force_authenticate(self.gerente)

        response = self.client.get('/api/v1/estoque/baixos/')

        self.assertEqual(response.status_code, 200, response.data)
        nomes_lojas = {item['loja_nome'] for item in response.data}
        self.assertEqual(nomes_lojas, {'Loja A', 'Loja B'})
        self.assertEqual(len(response.data), 2)

    def test_responsavel_ve_apenas_baixos_da_sua_loja(self):
        self.client.force_authenticate(self.resp_a)

        response = self.client.get('/api/v1/estoque/baixos/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['loja_nome'], 'Loja A')
        self.assertEqual(response.data[0]['produto_nome'], 'Coxinha')

    def test_produto_acima_do_minimo_nao_aparece(self):
        self.client.force_authenticate(self.gerente)

        response = self.client.get('/api/v1/estoque/baixos/')

        produtos = {item['produto_nome'] for item in response.data}
        self.assertNotIn('Coca', produtos)


class EstoqueIntegridadeTests(APITestCase):
    """Constraints do Estoque e historico de MovimentacaoEstoque."""

    def setUp(self):
        self.grupo_gerente, _ = Group.objects.get_or_create(name='Gerente')
        self.user = User.objects.create_user(username='resp', password='123')
        self.gerente = User.objects.create_user(username='ger', password='123')
        self.gerente.groups.add(self.grupo_gerente)

        self.loja = Loja.objects.create(
            nome_loja='Loja A', cidade='Patos', endereco='Rua 1',
            responsavel=self.user,
        )
        self.produto = Produto.objects.create(
            nome_produto='Coxinha', categoria='SALGADOS_GDE',
        )
        self.estoque = Estoque.objects.create(
            loja=self.loja, produto=self.produto,
            quantidade_atual=10, quantidade_minima=2,
        )

    def test_nao_permite_estoque_duplicado_para_produto_e_loja(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Estoque.objects.create(
                loja=self.loja, produto=self.produto,
                quantidade_atual=5, quantidade_minima=1,
            )

    def test_nao_permite_estoque_negativo(self):
        outro = Produto.objects.create(nome_produto='Coca', categoria='MERCADO')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Estoque.objects.create(
                loja=self.loja, produto=outro,
                quantidade_atual=-1, quantidade_minima=0,
            )

    def test_entrega_de_pedido_registra_movimentacao_entrada(self):
        from app.api.v1.viewsets import somar_itens_no_estoque

        pedido = Pedido.objects.create(responsavel=self.user, loja=self.loja)
        ItemPedido.objects.create(
            pedido=pedido, produto=self.produto, quantidade=4, responsavel=self.user,
        )
        somar_itens_no_estoque(pedido)

        mov = MovimentacaoEstoque.objects.get(tipo=MovimentacaoEstoque.Tipo.ENTRADA)
        self.assertEqual(mov.loja_destino, self.loja)
        self.assertEqual(mov.produto, self.produto)
        self.assertEqual(mov.quantidade, 4)
        self.assertEqual(mov.usuario, self.user)

    def test_venda_pdv_registra_movimentacao_saida(self):
        self.client.force_authenticate(self.gerente)
        response = self.client.post(
            '/api/v1/vendas/',
            {
                'loja_id': str(self.loja.public_id),
                'itens': [{'produto_id': str(self.produto.public_id), 'quantidade': 3}],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)

        mov = MovimentacaoEstoque.objects.get(tipo=MovimentacaoEstoque.Tipo.VENDA_PDV)
        self.assertEqual(mov.loja_origem, self.loja)
        self.assertEqual(mov.quantidade, 3)
        self.assertEqual(mov.usuario, self.gerente)
        self.estoque.refresh_from_db()
        self.assertEqual(self.estoque.quantidade_atual, 7)

    def test_ajuste_manual_registra_delta(self):
        self.client.force_authenticate(self.gerente)
        response = self.client.patch(
            f'/api/v1/estoque/{self.estoque.public_id}/',
            {'quantidade_atual': 6},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

        mov = MovimentacaoEstoque.objects.get(tipo=MovimentacaoEstoque.Tipo.AJUSTE)
        self.assertEqual(mov.quantidade, -4)  # 10 -> 6
        self.assertEqual(mov.loja_origem, self.loja)
        self.assertEqual(mov.usuario, self.gerente)


class NotificacaoAssincronaTests(APITestCase):
    """Confirmacao de conta por email e alerta assincrono de estoque baixo.

    CELERY_TASK_ALWAYS_EAGER esta ativo em testes: .delay() roda na hora e o
    email cai em django.core.mail.outbox.
    """

    def setUp(self):
        Group.objects.get_or_create(name='Responsavel')
        Group.objects.get_or_create(name='Gerente')

    def test_registro_publico_cria_conta_inativa_e_envia_email(self):
        response = self.client.post("/api/v1/user/registrar/", {
            "email": "ana@email.com",
            "password": "123456",
            "tipo_usuario": "responsavel",
        })
        self.assertEqual(response.status_code, 201, response.data)

        user = User.objects.get(username="ana@email.com")
        self.assertFalse(user.is_active)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/confirmar-conta/", mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ["ana@email.com"])

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
        produto = Produto.objects.create(nome_produto='Coca', categoria='MERCADO')
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

