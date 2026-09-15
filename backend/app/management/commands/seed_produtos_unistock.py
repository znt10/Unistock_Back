from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from app.models import Categoria, Conta, Produto


PRODUTOS = {
    "Salgados grande": [
        "Coxinha",
        "Risoles de queijo",
        "Risole presunto e queijo",
        "Bolinho de carne",
        "Kibe",
        "Kibe Queijo",
        "Salsicha",
        "Bolinho ovo",
    ],
    "Salgados mini": [
        "Coxinha",
        "Risoles de queijo",
        "Risole presunto e queijo",
        "Bolinho de carne",
        "Kibe",
        "Kibe Queijo",
    ],
    "Esfihas grande": [
        "Carne",
        "Frango",
        "Bauru",
        "Calabresa",
        "Hamburger",
        "Salsicha com cheddar",
        "Torta de banana",
    ],
    "Esfihas mini": [
        "Carne",
        "Frango",
        "Bauru",
        "Calabresa",
        "Hamburger",
        "Salsicha com cheddar",
        "Torta de banana",
    ],
    "Fogazzas grande": [
        "Presunto e Queijo",
        "2 Queijos",
        "Calabresa",
        "Frango",
        "Pizza",
        "Chocolate",
        "Doce de leite",
    ],
    "Fogazzas mini": [
        "Presunto e Queijo",
        "2 Queijos",
        "Calabresa",
        "Frango",
        "Pizza",
        "Chocolate",
        "Doce de leite",
    ],
    "Recheios": [
        "Açúcar+canela",
        "Bisnaga de chocolate",
        "Bisnaga doce de leite",
        "Bisnaga Beijinho",
        "Calabresa",
        "Carne",
        "Catupiry",
        "Frango",
        "Laranja",
        "Limão",
        "Massa de empada",
        "Massa Pastel",
        "Mussarela",
        "Óleo",
        "Orégano",
        "Ovo",
        "Palmito",
        "Pimenta",
        "Presunto",
        "Tomate",
    ],
    "Mercado": [
        "Açúcar",
        "Café",
        "Detergente",
        "Leite",
        "Nescau",
        "Bombril",
        "Adoçante",
    ],
}


class Command(BaseCommand):
    help = "Cadastra a lista padrao de produtos do UniStock."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limpar",
            action="store_true",
            help="Remove todos os produtos antes de cadastrar a lista padrao.",
        )
        parser.add_argument(
            "--conta",
            help=(
                "Nome ou slug da empresa dona deste catalogo. Se omitido e so "
                "existir uma conta no sistema, usa ela; com zero ou mais de "
                "uma, precisa informar explicitamente."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        conta = self._resolver_conta(options["conta"])

        if options["limpar"]:
            total_removidos, _ = Produto.objects.filter(conta=conta).delete()
            self.stdout.write(f"Registros removidos: {total_removidos}")

        criados = 0
        atualizados = 0

        for indice, (nome_categoria, nomes) in enumerate(PRODUTOS.items()):
            categoria, _ = Categoria.objects.get_or_create(
                nome=nome_categoria, conta=conta, defaults={"ordem": indice}
            )
            for nome in nomes:
                _, created = Produto.objects.update_or_create(
                    nome_produto=nome.strip(),
                    categoria=categoria,
                    defaults={
                        "unidade_medida": Produto.UnidadeMedida.UNIDADE,
                        "quantidade_por_embalagem": None,
                        "estoque_minimo_sugerido": 1,
                        "conta": conta,
                    },
                )

                if created:
                    criados += 1
                else:
                    atualizados += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Produtos cadastrados para {conta.nome}. "
                f"Criados: {criados}. Atualizados: {atualizados}."
            )
        )

    def _resolver_conta(self, identificador):
        if identificador:
            conta = Conta.objects.filter(
                Q(nome__iexact=identificador) | Q(slug=identificador)
            ).first()
            if not conta:
                raise CommandError(f"Nenhuma empresa encontrada: {identificador!r}.")
            return conta

        contas = Conta.objects.all()
        total = contas.count()
        if total == 1:
            return contas.first()
        if total == 0:
            raise CommandError(
                "Nao ha nenhuma empresa cadastrada ainda — crie uma no /admin."
            )
        raise CommandError(
            "Mais de uma empresa cadastrada — informe --conta <nome|slug> pra "
            "dizer de quem e este catalogo."
        )
