"""Digest diario de estoque baixo (tasks disparar_digests / enviar_digest)."""

import datetime

from django.core import mail
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APITestCase

from app.models import Estoque, Loja, PreferenciaNotificacao, Produto
from app.notifications.tasks import disparar_digests

TODOS_OS_DIAS = "1,2,3,4,5,6,7"


class DigestDiarioTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='digest@email.com', email='digest@email.com', password='123',
        )
        self.loja = Loja.objects.create(
            nome_loja='Loja Digest', cidade='Patos', endereco='Rua 1',
            responsavel=self.user,
        )
        self.produto = Produto.objects.create(nome_produto='Coxinha', categoria='SALGADOS_GDE')
        self.estoque = Estoque.objects.create(
            loja=self.loja, produto=self.produto,
            quantidade_atual=1, quantidade_minima=5,
        )

    def _prefs(self, **kwargs):
        padrao = {
            "usuario": self.user,
            "digest_ativo": True,
            "digest_horario": datetime.time(0, 0),  # sempre "ja passou"
            "digest_dias_semana": TODOS_OS_DIAS,
        }
        padrao.update(kwargs)
        return PreferenciaNotificacao.objects.create(**padrao)

    def test_digest_envia_um_email_com_itens_baixos(self):
        prefs = self._prefs()

        disparados = disparar_digests()

        self.assertEqual(disparados, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Coxinha', mail.outbox[0].body)
        self.assertIn('Loja Digest', mail.outbox[0].body)
        prefs.refresh_from_db()
        self.assertEqual(
            prefs.ultimo_digest_em, timezone.localtime(timezone.now()).date()
        )

    def test_nao_duplica_no_mesmo_dia(self):
        self._prefs()

        disparar_digests()
        disparados = disparar_digests()

        self.assertEqual(disparados, 0)
        self.assertEqual(len(mail.outbox), 1)

    def test_sem_estoque_baixo_nao_envia(self):
        self.estoque.quantidade_atual = 100
        self.estoque.save()
        self._prefs()

        disparar_digests()

        self.assertEqual(len(mail.outbox), 0)

    def test_dia_fora_da_agenda_nao_envia(self):
        hoje_iso = timezone.localtime(timezone.now()).isoweekday()
        outro_dia = str(hoje_iso % 7 + 1)  # qualquer dia != hoje
        self._prefs(digest_dias_semana=outro_dia)

        disparados = disparar_digests()

        self.assertEqual(disparados, 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_horario_ainda_nao_chegou_nao_envia(self):
        self._prefs(digest_horario=datetime.time(23, 59))

        # 23:59 quase sempre esta no futuro; se o teste rodar exatamente
        # nesse minuto, o filtro <= ainda seria legitimo — tolera os dois.
        agora = timezone.localtime(timezone.now()).time()
        disparados = disparar_digests()

        if agora < datetime.time(23, 59):
            self.assertEqual(disparados, 0)
            self.assertEqual(len(mail.outbox), 0)
