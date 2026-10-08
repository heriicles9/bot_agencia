import os
import copy
import hashlib
import hmac
import requests
import unicodedata
from datetime import datetime, timedelta
from flask import Flask, request, redirect, session, render_template, make_response
from requests_oauthlib import OAuth2Session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.exc import IntegrityError
from werkzeug.middleware.proxy_fix import ProxyFix

# NOVO SDK DO GOOGLE GEMINI
from google import genai

# --- CONFIGURAÇÕES ---
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.config['SESSION_COOKIE_NAME'] = 'instagram_bot_session'
app.config['SESSION_COOKIE_SECURE'] = os.getenv("RENDER") is not None
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY precisa estar configurada.")
app.secret_key = SECRET_KEY
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# --- CONFIGURAÇÃO DO NOVO GOOGLE GEMINI (IA) ---
GENAI_KEY = os.getenv("GEMINI_API_KEY")
gemini_client = None
if GENAI_KEY:
    gemini_client = genai.Client(api_key=GENAI_KEY)

# FACEBOOK / META
CLIENT_ID = os.getenv("FACEBOOK_APP_ID")
CLIENT_SECRET = os.getenv("FACEBOOK_APP_SECRET")
REDIRECT_URI = "https://bot-instagram-bcjd.onrender.com/callback"
AUTHORIZATION_BASE_URL = 'https://www.facebook.com/dialog/oauth'
TOKEN_URL = 'https://graph.facebook.com/oauth/access_token'
SCOPE = ['pages_show_list', 'instagram_basic', 'instagram_manage_comments', 'instagram_manage_messages', 'pages_messaging', 'pages_read_engagement', 'pages_manage_metadata']

# BANCO DE DADOS (FORÇANDO O DRIVER PSYCOPG2)
db_url = os.getenv("DATABASE_URL", "")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+psycopg2://", 1)
elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+psycopg2://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = (
    {"connect_args": {"sslmode": "require"}} if db_url.startswith("postgresql") else {}
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
VERIFY_TOKEN = os.getenv("FACEBOOK_VERIFY_TOKEN")
ASAAS_WEBHOOK_TOKEN = os.getenv("ASAAS_WEBHOOK_TOKEN", "")

DEFAULT_CONFIG = {
    "msg_padrao": "Você é um assistente virtual útil. Responda de forma curta.",
    "msg_comentario_publico": "Oi {nome}! Te chamei no direct.",
    "fluxos": [{"gatilhos": "preço", "resposta": "R$ 99,00"}],
}

MODELOS_POR_SEGMENTO = {
    "loja": {
        "nome": "Loja",
        "msg_padrao": (
            "Você é o atendente virtual de uma loja. Seja simpático, direto e adapte o tom "
            "à marca. Responda apenas com informações fornecidas pelo negócio; não invente "
            "preços, estoque, prazos ou políticas. Se faltar informação, pergunte o produto, "
            "modelo ou variação e informe que a equipe pode confirmar."
        ),
        "fluxos": [
            {
                "gatilhos": "preço, valor, quanto custa",
                "resposta": "Qual produto ou modelo você procura? A equipe confirma o preço atualizado.",
            },
            {
                "gatilhos": "entrega, frete, entrega aqui",
                "resposta": "Me envie o produto e seu CEP para a equipe confirmar prazo e frete.",
            },
            {
                "gatilhos": "horário, abre, funciona",
                "resposta": "Qual dia você pretende visitar? A equipe confirma o horário da loja.",
            },
        ],
    },
    "supermercado": {
        "nome": "Supermercado",
        "msg_padrao": (
            "Você é o atendente virtual de um supermercado. Seja simpático, direto e adapte "
            "o tom à marca. Responda apenas com informações fornecidas pelo negócio; não "
            "invente preços, ofertas, estoque, prazos ou políticas. Se faltar informação, "
            "pergunte o produto, marca ou unidade e informe que a equipe pode confirmar."
        ),
        "fluxos": [
            {
                "gatilhos": "encarte, ofertas, promoção, desconto",
                "resposta": "Qual produto ou categoria procura? A equipe confirma as ofertas vigentes.",
            },
            {
                "gatilhos": "entrega, frete, entrega aqui",
                "resposta": "Me envie seu bairro ou CEP para a equipe confirmar as opções de entrega.",
            },
            {
                "gatilhos": "horário, abre, funciona",
                "resposta": "Qual unidade e dia você quer consultar? A equipe confirma o horário.",
            },
        ],
    },
}

# --- MODELO DO CLIENTE ---
class Cliente(db.Model):
    __tablename__ = 'clientes'
    id = db.Column(db.String(50), primary_key=True)
    nome = db.Column(db.String(100))
    token = db.Column(db.String(300))
    plano = db.Column(db.String(20))
    config_json = db.Column(JSON)
    data_expiracao = db.Column(db.DateTime)
    ativo = db.Column(db.Boolean, default=True)

    def __init__(self, id, nome, token, plano, config_json, data_expiracao):
        self.id = id
        self.nome = nome
        self.token = token
        self.plano = plano
        self.config_json = config_json
        self.data_expiracao = data_expiracao
        self.ativo = True


class AsaasEvento(db.Model):
    __tablename__ = 'asaas_eventos'

    id = db.Column(db.String(120), primary_key=True)
    tipo = db.Column(db.String(60), nullable=False)
    pagamento_id = db.Column(db.String(100), nullable=False)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.now)


class AsaasPagamento(db.Model):
    __tablename__ = 'asaas_pagamentos'

    id = db.Column(db.String(100), primary_key=True)
    cliente_id = db.Column(db.String(50), db.ForeignKey('clientes.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    periodo_concedido = db.Column(db.Boolean, nullable=False, default=False)
    atualizado_em = db.Column(db.DateTime, nullable=False, default=datetime.now)


with app.app_context():
    db.create_all()

mensagens_processadas = set()

# --- FUNÇÕES AUXILIARES ---
def verificar_assinatura(cliente):
    if not cliente.ativo: return False
    if cliente.data_expiracao and datetime.now() > cliente.data_expiracao: return False
    return True


def aplicar_modelo_segmento(configuracao, segmento):
    modelo = MODELOS_POR_SEGMENTO.get(segmento)
    if not modelo:
        raise ValueError("Segmento inválido.")

    config = copy.deepcopy(configuracao) if isinstance(configuracao, dict) else {}
    modelo_anterior = config.get("_modelo_base", {})
    padroes_novos = {
        "msg_padrao": modelo["msg_padrao"],
        "fluxos": modelo["fluxos"],
        "msg_comentario_publico": DEFAULT_CONFIG["msg_comentario_publico"],
    }

    for campo, padrao_novo in padroes_novos.items():
        valor_atual = config.get(campo)
        era_padrao = valor_atual == modelo_anterior.get(campo)
        era_padrao_antigo = valor_atual == DEFAULT_CONFIG.get(campo)
        if not valor_atual or era_padrao or era_padrao_antigo:
            config[campo] = copy.deepcopy(padrao_novo)

    config["segmento"] = segmento
    config["_modelo_base"] = copy.deepcopy(padroes_novos)
    return config


# --- INTEGRAÇÃO COM OS BOTÕES INICIAIS DO INSTAGRAM ---
def atualizar_ice_breakers(token, perguntas):
    call_to_actions = [
        {"question": pergunta, "payload": pergunta}
        for pergunta in perguntas
        if pergunta.strip()
    ][:4]
    url = "https://graph.facebook.com/v18.0/me/messenger_profile"
    parametros = {"access_token": token, "platform": "instagram"}

    if not call_to_actions:
        resposta = requests.delete(
            url,
            params=parametros,
            json={"fields": ["ice_breakers"]},
            timeout=10,
        )
    else:
        resposta = requests.post(
            url,
            params=parametros,
            json={
                "platform": "instagram",
                "ice_breakers": [
                    {"call_to_actions": call_to_actions, "locale": "default"}
                ],
            },
            timeout=10,
        )

    resposta.raise_for_status()


# --- ROTAS ---
@app.route("/")
def index():
    return render_template("index.html", conectado=bool(session.get("user_id")))

@app.route("/login")
def login():
    session.permanent = True
    facebook = OAuth2Session(CLIENT_ID, redirect_uri=REDIRECT_URI, scope=SCOPE)
    authorization_url, state = facebook.authorization_url(AUTHORIZATION_BASE_URL)
    session['oauth_state'] = state
    return redirect(authorization_url)

@app.route("/callback")
def callback():
    try:
        estado_session = session.get('oauth_state')
        estado_url = request.args.get('state')
        estado_final = estado_session if estado_session else estado_url

        facebook = OAuth2Session(CLIENT_ID, state=estado_final, redirect_uri=REDIRECT_URI)
        token = facebook.fetch_token(TOKEN_URL, client_secret=CLIENT_SECRET, authorization_response=request.url)
        user_token = token['access_token']

        r = requests.get(f"https://graph.facebook.com/v18.0/me/accounts?access_token={user_token}")
        paginas = r.json().get('data', [])
        if not paginas: return "❌ Nenhuma página encontrada."

        pagina = paginas[0]
        r_insta = requests.get(f"https://graph.facebook.com/v18.0/{pagina['id']}?fields=instagram_business_account&access_token={pagina['access_token']}")
        insta_data = r_insta.json().get('instagram_business_account')
        if not insta_data: return "❌ Página sem Instagram vinculado."

        requests.post(f"https://graph.facebook.com/v18.0/{pagina['id']}/subscribed_apps", data={"subscribed_fields": "feed,mentions,messages,messaging_postbacks,comments", "access_token": pagina['access_token']})

        cliente_existente = db.session.get(Cliente, insta_data['id'])

        if cliente_existente:
            cliente_existente.token = pagina['access_token']
            cliente_existente.nome = pagina['name']
            db.session.commit()
        else:
            validade_teste = datetime.now() + timedelta(days=7)
            config_padrao = copy.deepcopy(DEFAULT_CONFIG)
            config_padrao["segmento"] = None
            novo_cliente = Cliente(insta_data['id'], pagina['name'], pagina['access_token'], "teste_gratis", config_padrao, validade_teste)
            db.session.add(novo_cliente)
            db.session.commit()

        session['user_id'] = insta_data['id']
        return redirect("/dashboard")

    except Exception as e:
        return f"Erro: {e}"

@app.route("/onboarding", methods=['GET', 'POST'])
def onboarding():
    user_id = session.get('user_id')
    if not user_id:
        return redirect("/login")

    cliente = db.session.get(Cliente, user_id)
    if not cliente:
        return redirect("/login")

    erro = ""
    if request.method == 'POST':
        segmento = request.form.get("segmento", "")
        if segmento not in MODELOS_POR_SEGMENTO:
            erro = "Escolha Loja ou Supermercado para continuar."
        else:
            try:
                cliente.config_json = aplicar_modelo_segmento(cliente.config_json, segmento)
                db.session.commit()
                return redirect("/dashboard")
            except Exception:
                db.session.rollback()
                app.logger.exception("Falha ao aplicar o modelo inicial para cliente %s", cliente.id)
                erro = "Não foi possível salvar o modelo. Tente novamente."

    return render_template("onboarding.html", cliente_nome=cliente.nome, erro=erro)

@app.route("/dashboard", methods=['GET', 'POST'])
def dashboard():
    user_id = session.get('user_id')
    if not user_id: return redirect("/login")
    cliente = db.session.get(Cliente, user_id)
    if not cliente: return redirect("/login")

    config_cliente = cliente.config_json if isinstance(cliente.config_json, dict) else {}
    if config_cliente.get("segmento") not in MODELOS_POR_SEGMENTO:
        return redirect("/onboarding")
    if not isinstance(config_cliente.get("pausados"), list):
        config_cliente = dict(config_cliente)
        config_cliente["pausados"] = []

    agora = datetime.now()
    dias_restantes = (
        (cliente.data_expiracao - agora).days if cliente.data_expiracao else 0
    )
    conta_vencida = bool(cliente.data_expiracao and cliente.data_expiracao < agora)
    acesso_bloqueado = not verificar_assinatura(cliente)

    mensagem = ""
    if request.method == 'POST':
        if acesso_bloqueado:
            mensagem = "❌ Seu acesso está pausado. Regularize a conta antes de salvar."
        else:
            gatilhos_list = request.form.getlist('gatilhos[]')
            respostas_list = request.form.getlist('respostas[]')

            config_atual = dict(config_cliente)
            config_atual['msg_padrao'] = request.form.get('msg_padrao')
            config_atual['msg_comentario_publico'] = request.form.get('msg_comentario_publico')

            novos_fluxos = []
            for i in range(len(gatilhos_list)):
                if gatilhos_list[i].strip():
                    novos_fluxos.append({"gatilhos": gatilhos_list[i], "resposta": respostas_list[i]})

            config_atual['fluxos'] = novos_fluxos
            perguntas_iniciais = request.form.getlist('ice_breakers[]')
            perguntas_validas = [
                pergunta.strip()
                for pergunta in perguntas_iniciais
                if pergunta.strip()
            ][:4]
            config_atual['ice_breakers'] = perguntas_validas
            cliente.config_json = config_atual

            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                app.logger.exception("Falha ao salvar configurações do cliente %s.", cliente.id)
                mensagem = "❌ Erro ao salvar configurações."
            else:
                try:
                    atualizar_ice_breakers(cliente.token, perguntas_validas)
                except requests.RequestException as erro:
                    status = erro.response.status_code if erro.response is not None else "sem resposta"
                    app.logger.warning(
                        "Falha ao sincronizar Ice Breakers com a Meta para o cliente %s (status: %s).",
                        cliente.id,
                        status,
                    )
                    mensagem = "❌ Configurações salvas, mas não foi possível atualizar os botões no Instagram. Tente novamente."
                else:
                    mensagem = "✅ Configurações salvas!"

    config_cliente = cliente.config_json if isinstance(cliente.config_json, dict) else {}
    data_formatada = (
        cliente.data_expiracao.strftime("%d/%m/%Y")
        if cliente.data_expiracao
        else "Não definida"
    )
    return render_template("dashboard.html",
                           config=config_cliente,
                           cliente_nome=cliente.nome,
                           segmento=MODELOS_POR_SEGMENTO[config_cliente["segmento"]]["nome"],
                           mensagem_sucesso=mensagem,
                           vencida=conta_vencida,
                           acesso_bloqueado=acesso_bloqueado,
                           pausada=not cliente.ativo,
                           validade=data_formatada,
                           dias_restantes=dias_restantes)

@app.route("/dashboard/retomar-atendimento", methods=["POST"])
def retomar_atendimento():
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/login")

    cliente = db.session.get(Cliente, user_id)
    if not cliente:
        return redirect("/login")

    sender_id = request.form.get("sender_id", "").strip()
    if not sender_id:
        return "Identificador de conversa inválido.", 400

    config = (
        dict(cliente.config_json)
        if isinstance(cliente.config_json, dict)
        else {}
    )
    pausados = config.get("pausados", [])
    if not isinstance(pausados, list) or sender_id not in pausados:
        return redirect("/dashboard")

    config["pausados"] = [pausado for pausado in pausados if pausado != sender_id]
    cliente.config_json = config
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception(
            "Falha ao retomar automação para a conversa %s do cliente %s.",
            sender_id,
            cliente.id,
        )
        return "Não foi possível retomar a automação.", 500

    return redirect("/dashboard")

@app.route("/modelos")
def listar_modelos():
    try:
        if not gemini_client: return "❌ Chave GEMINI_API_KEY não configurada corretamente."

        resultado = "<h3>🤖 Modelos Disponíveis na sua Conta (Novo SDK):</h3><ul>"
        for m in gemini_client.models.list():
            resultado += f"<li><b>Nome:</b> {m.name}</li>"

        resultado += "</ul>"
        return resultado
    except Exception as e:
        return f"❌ Erro ao listar: {e}"

@app.route("/termos")
def termos():
    return render_template("termos.html")


@app.route("/privacidade")
def privacidade():
    return render_template("privacidade.html")


@app.route("/admin")
def admin_panel():
    if not session.get('admin_logged_in'): return render_template("admin_login.html")
    todos_clientes = Cliente.query.all()
    return render_template("admin_dashboard.html", clientes=todos_clientes, hoje=datetime.now())

@app.route("/admin/login", methods=['POST'])
def admin_login():
    if not ADMIN_PASSWORD:
        app.logger.error("ADMIN_PASSWORD não está configurado.")
        return "Login administrativo não configurado.", 503
    if request.form.get('senha') == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        return redirect("/admin")
    return "❌ Senha incorreta."

@app.route("/admin/renovar/<id>")
def admin_renovar(id):
    if not session.get('admin_logged_in'): return redirect("/admin")
    cliente = db.session.get(Cliente, id)
    if cliente:
        cliente.data_expiracao = datetime.now() + timedelta(days=30)
        cliente.ativo = True
        cliente.plano = "renovado_manual"
        db.session.commit()
    return redirect("/admin")

@app.route("/admin/toggle_status/<id>")
def admin_toggle(id):
    if not session.get('admin_logged_in'): return redirect("/admin")
    cliente = db.session.get(Cliente, id)
    if cliente:
        cliente.ativo = not cliente.ativo
        db.session.commit()
    return redirect("/admin")

@app.route("/admin/excluir/<id>", methods=['POST'])
def admin_excluir(id):
    if not session.get('admin_logged_in'): return redirect("/admin")
    cliente = db.session.get(Cliente, id)
    if cliente:
        db.session.delete(cliente)
        db.session.commit()
    return redirect("/admin")

@app.route("/logout")
def logout():
    session.clear()
    resposta = make_response(redirect("/"))
    resposta.set_cookie('instagram_bot_session', '', expires=0)
    return resposta

@app.route("/webhook/asaas", methods=['POST'])
def webhook_asaas():
    if not ASAAS_WEBHOOK_TOKEN:
        app.logger.error("ASAAS_WEBHOOK_TOKEN não está configurado.")
        return "Webhook Asaas não configurado.", 503

    token_recebido = request.headers.get("asaas-access-token", "")
    if not hmac.compare_digest(token_recebido, ASAAS_WEBHOOK_TOKEN):
        return "Não autorizado.", 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return "Payload JSON inválido.", 400

    evento_id = payload.get("id")
    tipo_evento = payload.get("event")
    pagamento = payload.get("payment")
    if not isinstance(evento_id, str) or not evento_id or not isinstance(tipo_evento, str):
        return "Identificador ou tipo de evento inválido.", 400

    eventos_pagos = {"PAYMENT_CONFIRMED", "PAYMENT_RECEIVED"}
    eventos_vencidos = {"PAYMENT_OVERDUE"}
    if tipo_evento not in eventos_pagos | eventos_vencidos:
        return {"received": True, "ignored": True}, 200

    if not isinstance(pagamento, dict):
        return "Dados da cobrança inválidos.", 400

    pagamento_id = pagamento.get("id")
    referencia_cliente = pagamento.get("externalReference")
    if not isinstance(pagamento_id, str) or not pagamento_id:
        return "Identificador da cobrança inválido.", 400
    if not isinstance(referencia_cliente, str) or not referencia_cliente:
        app.logger.error("Cobrança Asaas %s sem externalReference de cliente.", pagamento_id)
        return "A cobrança precisa informar externalReference com o ID do cliente.", 422

    cliente = db.session.get(Cliente, referencia_cliente)
    if not cliente:
        app.logger.error(
            "Cobrança Asaas %s referencia cliente inexistente: %s",
            pagamento_id,
            referencia_cliente,
        )
        return "Cliente da cobrança não encontrado.", 422

    if db.session.get(AsaasEvento, evento_id):
        return {"received": True, "duplicate": True}, 200

    try:
        registro_pagamento = db.session.get(AsaasPagamento, pagamento_id)
        if registro_pagamento and registro_pagamento.cliente_id != cliente.id:
            app.logger.error(
                "Cobrança Asaas %s associada a mais de um cliente.",
                pagamento_id,
            )
            return "A cobrança está associada a outro cliente.", 409
        if not registro_pagamento:
            registro_pagamento = AsaasPagamento(
                id=pagamento_id,
                cliente_id=cliente.id,
                status="PENDING",
                periodo_concedido=False,
            )
            db.session.add(registro_pagamento)

        db.session.add(AsaasEvento(id=evento_id, tipo=tipo_evento, pagamento_id=pagamento_id))

        if tipo_evento in eventos_pagos:
            if not registro_pagamento.periodo_concedido:
                agora = datetime.now()
                inicio_periodo = cliente.data_expiracao
                if not inicio_periodo or inicio_periodo < agora:
                    inicio_periodo = agora
                cliente.data_expiracao = inicio_periodo + timedelta(days=30)
                registro_pagamento.periodo_concedido = True
            registro_pagamento.status = "PAID"
            cliente.ativo = True
        elif registro_pagamento.status != "PAID":
            registro_pagamento.status = "OVERDUE"
            cliente.ativo = False

        registro_pagamento.atualizado_em = datetime.now()
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if db.session.get(AsaasEvento, evento_id):
            return {"received": True, "duplicate": True}, 200
        app.logger.exception("Falha de integridade ao processar evento Asaas %s.", evento_id)
        return "Não foi possível registrar o evento.", 500
    except Exception:
        db.session.rollback()
        app.logger.exception("Falha ao processar evento Asaas %s.", evento_id)
        return "Não foi possível processar o evento.", 500

    return {"received": True}, 200

# --- WEBHOOK & LÓGICA IA (ATUALIZADA PARA O NOVO SDK GEMINI) ---

def consultar_gemini(persona_loja, pergunta_cliente):
    pergunta_segura = pergunta_cliente[:250]

    try:
        if not gemini_client:
            print("⚠️ ERRO: Cliente do Gemini não configurado (Verifique a GEMINI_API_KEY)!")
            return None

        prompt_sistema = f"""
        Você é um atendente virtual.
        SUAS INSTRUÇÕES: {persona_loja}
        CLIENTE: "{pergunta_segura}"

        REGRA RÍGIDA: Responda em APENAS 1 frase curta (máximo 15 palavras). Seja direto e nunca saia do personagem.
        """

        # O modelo recomendado para automações rápidas e gratuitas
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt_sistema
        )
        return response.text.strip()
    except Exception as e:
        print(f"❌ ERRO CRÍTICO NO GEMINI: {e}")
        return None

def encontrar_resposta(texto, cliente):
    config = cliente.config_json
    fluxos = config.get('fluxos', [])

    for regra in fluxos:
        gatilhos = [p.strip().lower() for p in regra['gatilhos'].split(',')]
        if any(p in texto for p in gatilhos):
            return regra['resposta']

    persona = config.get('msg_padrao')
    if persona and len(persona) > 5:
        return consultar_gemini(persona, texto)

    return None

def processar_mensagem(event, cliente):
    sender_id = event.get('sender', {}).get('id')
    mensagem = event.get('message') or {}
    postback = event.get('postback') or {}
    texto = (mensagem.get('text') or postback.get('payload') or postback.get('title') or '').lower()
    evento_id = mensagem.get('mid') or event.get('timestamp')
    msg_id = f"{sender_id}:{evento_id}" if sender_id and evento_id is not None else None

    if not sender_id or sender_id == cliente.id or mensagem.get('is_echo') or not texto:
        return
    if msg_id is not None and msg_id in mensagens_processadas:
        return

    config = (
        dict(cliente.config_json)
        if isinstance(cliente.config_json, dict)
        else {}
    )
    pausados = config.get('pausados', [])
    if not isinstance(pausados, list):
        pausados = []

    if sender_id in pausados:
        return

    texto_normalizado = ''.join(
        caractere
        for caractere in unicodedata.normalize('NFD', texto.casefold())
        if not unicodedata.combining(caractere)
    )
    gatilhos_humano = (
        "atendente",
        "humano",
        "pessoa",
        "suporte",
        "falar com alguem",
    )
    if any(gatilho in texto_normalizado for gatilho in gatilhos_humano):
        pausados.append(sender_id)
        config['pausados'] = pausados
        cliente.config_json = config
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception(
                "Falha ao pausar automação para atendimento humano (cliente %s).",
                cliente.id,
            )
            return

        enviar_texto(
            sender_id,
            "Certo! Pausei as respostas automáticas para esta conversa. A equipe pode continuar o atendimento pelo Instagram.",
            cliente.token,
        )
        if msg_id is not None:
            mensagens_processadas.add(msg_id)
        return

    resposta = encontrar_resposta(texto, cliente)

    if resposta:
        enviar_texto(sender_id, resposta, cliente.token)
        if msg_id is not None:
            mensagens_processadas.add(msg_id)

def processar_comentario(comentario, cliente):
    texto = comentario.get('text', '').lower()
    comment_id = comentario.get('id')
    from_id = comentario.get('from', {}).get('id')
    username = comentario.get('from', {}).get('username', 'visitante')

    if from_id == cliente.id: return

    resposta_privada = encontrar_resposta(texto, cliente)
    if resposta_privada:
        mascara = cliente.config_json.get('msg_comentario_publico', "Olá {nome}! Direct!")
        enviar_resposta_publica(comment_id, mascara.replace("{nome}", f"@{username}"), cliente.token)
        enviar_private_reply(comment_id, resposta_privada, cliente.token)

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        if not VERIFY_TOKEN:
            app.logger.error("FACEBOOK_VERIFY_TOKEN não está configurado.")
            return "Webhook Meta não configurado.", 503
        if request.args.get('hub.verify_token') == VERIFY_TOKEN:
            return request.args.get('hub.challenge'), 200
        return 'Erro', 403

    if request.method == 'POST':
        assinatura_meta = request.headers.get('X-Hub-Signature-256', '')
        if not assinatura_meta:
            return 'Acesso negado: Assinatura ausente', 403

        if not CLIENT_SECRET:
            app.logger.error("FACEBOOK_APP_SECRET não está configurado.")
            return "Webhook Meta não configurado.", 503

        assinatura_esperada = 'sha256=' + hmac.new(
            CLIENT_SECRET.encode('utf-8'),
            request.data,
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(assinatura_esperada, assinatura_meta):
            app.logger.warning("Tentativa de ataque bloqueada no Webhook do Facebook.")
            return 'Acesso negado: Assinatura inválida', 403

        data = request.json
        if not isinstance(data, dict):
            return 'Payload JSON inválido', 400

        if 'entry' in data:
            for entry in data['entry']:
                evento_id = entry.get('id')
                cliente = db.session.get(Cliente, evento_id)

                if not cliente or not verificar_assinatura(cliente):
                    continue

                if 'messaging' in entry:
                    for msg in entry['messaging']:
                        processar_mensagem(msg, cliente)

                if 'changes' in entry:
                    for change in entry['changes']:
                        if change.get('field') == 'comments':
                            processar_comentario(change['value'], cliente)
        return 'Recebido', 200

# --- FUNÇÕES DE ENVIO ---

def enviar_texto(recipient_id, texto, token):
    try:
        requests.post(
            f"https://graph.facebook.com/v18.0/me/messages?access_token={token}",
            json={"recipient": {"id": recipient_id}, "message": {"text": texto}},
            headers={"Content-Type": "application/json"}
        )
    except Exception as e:
        print(f"❌ ERRO DE CONEXÃO: {e}")

def enviar_resposta_publica(comment_id, texto, token):
    try:
        requests.post(
            f"https://graph.facebook.com/v18.0/{comment_id}/replies",
            params={"access_token": token},
            json={"message": texto},
            headers={"Content-Type": "application/json"}
        )
    except Exception as e:
        print(e)

def enviar_private_reply(comment_id, texto, token):
    try:
        requests.post(
            f"https://graph.facebook.com/v18.0/me/messages?access_token={token}",
            json={
                "recipient": {"comment_id": comment_id},
                "message": {"text": texto}
            },
            headers={"Content-Type": "application/json"}
        )
    except Exception as e:
        print(f"❌ Erro de Conexão Private Reply: {e}")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
