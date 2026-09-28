"""Limite por IP: o contador do throttle segue o visitante, nao o cabecalho.

Usa o login (taxa "login", 10/min) porque e a rota com o teto mais baixo.
"""

from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase

SEGREDO = "segredo-de-teste"


@override_settings(PROXY_SEGREDO=SEGREDO)
class LimitePorIpTests(APITestCase):
    def setUp(self):
        cache.clear()  # o historico do throttle vaza entre testes

    def tearDown(self):
        cache.clear()

    def logar(self, **cabecalhos):
        return self.client.post(
            "/login/",
            {"email": "ninguem@unistock.com", "password": "errada"},
            format="json",
            **cabecalhos,
        )

    def esgotar(self, **cabecalhos):
        for _ in range(10):
            self.assertEqual(self.logar(**cabecalhos).status_code, 401)

    def test_decimo_primeiro_login_do_mesmo_ip_e_barrado(self):
        self.esgotar(HTTP_X_FORWARDED_FOR="203.0.113.7")
        self.assertEqual(self.logar(HTTP_X_FORWARDED_FOR="203.0.113.7").status_code, 429)

    def test_trocar_o_comeco_do_x_forwarded_for_nao_escapa(self):
        # So o ultimo IP (o que o Traefik acrescentou) conta.
        for i in range(10):
            self.logar(HTTP_X_FORWARDED_FOR=f"10.0.0.{i}, 203.0.113.7")
        resposta = self.logar(HTTP_X_FORWARDED_FOR="10.0.0.99, 203.0.113.7")
        self.assertEqual(resposta.status_code, 429)

    def test_ip_do_next_com_segredo_separa_os_visitantes(self):
        # Todo pedido vem do servidor do Next (mesmo ultimo IP), mas cada
        # visitante tem o proprio contador.
        servidor = {"HTTP_X_FORWARDED_FOR": "198.51.100.1", "HTTP_X_PROXY_SEGREDO": SEGREDO}
        self.esgotar(HTTP_X_CLIENTE_IP="203.0.113.7", **servidor)
        self.assertEqual(self.logar(HTTP_X_CLIENTE_IP="203.0.113.7", **servidor).status_code, 429)
        self.assertEqual(self.logar(HTTP_X_CLIENTE_IP="203.0.113.8", **servidor).status_code, 401)

    def test_ip_do_next_sem_o_segredo_certo_e_ignorado(self):
        for i in range(10):
            self.logar(
                HTTP_X_FORWARDED_FOR="203.0.113.7",
                HTTP_X_CLIENTE_IP=f"10.0.0.{i}",
                HTTP_X_PROXY_SEGREDO="chute",
            )
        resposta = self.logar(
            HTTP_X_FORWARDED_FOR="203.0.113.7",
            HTTP_X_CLIENTE_IP="10.0.0.99",
            HTTP_X_PROXY_SEGREDO="chute",
        )
        self.assertEqual(resposta.status_code, 429)

    @override_settings(PROXY_SEGREDO="")
    def test_sem_segredo_configurado_o_cabecalho_e_ignorado(self):
        # Segredo vazio no servidor nao pode aceitar segredo vazio do pedido.
        for i in range(10):
            self.logar(HTTP_X_FORWARDED_FOR="203.0.113.7", HTTP_X_CLIENTE_IP=f"10.0.0.{i}")
        resposta = self.logar(HTTP_X_FORWARDED_FOR="203.0.113.7", HTTP_X_CLIENTE_IP="10.0.0.99")
        self.assertEqual(resposta.status_code, 429)
