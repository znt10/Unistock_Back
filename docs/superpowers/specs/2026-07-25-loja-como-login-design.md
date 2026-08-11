# A loja vira o login (fim do responsável pessoal)

**Data:** 2026-07-25
**Repositórios:** `Unistock_Back` + `Unistock_Front`.

## Contexto

Hoje o acesso de uma loja é uma **pessoa**: cria-se um usuário "Responsável" com
e-mail pessoal e vincula-se manualmente em `Loja.responsavel`. Isso tem dois
problemas na operação real:

1. **Rotatividade.** Quem trabalha na loja entra e sai. Quando a pessoa sai, o
   acesso da loja está preso ao e-mail pessoal dela.
2. **Turnos.** A loja tem turno da manhã (até ~14h) e da tarde (14h às ~20h). Não
   existe "um" responsável — existem várias pessoas na mesma loja ao longo do dia.

A loja já tem **e-mail** e **telefone** próprios (usados pelo digest diário e pelo
bot de WhatsApp). O login natural é a loja, não a pessoa.

## Decisão

**A loja vira o login.** `Loja.responsavel` continua sendo o encanamento do
escopo, mas passa a apontar para um usuário cujo **username/e-mail é o e-mail da
loja**. Ninguém cria "pessoa" à mão.

### Decisões tomadas

| Decisão | Escolha |
|---|---|
| Rastro por pessoa | **Não é necessário.** Basta loja + data/hora — o dono sabe quem estava no turno |
| Senha na criação | **Não.** A loja define no 1º acesso, por link enviado ao e-mail da loja |
| Responsáveis existentes | **Converter** o login para o e-mail da loja (preserva histórico) |
| "Esqueci a senha" | **Incluir agora** — mesmo mecanismo, e sem ele toda perda de senha vira trabalho manual no `/admin` |

### O que "responsável" significa no código (três coisas distintas)

Levantamento feito antes do desenho — 190 ocorrências, mas só uma categoria muda:

| Uso | O que é | Ação |
|---|---|---|
| `Loja.responsavel` | Chave de escopo: *este login enxerga qual loja*. Usado em ~10 lugares (`loja__responsavel`, `user.loja_set`, `Loja.objects.filter(responsavel=user)`) | **Mantém.** Só muda como é criado |
| `Pedido.responsavel`, `ItemPedido.responsavel`, `MovimentacaoEstoque.usuario` | Auditoria: *quem fez*. `PROTECT` | **Mantém.** "Quem" passa a ser a loja |
| Grupo `Responsavel` | Papel/permissão | **Mantém.** Só muda quem ocupa |

Por isso o trabalho é pequeno: o encanamento continua, muda o **fluxo de criação**.

## Frentes de implementação

### 1 · Criar a loja cria o acesso

O formulário de loja **não muda** (já tem e-mail). Muda o que o backend faz ao
criar:

- Em `LojaSerializer.create` (ou serializer de criação dedicado):
  1. Cria `User` com `username = email = Loja.email`, grupo `Responsavel`,
     `is_active=False` e **senha inutilizável** (`set_unusable_password()`).
  2. Vincula em `Loja.responsavel`.
  3. Dispara task Celery que envia ao **e-mail da loja** o link de definir senha.
- Loja criada **sem e-mail** não ganha login (fica como hoje, sem responsável) —
  não é erro, mas a resposta deve deixar claro que não há acesso.
- `Loja.responsavel` deixa de ser escrita pela API: sai do payload aceito
  (read-only no serializer).

### 2 · Definir senha no 1º acesso

Reaproveita o mecanismo de token que já existe em
`app/notifications/tasks.py` (`gerar_token_confirmacao` /
`validar_token_confirmacao` — `django.core.signing`, validade 3 dias).

- **Generalizar** o token: mesmo `dumps/loads`, salt próprio
  (`unistock-definir-senha`).
- **Back:**
  - `POST /api/v1/user/definir-senha/{token}/` com `{"password": "..."}` →
    valida token, `set_password`, `is_active=True`.
  - Validação de senha via `django.contrib.auth.password_validation` (o projeto
    já tem `AUTH_PASSWORD_VALIDATORS` configurado).
  - **Token de uso único (requisito, não opcional):** o payload do token inclui
    um dado derivado da senha atual (ex.: primeiros caracteres de
    `user.password`). Ao definir a senha esse dado muda, então o mesmo link para
    de funcionar. Sem isso, um link vazado continua válido por 3 dias mesmo
    depois de usado.
- **Front:** a tela `/redefinir-senha` **já existe** como casca — ligar de verdade,
  lendo o token da URL.

### 3 · Esqueci a senha

Hoje `/esqueci-senha` é **falsa**: o `handleSubmit` só faz
`router.push("/redefinir-senha")`, sem chamar API.

- **Back:** `POST /api/v1/user/esqueci-senha/` com `{"email": "..."}` → se existir
  usuário ativo com aquele e-mail, dispara o mesmo link de definir senha.
  **Resposta sempre 200**, exista ou não o e-mail (não vazar quais e-mails estão
  cadastrados). Throttle próprio (o projeto já usa `DEFAULT_THROTTLE_RATES`).
- **Front:** ligar a tela existente à API.

### 4 · Migração dos responsáveis atuais

Data migration:

- Para cada `Loja` ativa com `email` preenchido e `responsavel` definido: troca
  `username` e `email` do usuário para o e-mail da loja.
- **Preserva o histórico** — é o mesmo `User`, então `Pedido.responsavel` e
  `MovimentacaoEstoque.usuario` continuam apontando certo.
- Pula (sem falhar) e reporta: loja sem e-mail, loja sem responsável, ou colisão
  de e-mail com usuário existente.
- Não mexe em gerentes/admins.

Depois da migração, as lojas convertidas precisam definir senha nova (fluxo
"esqueci a senha") ou manter a atual — a migração **não** invalida a senha
existente.

### 5 · Limpeza no front

- **Cadastro de usuário:** remover a opção "Responsável" do
  `CadastroUsuarioForm`/`CadastroUsuarioModal`. Criar **Gerente** continua.
- **Edição de loja:** o campo "responsável" vira **somente leitura**, exibindo o
  e-mail de acesso da loja em vez de um seletor de pessoas.

## Casos que quebram silenciosamente (tratar explicitamente)

- **Trocar o e-mail da loja** deve trocar o login junto. Sem isso a loja perde o
  acesso na primeira edição de cadastro. Em `LojaSerializer.update`: se `email`
  mudou e existe `responsavel`, atualizar `username`/`email` do usuário.
- **Duas lojas com o mesmo e-mail** colidem (username é único). Validar no
  serializer: e-mail de loja precisa ser único entre lojas.
- **Loja sem e-mail** não tem login — estado válido, mas precisa ficar visível na
  tela de lojas (senão o usuário não entende por que não consegue entrar).

## Testes

- Criar loja com e-mail → cria `User` inativo, sem senha utilizável, no grupo
  `Responsavel`, vinculado em `Loja.responsavel`, e-mail de definir senha no
  outbox.
- Criar loja **sem** e-mail → nenhum usuário criado, sem erro.
- Criar duas lojas com o mesmo e-mail → 400.
- Definir senha com token válido → senha aplicada, `is_active=True`, login passa
  a funcionar.
- Definir senha com token inválido/expirado → 400.
- Definir senha com senha fraca → 400 (validators do Django).
- **Reusar o mesmo token depois de já ter definido a senha → 400** (uso único).
- Esqueci a senha com e-mail existente → 200 + e-mail no outbox.
- Esqueci a senha com e-mail inexistente → **200 igual**, outbox vazio.
- Trocar o e-mail da loja → o login do responsável acompanha.
- Migração: responsável convertido para o e-mail da loja; pedidos antigos
  continuam apontando para o mesmo usuário; loja sem e-mail é pulada.

## Fora de escopo

- Rastreamento de turno / de qual pessoa operou (decidido: não é necessário).
- Trocar o login de gerentes/admins — continuam pessoais.
- Autenticação por WhatsApp/telefone.
- Refatorar o escopo por `loja__responsavel` (continua como está).

## Riscos / observações

- **Perda de acesso na migração:** se o e-mail da loja estiver errado no
  cadastro, a loja fica sem conseguir recuperar a senha. Conferir os e-mails das
  lojas **antes** de rodar a migração.
- **Uma senha compartilhada entre turnos** é menos segura por natureza (não há
  como saber quem usou). Foi uma decisão consciente do dono: a loja é a unidade
  de responsabilidade, e data/hora bastam para identificar o turno.
- **Envio de e-mail depende do SMTP** já configurado (Gmail, porta 587). Se o
  e-mail não chegar, a loja não define senha — o `/admin` do Django continua como
  saída de emergência.
