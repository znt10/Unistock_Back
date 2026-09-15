import uuid

from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify

def maximo_padrao(minimo):
    """O teto de partida para um nivel minimo. Sempre > minimo e nunca 0.

    Tres vezes o minimo e um palpite, nao uma verdade: existe para a linha
    nascer valida quando o sistema cria estoque sozinho (pedido entregue com
    produto que a loja ainda nao tinha). Quem sabe o giro da loja ajusta
    depois na tela da loja.
    """
    return max(int(minimo or 0) * 3, int(minimo or 0) + 1, 1)


class BaseModel(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        abstract = True

    def soft_delete(self):
        self.is_deleted = True
        self.save()

class Conta(BaseModel):
    """Uma empresa cliente do Unistock. E o limite de visibilidade do sistema.

    Loja, catalogo (Categoria/Produto) e os usuarios pertencem a uma conta, e
    ninguem enxerga fora da propria. Antes disso o dono do dado era o proprio
    usuario Gerente (Loja.gerente, Produto.gerente): dois gerentes da mesma
    empresa viravam dois silos, cada um com o proprio catalogo, e a loja
    perdia o catalogo se o gerente dela saisse.

    "Gerente" continua existindo, mas como CARGO (grupo do Django) — quem pode
    administrar —, nao como dono do dado.
    """

    nome = models.CharField(max_length=150)
    # Identificador legivel para URL e log. Gerado do nome no save().
    slug = models.SlugField(max_length=60, unique=True, null=True, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._slug_livre(slugify(self.nome)[:55])
        return super().save(*args, **kwargs)

    def _slug_livre(self, base):
        base = base or "conta"
        slug, sufixo = base, 2
        while Conta.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{sufixo}"
            sufixo += 1
        return slug

    def __str__(self):
        return self.nome


class PerfilUsuario(BaseModel):
    """Liga um usuario a conta dele.

    Super admin (is_superuser) NAO tem perfil, de proposito: quem nao tem
    conta vinculada e ou dono da plataforma (ve tudo) ou nao ve nada. Nao
    existe meio-termo — ver get_conta_do_usuario em permissions.py.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="perfil")
    conta = models.ForeignKey(Conta, on_delete=models.CASCADE, related_name="membros")

    def __str__(self):
        return f"{self.user.username} - {self.conta.nome}"


class Loja(BaseModel):
    class Tipo(models.TextChoices):
        # Grafia "Loja"/"Fabrica", e nao LOJA/FABRICA: e o que a tela de
        # cadastro ja envia e o que ja esta gravado. Trocar a grafia obrigaria
        # migrar front e dados juntos, sem ganho nenhum.
        LOJA = "Loja", "Loja"
        FABRICA = "Fabrica", "Fábrica"

    # PROTECT e nao CASCADE: apagar uma conta por engano no /admin nao pode
    # levar junto o historico de pedidos e movimentacao das lojas dela.
    conta = models.ForeignKey(Conta, on_delete=models.PROTECT, related_name="lojas")
    nome_loja = models.CharField(max_length=100)
    tipo = models.CharField(max_length=50, choices=Tipo.choices, default=Tipo.LOJA)
    cidade = models.CharField(max_length=100)
    endereco = models.CharField(max_length=255)
    ativo = models.BooleanField(default=True)
    responsavel = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    # Numero de WhatsApp DA LOJA (nao do responsavel): e por ele que o bot
    # identifica de qual loja veio o pedido. Apenas digitos.
    telefone_whatsapp = models.CharField(
        max_length=20, unique=True, null=True, blank=True
    )
    email = models.EmailField(null=True, blank=True)

    def __str__(self):
        return self.nome_loja



class Categoria(BaseModel):
    """Categoria de produto, cadastrada pelo Admin/Gerente (via /admin por enquanto).

    Substitui o antigo enum fixo em Produto.Categoria: para adicionar uma
    categoria nova basta criar uma linha aqui, sem alterar codigo.
    """

    nome = models.CharField(max_length=50)
    ordem = models.PositiveIntegerField(default=0)
    # Dono do catalogo e a EMPRESA, nao a pessoa: os dois gerentes de uma
    # mesma conta veem e editam as mesmas categorias. Nunca vem do request —
    # e sempre derivado do usuario logado (ver get_conta_do_usuario).
    conta = models.ForeignKey(
        Conta, on_delete=models.PROTECT, related_name="categorias"
    )

    class Meta:
        ordering = ["ordem", "nome"]
        # Nao e unique=True sozinho: duas empresas podem ter categoria com o
        # mesmo nome, cada uma na propria.
        constraints = [
            models.UniqueConstraint(
                fields=["nome", "conta"], name="categoria_nome_unico_por_conta"
            ),
        ]

    def __str__(self):
        return self.nome


class Produto(BaseModel):
    class UnidadeMedida(models.TextChoices):
        UNIDADE = "UNIDADE", "Unidade"
        CAIXA = "CAIXA", "Caixa"
        PACOTE = "PACOTE", "Pacote"
        QUILO = "QUILO", "Quilo"
        LITRO = "LITRO", "Litro"

    nome_produto = models.CharField(max_length=100)
    unidade_medida = models.CharField(
        max_length=20,
        choices=UnidadeMedida.choices,
        default=UnidadeMedida.UNIDADE,
    )
    quantidade_por_embalagem = models.PositiveIntegerField(null=True, blank=True)
    estoque_minimo_sugerido = models.PositiveIntegerField(default=1)
    # Valor de PARTIDA do teto quando a loja ainda nao tem linha deste produto.
    # Nao e um teto universal: o que vale e o de cada loja, porque a Lapa gira
    # muito mais que a Casa Verde e um numero so nao serve para as duas.
    estoque_maximo_sugerido = models.PositiveIntegerField(default=3)
    # Sai da fabrica propria em caixas com etiqueta. Sozinho nao liga o fluxo
    # das caixas: ver services/fabrica.segue_fluxo_fabrica.
    vem_da_fabrica = models.BooleanField(default=False)
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        related_name="produtos",
    )
    # Mesmo dono-de-catalogo que Categoria.conta — ver comentario la.
    conta = models.ForeignKey(
        Conta, on_delete=models.PROTECT, related_name="produtos"
    )

    def __str__(self):
        return self.nome_produto
    

class Pedido(BaseModel):

    
    class Status(models.TextChoices):
        PENDENTE = "PENDENTE", "Pendente"
        EM_ENTREGA = "EM_ENTREGA", "Em entrega"
        ENTREGUE = "ENTREGUE", "Entregue"
        CANCELADO = "CANCELADO", "Cancelado"

    # PROTECT: deletar um usuario nao pode apagar o historico de pedidos.
    responsavel = models.ForeignKey(User, on_delete=models.PROTECT)

    loja = models.ForeignKey(
        Loja,
        on_delete=models.CASCADE
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDENTE
    )
    descricao = models.TextField(blank=True, null=True)
    # Gravado na criacao, e nao lido do produto na hora: mudar vem_da_fabrica
    # num produto nao pode trocar o fluxo de um pedido que ja esta a caminho.
    da_fabrica = models.BooleanField(default=False)
    data_pedido = models.DateTimeField(auto_now_add=True)

    produtos = models.ManyToManyField(
        Produto,
        through='ItemPedido',
        related_name='pedidos'
    )
    
    def __str__(self):
        user_repr = self.responsavel.username if self.responsavel else "Unknown"
        loja_nome = self.loja.nome_loja if self.loja else "Unknown"
        return f"Pedido {self.id} - {user_repr} - {loja_nome}"


class ItemPedido(BaseModel):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='itens')
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    quantidade = models.IntegerField()
    responsavel = models.ForeignKey(User, on_delete=models.PROTECT)

    def __str__(self):
        return f"{self.quantidade} x {self.produto.nome_produto} (Pedido {self.pedido.id})"


class Caixa(BaseModel):
    """Uma caixa fisica que sai da fabrica com etiqueta de QR.

    Produto e loja vem do pedido (que tem um item so) — nao sao repetidos
    aqui, para nao existirem duas fontes do mesmo fato.
    """

    class Situacao(models.TextChoices):
        A_CAMINHO = "A_CAMINHO", "A caminho"
        CHEGOU = "CHEGOU", "Chegou"
        ABERTA = "ABERTA", "Aberta"
        ACABOU = "ACABOU", "Acabou"

    pedido = models.ForeignKey(Pedido, on_delete=models.PROTECT, related_name="caixas")
    # "caixa 2/3": o 3 e a quantidade do item do pedido.
    numero = models.PositiveSmallIntegerField()
    # Vai no QR. Aleatorio, e nao sequencial, para ninguem chegar a caixa de
    # outra loja adivinhando um numero.
    codigo = models.CharField(max_length=16, unique=True)
    situacao = models.CharField(
        max_length=10, choices=Situacao.choices, default=Situacao.A_CAMINHO
    )
    chegou_em = models.DateTimeField(null=True, blank=True)
    aberta_em = models.DateTimeField(null=True, blank=True)
    acabou_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["pedido", "numero"], name="caixa_numero_unico_no_pedido"
            ),
        ]

    def __str__(self):
        return f"Caixa {self.numero} do pedido {self.pedido_id}"


class EstoqueQuerySet(models.QuerySet):
    def excedidos(self):
        """Itens ACIMA do teto, em lojas ativas — o espelho de baixos().

        Mesma forma da consulta de falta de proposito: painel, digest e PDF
        consomem as duas do mesmo jeito, e quem mexer numa lembra da outra.
        """
        return (
            self.filter(
                loja__ativo=True,
                quantidade_atual__gt=models.F("quantidade_maxima"),
            )
            .select_related("produto", "loja")
            .order_by("loja__nome_loja", "produto__nome_produto")
        )

    def baixos(self):
        """Itens no/abaixo do minimo, em lojas ativas, prontos para exibir.

        Usado pelo painel (/estoque/baixos/) e pelo digest diario — os dois
        precisam da mesma definicao de "baixo".
        """
        return (
            self.filter(
                loja__ativo=True,
                quantidade_minima__gt=0,
                quantidade_atual__lte=models.F("quantidade_minima"),
            )
            .select_related("produto", "loja")
            .order_by("loja__nome_loja", "produto__nome_produto")
        )


class Estoque(BaseModel):
    class EstadoProduto(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        CONGELADO = "CONGELADO", "Congelado"
        RESFRIADO = "RESFRIADO", "Resfriado"

    objects = EstoqueQuerySet.as_manager()

    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    loja = models.ForeignKey(Loja, on_delete=models.CASCADE)
    quantidade_atual = models.IntegerField()
    quantidade_minima = models.IntegerField()
    # Teto DESTA loja para ESTE produto. Obrigatorio e sempre maior que o
    # minimo — um teto zerado nao existe, e um teto abaixo do minimo deixaria
    # a linha em falta e em excesso ao mesmo tempo.
    #
    # O motivo do campo nao e espaco de prateleira, e validade: produto parado
    # demais estraga. Por isso o excesso alerta, do mesmo jeito que a falta.
    quantidade_maxima = models.PositiveIntegerField()
    estado = models.CharField(
        max_length=20,
        choices=EstadoProduto.choices,
        default=EstadoProduto.NORMAL,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["produto", "loja"], name="estoque_unico_por_produto_loja"
            ),
            models.CheckConstraint(
                condition=models.Q(quantidade_atual__gte=0),
                name="estoque_nao_negativo",
            ),
            # No banco, e nao so no serializer: o bot, o PDV e o /admin
            # escrevem estoque sem passar pela API, e a regra precisa valer
            # para os quatro caminhos.
            models.CheckConstraint(
                condition=models.Q(quantidade_maxima__gt=models.F("quantidade_minima")),
                name="estoque_maximo_maior_que_minimo",
            ),
        ]

    def __str__(self):
        return f"Estoque de {self.produto.nome_produto} na {self.loja.nome_loja}"


class MovimentacaoEstoque(BaseModel):
    """Historico auditavel de toda alteracao de estoque.

    ENTRADA usa loja_destino; SAIDA/VENDA_PDV usam loja_origem; TRANSFERENCIA
    usa as duas; AJUSTE usa loja_origem com quantidade positiva ou negativa
    (delta do ajuste manual).
    """

    class Tipo(models.TextChoices):
        ENTRADA = "ENTRADA", "Entrada"
        SAIDA = "SAIDA", "Saída"
        TRANSFERENCIA = "TRANSFERENCIA", "Transferência"
        AJUSTE = "AJUSTE", "Ajuste"
        VENDA_PDV = "VENDA_PDV", "Venda PDV"

    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    produto = models.ForeignKey(
        Produto, on_delete=models.PROTECT, related_name="movimentacoes"
    )
    loja_origem = models.ForeignKey(
        Loja, on_delete=models.PROTECT, null=True, blank=True,
        related_name="movimentacoes_saida",
    )
    loja_destino = models.ForeignKey(
        Loja, on_delete=models.PROTECT, null=True, blank=True,
        related_name="movimentacoes_entrada",
    )
    quantidade = models.IntegerField()
    usuario = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="movimentacoes_estoque",
    )

    def __str__(self):
        return f"{self.tipo} {self.quantidade}x {self.produto.nome_produto}"


class PreferenciaNotificacao(BaseModel):
    """Canais de notificacao do usuario.

    Criada sob demanda (get_or_create) na primeira leitura — nao precisa de
    signal no cadastro. O resumo diario NAO fica aqui: ele e por loja (vai pro
    email da loja as 7h), nao por usuario.
    """

    usuario = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="preferencia_notificacao"
    )
    email_ativo = models.BooleanField(default=True)
    whatsapp_ativo = models.BooleanField(default=False)
    telefone_whatsapp = models.CharField(max_length=20, blank=True, default="")

    def __str__(self):
        return f"Preferencias de {self.usuario.username}"


class Notificacao(BaseModel):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notificacoes')
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, null=True, blank=True, related_name='notificacoes')
    loja = models.ForeignKey(Loja, on_delete=models.SET_NULL, null=True, blank=True, related_name='notificacoes')
    # Alertas de estoque baixo apontam para o Estoque: dedup/limpeza por FK,
    # nao por comparacao de texto da mensagem.
    estoque = models.ForeignKey(Estoque, on_delete=models.CASCADE, null=True, blank=True, related_name='notificacoes')
    tipo = models.CharField(max_length=50, default='info')
    titulo = models.CharField(max_length=120)
    mensagem = models.TextField()
    lida = models.BooleanField(default=False)

    def __str__(self):
        return self.titulo
