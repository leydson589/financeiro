# A dois — finanças da casa

Sistema privado para um casal: contas individuais, painel compartilhado por mês, receitas, despesas, categorias e identificação de quem registrou. Cada pessoa pode excluir seus próprios lançamentos. Não há cadastro público nem integração bancária. Os valores são armazenados em centavos em SQLite, em volume persistente.

## Instalar na VPS

Requisitos: Linux com Docker Engine e Docker Compose, um domínio ou subdomínio apontando para o IP da VPS e portas 80/443 disponíveis. Se já houver proxy reverso na VPS, adapte o serviço Caddy para evitar conflito de portas.

1. Copie esta pasta para a VPS.
2. Copie `.env.example` para `.env`, informe o domínio (sem https://) e gere uma chave com `openssl rand -hex 32`. Cole o resultado em SECRET_KEY. Não compartilhe o arquivo .env.
3. Execute `docker compose up -d --build`.
4. Crie sua conta com `docker compose exec app flask --app app create-user`.
5. Repita o comando para criar a conta da sua mulher. Use senhas diferentes com no mínimo 12 caracteres.
6. Acesse `https://SEU_DOMINIO`. O Caddy emite e renova o certificado HTTPS automaticamente se o DNS e as portas estiverem corretos.

As contas criadas acessam os mesmos dados da família. A criação de contas é exclusiva do terminal da VPS. Senhas são armazenadas com hash PBKDF2-SHA256 com 1 milhão de iterações. Cookies de sessão exigem HTTPS, são HttpOnly e SameSite=Lax, expiram em 12 horas; formulários usam proteção CSRF. Após 8 falhas por e-mail o login fica bloqueado por 15 minutos. A chave deve permanecer estável entre reinicializações. Não ative debug na VPS.

## Backup e restauração

Faça backups frequentes e guarde cópias fora da VPS. A cópia contém os dados financeiros e hashes de senha: mantenha-a privada. Com o serviço pausado, copie o banco:

```sh
docker compose stop app
docker compose cp app:/data/financeiro.db ./backup-financeiro.db
docker compose start app
```

Para restaurar, pare o app, copie o backup para `/data/financeiro.db` usando `docker compose cp ./backup-financeiro.db app:/data/financeiro.db`, corrija a propriedade se necessário (`docker compose run --rm --user root app chown app:app /data/financeiro.db`) e inicie o app. Preserve também o `.env` em local seguro. `docker compose down -v` apaga os volumes e os dados.

## Desenvolvimento local

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export SECRET_KEY="$(openssl rand -hex 32)"
export COOKIE_SECURE=false
.venv/bin/flask --app app create-user
.venv/bin/flask --app app run --host 127.0.0.1
```

Abra http://127.0.0.1:5000. COOKIE_SECURE=false serve apenas para desenvolvimento local. Para executar a verificação automatizada: `.venv/bin/python -m unittest discover -s tests`.

A versão atual inclui edição de lançamentos, contas com saldo inicial, cartões, parcelas, quitação de faturas e despesas recorrentes geradas manualmente. Ainda não inclui recuperação de senha por e-mail, conciliação bancária ou orçamento por categoria. Excluir um lançamento move o registro para a lixeira; o autor pode restaurá-lo. O sistema depende de senhas fortes e da segurança/atualização da VPS. A implantação deve ser validada no servidor de destino.


## Contas, cartões e recorrências

Em **Contas e cartões**, cadastre as contas com o saldo anterior aos lançamentos que pretende registrar. O saldo considera todos os lançamentos vinculados, inclusive futuros. Lançamentos antigos permanecem sem conta vinculada e continuam no painel.

No novo lançamento, escolha uma conta para receitas/despesas diretas ou um cartão para compras. Informe o valor total e o número de parcelas; o sistema distribui os centavos e gera as próximas parcelas. O painel mensal considera o mês da fatura para compras no cartão e a data para lançamentos diretos. A fatura usa o mês do fechamento; compras no dia do fechamento entram na próxima. O dia de vencimento é informativo. O pagamento é registrado manualmente e descontado da conta sem duplicar despesas no painel. Faturas com pagamentos registrados não permitem editar ou excluir suas compras. O histórico de pagamentos fica na mesma tela.

Em **Despesas recorrentes**, cadastre os compromissos e use **Gerar lançamentos** para o mês desejado. A geração é manual, não duplica o mesmo compromisso no mesmo mês e ajusta dias 29–31 em meses curtos. Encerrar a recorrência preserva os lançamentos anteriores. Excluir um lançamento gerado move-o para a lixeira; a geração não recria esse compromisso, evitando duplicatas. Restaure o lançamento pela lixeira. A edição de uma parcela ou recorrência gerada altera somente aquele lançamento.

Para iniciar o ambiente de teste local novamente: `.venv/bin/python run_local.py`. O banco e a chave local são persistidos em `data/`. As contas de teste não são criadas na instalação Docker da VPS.

## Orçamento, metas e relatórios

- **Orçamento:** defina limites por categoria e mês. Salvar novamente o mesmo mês e categoria atualiza o limite. O consumo inclui as despesas diretas do mês e as compras na competência da fatura. Remover um limite preserva os lançamentos.
- **Metas do casal:** cadastre o objetivo, valor e prazo opcional. Cada reserva identifica a pessoa e a data. Reservas são um registro manual de planejamento, sem movimentação de contas ou efeito no resultado mensal. Cada pessoa pode remover suas próprias reservas. Metas podem ser arquivadas e reativadas.
- **Relatórios:** compare os seis meses encerrando no mês escolhido e veja a distribuição de despesas por categoria. Meses sem lançamentos aparecem zerados.
- **Busca e filtros:** o painel permite buscar descrições e filtrar por pessoa, tipo e categoria. Os totais acompanham os filtros; relatórios e orçamentos continuam considerando os dados completos do casal.
- **CSV:** exporte os lançamentos do mês e dos filtros atuais ou o mês completo pela tela de relatórios. O arquivo usa ponto e vírgula, vírgula decimal e UTF-8 com BOM. Textos potencialmente interpretados como fórmulas recebem um apóstrofo de proteção. A exportação exige login e contém informações financeiras privadas.

## Segurança e backup verificado

A tela **Segurança** permite alterar a própria senha, exigindo a senha atual e confirmação da nova (mínimo 12 caracteres). A alteração invalida todas as sessões anteriores da mesma conta. O histórico mostra as últimas 100 ações do casal desde a atualização, com data UTC; não registra senhas, valores ou descrições dos lançamentos. Ele é um acompanhamento de uso, não uma trilha de auditoria imutável.

Para criar um backup consistente com o sistema em funcionamento:

```sh
docker compose exec -e BACKUP_DIRECTORY=/data/backups app flask --app app backup
```

O comando informa o nome exato do arquivo e verifica a integridade SQLite. Copie esse arquivo para um local privado fora da VPS com `docker compose cp app:/data/backups/NOME_DO_ARQUIVO.db ./NOME_DO_ARQUIVO.db`. Backups não são eliminados automaticamente: acompanhe o espaço em disco. O backup contém hashes de senha e dados financeiros, mas não a SECRET_KEY do ambiente. Preserve o `.env` separadamente. O agendamento automático e a cópia externa ainda precisam ser configurados na VPS.

Para backup no ambiente local de teste, sem iniciar outro servidor:

```sh
.venv/bin/python -c 'import run_local; result = run_local.app.test_cli_runner().invoke(args=["backup"]); print(result.output); raise SystemExit(result.exit_code)'
```

## Uso no celular e instalação

A interface adapta navegação, formulários e tabelas para telas pequenas. O aplicativo inclui manifesto, ícones e service worker. No Android/Chrome, use **Instalar aplicativo** no menu ou o botão do rodapé quando o navegador disponibilizar. No iPhone/Safari, use **Compartilhar → Adicionar à Tela de Início**. A instalação no celular depende da publicação em HTTPS na VPS; `localhost` do celular aponta para o próprio celular, não para o computador.

O service worker armazena somente a página pública de orientação sobre falta de conexão. Páginas autenticadas, dados financeiros e formulários não ficam disponíveis offline. Não há fila de salvamentos offline. O aviso de conexão usa o estado informado pelo navegador; ele não garante que o servidor está disponível.

Na edição de lançamentos diretos, é possível vincular ou trocar a conta bancária. Os saldos são recalculados e os lançamentos antigos sem conta permanecem preservados até que uma conta seja escolhida. Compras no cartão continuam vinculadas ao cartão original.


## Lixeira dos lançamentos

Lançamentos excluídos ficam na **Lixeira**, visíveis para o casal, e deixam de compor painel, saldos, orçamentos, relatórios e exportações. Só a pessoa que criou o lançamento pode restaurá-lo. A restauração recalcula os totais e registra uma ação no histórico. Cada parcela é independente. Faturas com pagamento registrado bloqueiam exclusões e restaurações para preservar os valores já pagos.

Não há exclusão definitiva ou remoção automática na lixeira. Os registros continuam no banco e nos backups. Exclusões feitas antes desta atualização não podem ser recuperadas pela nova lixeira. Despesas recorrentes na lixeira não são geradas novamente para o mesmo mês; restaure o registro original.

## Divisão de despesas do casal

Na criação ou edição de uma despesa, selecione **Individual** ou **Compartilhada**, indique quem assumiu o pagamento e, nas compartilhadas, a outra pessoa e a porcentagem do responsável. O restante pertence à outra pessoa. A divisão é aplicada a cada parcela e os centavos são distribuídos sem alterar o total. “Individual” é uma classificação financeira: todos os registros continuam visíveis para o casal.

A tela **Divisão do casal** mostra a estimativa mensal de quanto cada pessoa assumiu, sua responsabilidade e o saldo entre elas. Ela inclui lançamentos futuros e faturas em aberto, não movimenta dinheiro e desconta somente os acertos registrados no sistema para o mês escolhido. Não deve ser tratada como extrato de pagamentos efetivamente realizados. Lançamentos antigos mantêm a classificação existente e podem ser classificados pelo autor na edição, respeitando os bloqueios das faturas pagas. Novas recorrências geradas herdam a classificação configurada na regra. Lançamentos na lixeira ficam fora da divisão.


## Acertos entre o casal

Na tela **Divisão do casal**, registre repasses já realizados, indicando remetente, destinatário, valor, data e observação opcional. O acerto afeta o mês selecionado no resumo, independentemente da data do repasse. O valor é abatido de quem tem a receber e compensado para quem repassou. Não há transporte de saldo entre meses nem alteração de saldos bancários. Repasses acima da dívida estimada podem inverter o saldo.

Quem registrou pode estornar o registro; ele permanece no histórico e deixa de participar do cálculo. A operação não envia ou devolve dinheiro. Acertos aparecem no histórico de segurança e no backup completo, mas não na exportação CSV de lançamentos. Evite registrar o mesmo repasse mais de uma vez.

## Editar e reativar recorrências

A criação de regras recorrentes aceita classificação individual/compartilhada e porcentagens. Os lançamentos gerados herdam a conta e a divisão definidas na regra. Em **Editar regra ou reativar**, o autor pode ajustar descrição, valor, categoria, dia, mês inicial, conta, divisão e estado ativo/encerrado. Isso afeta somente lançamentos ainda não gerados; meses existentes e registros na lixeira são preservados. Não há atualização retroativa nem geração automática em segundo plano. Ao reativar, confira o mês inicial antes de gerar meses anteriores.
