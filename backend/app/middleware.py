"""IP do visitante quando o pedido chega pelo Next.

O front reescreve /backend/* para a URL publica da api, entao o pedido faz
Traefik -> Next -> internet -> Traefik -> Django: o ultimo IP do
X-Forwarded-For e o do proprio servidor, para todo visitante. Sem isto, com
NUM_PROXIES = 1, o site inteiro dividiria um contador so do throttle.
"""

import hmac

from django.conf import settings


class IpDoProxyMiddleware:
    """Troca o X-Forwarded-For pelo IP que o Next mandou, SE vier com o
    segredo certo. Sem o segredo, o cabecalho e ignorado e vale o que o
    Traefik escreveu no fim da lista."""

    IP = "HTTP_X_CLIENTE_IP"
    SEGREDO = "HTTP_X_PROXY_SEGREDO"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # pop: nenhuma view deve ver o segredo, nem o IP sem conferencia.
        ip = request.META.pop(self.IP, "").strip()
        recebido = request.META.pop(self.SEGREDO, "")
        segredo = settings.PROXY_SEGREDO
        if segredo and ip and hmac.compare_digest(recebido.encode(), segredo.encode()):
            request.META["HTTP_X_FORWARDED_FOR"] = ip
        return self.get_response(request)
