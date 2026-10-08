# IGent

Automação de atendimento no Instagram para lojas e supermercados, com modelos iniciais editáveis no painel.

## Configuração de segurança

Configure no ambiente de execução, nunca no código ou no Git, os valores `SECRET_KEY`, `ADMIN_PASSWORD` e `FACEBOOK_VERIFY_TOKEN`. Use valores aleatórios fortes e exclusivos. O aplicativo não inicia sem `SECRET_KEY`; sem `ADMIN_PASSWORD` o login administrativo fica indisponível, e sem `FACEBOOK_VERIFY_TOKEN` a verificação do webhook retorna erro.

Para integrar os serviços, configure também `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET` e `GEMINI_API_KEY`. Configure `DATABASE_URL` para persistência fora do banco SQLite local. Não envie arquivos `.env`, bancos locais ou tokens ao repositório.

## Configuração do webhook Asaas

O endpoint de notificações é `POST /webhook/asaas`. Configure `ASAAS_WEBHOOK_TOKEN` no ambiente do servidor com um token aleatório seguro (32 a 255 caracteres, sem espaços) e informe o mesmo valor no campo de autenticação do webhook Asaas. O Asaas envia esse valor no cabeçalho `asaas-access-token`.

Selecione os eventos:

- `PAYMENT_CONFIRMED`
- `PAYMENT_RECEIVED`
- `PAYMENT_OVERDUE`

Para que o pagamento seja associado à conta correta, a cobrança deve incluir `externalReference` com o ID da conta profissional do Instagram exibido no painel administrativo. Sem essa referência, o endpoint rejeita o evento com `422` e registra a ocorrência no log da aplicação.

O primeiro evento de confirmação/recebimento concede 30 dias, a partir da validade atual quando ainda houver dias ativos; se já expirou, conta 30 dias a partir do processamento. Os eventos `PAYMENT_CONFIRMED` e `PAYMENT_RECEIVED` da mesma cobrança não concedem períodos duplicados. Uma cobrança vencida suspende o robô, mas um evento de vencimento atrasado não suspende novamente uma cobrança já marcada como paga.

O webhook atualiza a validade e o acesso, mas não cria cobranças nem checkout. A emissão deve usar o `externalReference` descrito acima. As tabelas de idempotência são criadas pelo `db.create_all()` existente na inicialização do aplicativo.

## Modelos por segmento

No primeiro acesso, o cliente seleciona **Loja** ou **Supermercado**. O sistema aplica instruções e respostas iniciais sem inventar preços, estoque ou políticas. É possível trocar o segmento no painel; alterações feitas pelo cliente são preservadas quando se reaplicam modelos.

## Botões de início rápido (Ice Breakers)

Os Ice Breakers podem ser configurados durante o teste grátis enquanto a conta estiver ativa e dentro da validade; não dependem de um pagamento confirmado. A integração usa a permissão `instagram_manage_messages`. Depois de publicar uma versão que solicite essa permissão, clientes já conectados precisam sair e entrar novamente para concedê-la ao novo token. O uso em contas de terceiros também depende da aprovação e do modo de acesso configurado no Meta App Dashboard. A Meta informa que os Ice Breakers não são exibidos no Instagram para desktop; valide a exibição pelo aplicativo móvel.

## Testes

Execute a suíte focada com:

```powershell
python -m unittest discover -s tests
```
