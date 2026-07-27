from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from app.models import Estoque, Loja, Produto


class Command(BaseCommand):
    help = "Cria estoque inicial para testar o PDV UniStock."

    def add_arguments(self, parser):
        parser.add_argument(
            "--loja",
            help="Public ID da loja. Se omitido, cria estoque para todas as lojas ativas.",
        )
        parser.add_argument(
            "--quantidade",
            type=int,
            default=100,
            help="Quantidade inicial para cada produto. Padrao: 100.",
        )
        parser.add_argument(
            "--minimo",
            type=int,
            default=10,
            help="Quantidade minima para cada produto. Padrao: 10.",
        )
        parser.add_argument(
            "--sobrescrever",
            action="store_true",
            help="Atualiza tambem estoques que ja existem.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        quantidade = options["quantidade"]
        minimo = options["minimo"]

        if quantidade < 0:
            raise CommandError("A quantidade deve ser maior ou igual a zero.")

        if minimo < 0:
            raise CommandError("O minimo deve ser maior ou igual a zero.")

        lojas = Loja.objects.filter(ativo=True)
        if options["loja"]:
            lojas = lojas.filter(public_id=options["loja"])

        if not lojas.exists():
            raise CommandError("Nenhuma loja ativa encontrada.")

        produtos = Produto.objects.all().order_by("categoria__nome", "nome_produto")
        if not produtos.exists():
            raise CommandError("Nenhum produto encontrado.")

        criados = 0
        atualizados = 0
        ignorados = 0

        for loja in lojas:
            for produto in produtos:
                estoque, created = Estoque.objects.get_or_create(
                    loja=loja,
                    produto=produto,
                    defaults={
                        "quantidade_atual": quantidade,
                        "quantidade_minima": minimo,
                        "estado": Estoque.EstadoProduto.NORMAL,
                    },
                )

                if created:
                    criados += 1
                    continue

                if options["sobrescrever"]:
                    estoque.quantidade_atual = quantidade
                    estoque.quantidade_minima = minimo
                    estoque.save(
                        update_fields=[
                            "quantidade_atual",
                            "quantidade_minima",
                            "updated_at",
                        ]
                    )
                    atualizados += 1
                else:
                    ignorados += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Estoque inicial processado. "
                f"Criados: {criados}. Atualizados: {atualizados}. Ignorados: {ignorados}."
            )
        )
