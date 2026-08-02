import uuid

from django.db import models
from django.contrib.auth.models import User

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

class Loja(BaseModel):
    nome_loja = models.CharField(max_length=100)
    tipo = models.CharField(max_length=50, null=True, blank=True)
    cidade = models.CharField(max_length=100)
    endereco = models.CharField(max_length=255)
    ativo = models.BooleanField(default=True)
    responsavel = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    # Gerente "dono" da loja: quem administra ela no dashboard do Admin.
    # Nullable porque a loja pode nascer sem gerente atribuido ainda — quem
    # atribui e o Admin, depois da loja existir.
    gerente = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lojas_gerenciadas",
    )
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
    # Dono do catalogo: cada gerente tem as proprias categorias/produtos, sem
    # ver os de outro gerente. Nullable pelo mesmo motivo de Loja.gerente —
    # dado antigo sem dono definido ainda cai aqui (so o Admin ve, ate alguem
    # atribuir). Mesmo padrao de Loja: definido na criacao, nao muda depois.
    gerente = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="categorias_gerenciadas",
    )

    class Meta:
        ordering = ["ordem", "nome"]
        # Nao e mais unique=True sozinho: duas empresas podem ter categoria
        # com o mesmo nome, cada uma na propria.
        constraints = [
            models.UniqueConstraint(
                fields=["nome", "gerente"], name="categoria_nome_unico_por_gerente"
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
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        related_name="produtos",
    )
    # Mesmo dono-de-catalogo que Categoria.gerente — ver comentario la.
    gerente = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="produtos_gerenciados",
    )

    def __str__(self):
        return self.nome_produto
    

class Pedido(BaseModel):

    
    class Status(models.TextChoices):
        PENDENTE = "PENDENTE", "Pendente"
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


class EstoqueQuerySet(models.QuerySet):
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
