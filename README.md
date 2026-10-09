# IGent

Automação de atendimento no Instagram para lojas e supermercados. O IGent conecta uma conta profissional, aplica um modelo inicial e permite configurar respostas automáticas para mensagens diretas e comentários.

Este documento reúne instruções para quem administra e publica o serviço e para os lojistas que usam o painel.

## Visão geral

- Login e autorização do Instagram pelo fluxo OAuth da Meta.
- Teste inicial de 7 dias para novas contas conectadas.
- Modelos iniciais de atendimento para **Loja** e **Supermercado**.
- Regras manuais por palavras ou expressões; essas regras têm prioridade sobre a IA.
- Respostas de fallback pelo Google Gemini, orientadas pela personalidade e pela base de conhecimento cadastradas pelo lojista.
- Até quatro botões Ice Breaker para iniciar conversas no Direct.
- Resposta pública a comentários e envio de mensagem privada quando o comentário encontra uma regra ou resposta da IA.
- Agradecimento configurável a menções da loja em Stories.
- Modo estritamente manual, com respostas somente pelas regras, quando escolhido ou quando a quota mensal de IA do plano Start se esgota.
- Pausa das respostas automáticas por conversa quando o cliente pede atendimento humano, com opção de retomar pelo painel.
- Planos Start, Pro e Enterprise: Start inclui 500 respostas de IA por mês e não inclui Base de Conhecimento; Pro e Enterprise incluem a Base de Conhecimento e não têm limite mensal de respostas de IA.
- Painel administrativo para acompanhar clientes, validade, status e contagem de respostas da IA.

## Configuração e publicação (responsável técnico)

Configure os valores abaixo no ambiente do serviço de hospedagem. Não coloque chaves, tokens, senhas ou arquivos `.env` no código ou no Git.

| Variável | Necessidade | Uso |
| --- | --- | --- |
| `SECRET_KEY` | Obrigatória | Assinatura das sessões do Flask. O aplicativo não inicia sem ela. Use um valor aleatório longo e privado. |
| `ADMIN_PASSWORD` | Obrigatória para usar o admin | Senha do painel administrativo. Sem ela, o login administrativo retorna indisponível. |
| `FACEBOOK_APP_ID` | Obrigatória para conectar contas | ID do aplicativo Meta usado no OAuth. |
| `FACEBOOK_APP_SECRET` | Obrigatória para conectar contas e validar o webhook Meta | Segredo do aplicativo Meta. |
| `FACEBOOK_VERIFY_TOKEN` | Obrigatória para verificar o webhook Meta | Token definido no Meta App Dashboard e usado na verificação `GET /webhook`. |
| `GEMINI_API_KEY` | Necessária para respostas de IA | Chave do Google Gemini. Sem ela, respostas manuais continuam disponíveis, mas não há fallback de IA. |
| `DATABASE_URL` | Recomendada em produção | URI do banco persistente. Sem ela, o SQLAlchemy usa SQLite local; armazenamento efêmero da hospedagem pode perder dados ao reiniciar. PostgreSQL é suportado. |
| `ASAAS_WEBHOOK_TOKEN` | Necessária se usar notificações Asaas | Token validado no cabeçalho `asaas-access-token` em `POST /webhook/asaas`. |
| `PORT` | Conforme a hospedagem | Porta usada quando o arquivo é iniciado diretamente. A hospedagem pode fornecer esse valor automaticamente. |
| `RENDER` | Automática no Render | Ativa a flag `Secure` do cookie da sessão quando presente. |

### Integração Meta

O endereço de callback está definido no código como `https://bot-instagram-bcjd.onrender.com/callback`. O domínio publicado e o URI de redirecionamento cadastrado no Meta App Dashboard devem corresponder; se a aplicação mudar de domínio, atualize também `REDIRECT_URI` em `app.py` e a configuração na Meta.

O OAuth solicita as permissões `pages_show_list`, `instagram_basic`, `instagram_manage_comments`, `instagram_manage_messages`, `pages_messaging`, `pages_read_engagement` e `pages_manage_metadata`. A inscrição do webhook inclui `mentions`, `messages`, `comments` e `messaging_postbacks`. A conexão depende de uma página Facebook com uma conta profissional do Instagram vinculada, das permissões liberadas para o aplicativo e das aprovações/modos de acesso configurados na Meta.

O webhook Meta é `GET/POST /webhook`. Configure `FACEBOOK_VERIFY_TOKEN` para a verificação e `FACEBOOK_APP_SECRET` para que as requisições POST sejam aceitas com assinatura válida.

### Banco de dados

O aplicativo chama `db.create_all()` na inicialização para criar tabelas ausentes. Isso não substitui backups e não aplica migrações estruturais a tabelas existentes. Em produção, use um banco persistente e mantenha cópias de segurança.

### Webhook de pagamentos Asaas

O endpoint de notificações é `POST /webhook/asaas`. Configure `ASAAS_WEBHOOK_TOKEN` no ambiente do servidor com um token aleatório seguro (32 a 255 caracteres, sem espaços) e informe o mesmo valor na autenticação do webhook Asaas. O Asaas envia esse valor no cabeçalho `asaas-access-token`.

Selecione os eventos:

- `PAYMENT_CONFIRMED`
- `PAYMENT_RECEIVED`
- `PAYMENT_OVERDUE`

Para associar a cobrança à conta correta, inclua `externalReference` com o ID profissional do Instagram do cliente. O endpoint rejeita eventos sem essa referência ou com cliente inexistente. Eventos confirmados/recebidos concedem 30 dias uma única vez por cobrança; a validade é prolongada a partir da data atual de expiração quando ainda está ativa. Um evento de vencimento suspende o robô, mas não anula uma cobrança que já foi marcada como paga.

**Limitação atual:** o webhook atualiza a validade e o acesso, mas não cria cobranças nem checkout. Embora o painel do lojista exiba uma seção e um formulário de pagamento, esta versão não implementa a rota `/pagar`; o botão de gerar fatura não conclui a cobrança. A emissão deve ser feita por um fluxo externo que envie ao Asaas o `externalReference` correto. Não anuncie o checkout como funcional até implementar e validar essa rota.

## Instruções para o lojista (cliente)

### Conectar e começar

1. Abra a página inicial e escolha **Conectar Instagram**.
2. Autorize o aplicativo Meta e selecione a conta profissional vinculada à página Facebook.
3. No primeiro acesso, escolha **Loja** ou **Supermercado**. O modelo cria sugestões que podem ser editadas.
4. Abra o painel e revise as respostas antes de ativar o atendimento com clientes reais.

Novas contas recebem um teste inicial de 7 dias. O funcionamento também depende da autorização e da disponibilidade dos serviços Meta e Google.

### Configurar respostas

**Regras manuais:** informe palavras ou expressões que possam aparecer na pergunta e escreva a resposta correspondente. Quando uma regra coincidir, ela é usada antes da IA e não consome Gemini. Inclua variações comuns (por exemplo, “preço”, “valor” e “quanto custa”) e confirme que a resposta continua correta após mudanças no negócio.

**Personalidade e instruções da IA:** descreva o tom de voz, como cumprimentar e como a equipe deve lidar com situações específicas. A instrução não deve contrariar os dados reais cadastrados na base de conhecimento.

**Base de Conhecimento da Loja:**

- Preencha o link completo do catálogo ou site oficial, incluindo `https://`.
- Em **Preços, horários e regras de entrega**, escreva os fatos que a IA pode informar: produtos, valores, horários, regiões atendidas, frete, políticas e restrições.
- Atualize esses dados sempre que mudarem. A IA não verifica automaticamente o estoque ou se um preço ainda está vigente.
- O sistema inclui o endereço do catálogo no prompt para que a IA possa compartilhá-lo quando perguntarem por produtos. **O sistema não abre nem importa o conteúdo do site**: cadastre também, no campo de dados extras, os produtos e as informações que a IA precisa conhecer.
- Se um dado não estiver cadastrado, a orientação da IA é não inventar e informar que a equipe poderá confirmar.

**Botões de início rápido:** configure até quatro perguntas para iniciar conversas no Direct. Crie regras de resposta correspondentes a essas perguntas para dar respostas determinísticas. A integração usa `instagram_manage_messages`; contas já conectadas podem precisar sair e entrar novamente após uma nova permissão ser adicionada. Os botões Ice Breaker não são exibidos no Instagram para desktop; valide pelo aplicativo móvel.

**Menções em Stories:** com a opção de agradecimento ligada, o robô envia a mensagem configurada quando o webhook Meta entrega um evento de menção de Story compatível. O recebimento depende da inscrição e das permissões de webhook da Meta.

**Comentários e atendimento humano:** quando um comentário encontra uma regra ou resposta da IA, o sistema publica a mensagem configurada (use `{nome}` para mencionar o usuário) e envia uma resposta privada. Se alguém pedir para falar com um atendente — por exemplo, usando “atendente”, “humano”, “suporte” ou “falar com alguém” — a automação pausa para aquela conversa até que a equipe a retome no painel. A detecção automática de respostas manuais enviadas pelo lojista não está disponível; a Meta não fornece aqui um evento confiável para acionar essa pausa.

**Permissões de resposta:** no topo das configurações, desative separadamente as respostas no Direct ou nos comentários. Cada opção desligada faz o webhook ignorar aquele tipo de evento; contas existentes sem essas opções salvas continuam com ambos os módulos ligados.

**Modo manual e planos:** o modo estritamente manual pode ser ligado no painel e faz o robô usar somente as regras cadastradas quando a mensagem inteira corresponde a uma palavra ou expressão de gatilho (ignorando maiúsculas, acentos e pontuação ao comparar). Todo teste novo começa no plano Start: até 500 respostas Gemini aceites por mês-calendário e sem acesso à Base de Conhecimento. Ao atingir a quota, apenas regras com correspondência da mensagem inteira continuam ativas até o início do próximo mês. Clientes legados e renovações administrativas existentes permanecem no Pro; eventos de pagamento Asaas confirmados também atribuem Pro. O administrador pode definir Start, Pro ou Enterprise individualmente no painel admin. Pro e Enterprise não têm quota mensal de IA e podem usar a Base de Conhecimento. A Base de Conhecimento de clientes Start é preservada, mas não é enviada ao Gemini nem pode ser editada até a mudança para Pro ou Enterprise.

O painel só permite salvar configurações quando a conta está ativa e dentro da validade. Se o acesso estiver suspenso ou vencido, fale com a equipe responsável.

## Instruções para você (administrador)

### Abrir o painel

Acesse `https://<seu-dominio>/painel-adm` e entre com `ADMIN_PASSWORD`. A rota antiga `/admin` não existe e retorna 404. O login, logout e as ações de renovar, bloquear/desbloquear e excluir também ficam sob `/painel-adm`.

O caminho menos óbvio é apenas uma camada adicional de discrição: **não substitui a senha**, autenticação, atualização de dependências ou outras medidas de segurança. Mantenha `ADMIN_PASSWORD` forte, privada e configurada no provedor de hospedagem. Não divulgue o endereço do painel para clientes.

### Interpretar o painel

- **Total de Clientes:** número de registros de clientes.
- **Robôs Ativos:** número de clientes cujo indicador de atividade está ligado; verifique também validade e rótulo de status.
- **Consumo API (Gemini):** soma dos contadores armazenados em `config_json`.
- **Uso IA:** contador individual acumulado mostrado para cada cliente.
- **Quota mensal:** o Start mostra também o total de respostas Gemini do mês atual, com limite de 500.
- **Plano:** o seletor na tabela atribui Start, Pro ou Enterprise e define o limite de IA e o acesso à Base de Conhecimento.
- **Validade e Status:** ajudam a identificar contas ativas, vencidas ou bloqueadas.
- **+30 Dias:** renova manualmente a validade por 30 dias e reativa a conta.
- **Bloquear/Desbloquear:** alterna o indicador de atividade da conta.
- **Excluir:** remove permanentemente o registro do cliente; confirme a identidade antes de usar.

O contador acumulado aumenta uma vez quando o Gemini retorna uma resposta não vazia que o fluxo aceita para envio, inclusive em respostas privadas a comentários. Regras manuais não aumentam os contadores. Se o Gemini falhar sem gerar resposta, não há incremento. O uso mensal do Start é separado e reinicia por mês-calendário; o contador acumulado permanece disponível no admin e **não é um extrato de faturamento da Google**. Ele conta respostas aceites pela aplicação, não tokens ou cobranças monetárias.

### Proteção e cuidados operacionais

- `/painel-adm` foi escolhido como caminho administrativo, mas caminhos curtos ou previsíveis podem ser descobertos. A senha administrativa continua sendo necessária.
- A ação de excluir não pode ser desfeita pelo painel; mantenha backups do banco.
- Confira a validade e os dados de cobrança antes de renovar ou bloquear manualmente.
- A autorização, entrega de mensagens e Ice Breakers dependem das permissões e políticas da Meta. Falhas externas devem ser conferidas nos logs do serviço e no painel da Meta.
- Não use uma resposta manual para preço, disponibilidade ou política que não esteja atualizada.

## Rotas principais

| Rota | Uso |
| --- | --- |
| `/` | Página pública |
| `/login` e `/callback` | Início e retorno do OAuth Meta |
| `/onboarding` | Escolha do modelo Loja/Supermercado |
| `/dashboard` | Configuração do lojista |
| `/dashboard/retomar-atendimento` | Retomar automação de uma conversa pausada |
| `/painel-adm` | Login e painel administrativo |
| `/painel-adm/login` | Envio do login administrativo |
| `/painel-adm/logout` | Encerrar sessão administrativa |
| `/webhook` | Verificação e eventos da Meta |
| `/webhook/asaas` | Notificações de pagamento Asaas |
| `/termos` e `/privacidade` | Páginas legais |

## Desenvolvimento e testes

Instale as dependências declaradas em `requirements.txt`. O aplicativo requer `SECRET_KEY` para iniciar; configure também as variáveis necessárias ao fluxo que pretende executar.

Para executar a suíte, se a pasta local `tests/` estiver disponível:

```powershell
python -m unittest discover -s tests
```

A pasta `tests/` é ignorada pelo Git neste repositório e pode não estar presente em um clone.
