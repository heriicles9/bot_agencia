import os
import json
import requests
from flask import Flask, request

app = Flask(__name__)

# --- CONFIGURAÇÕES VIA ENVIRONMENT (RENDER) ---
# O código busca essas chaves nas configurações do servidor
ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("FACEBOOK_VERIFY_TOKEN")
MEU_ID_DO_INSTAGRAM = os.getenv("INSTAGRAM_ACCOUNT_ID")
LINK_WHATSAPP = os.getenv("CLIENTE_LINK_WHATSAPP")

# --- GATILHOS (Padrão para todos) ---
PALAVRAS_CHAVE = [
    "preço", "preco", "valor", "link", "comprar", "grupo", "info", "teste", "eu quero",
    "🔥", "😍", "👏", "❤️", "😮"
]

# --- MEMÓRIA (Reinicia se o bot reiniciar) ---
comentarios_processados = set()
mensagens_processadas = set()

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    # Verifica se as variáveis foram configuradas
    if not ACCESS_TOKEN or not VERIFY_TOKEN:
        print("❌ ERRO CRÍTICO: Variáveis de Ambiente não configuradas no Render!")
        return 'Erro de Configuração', 500

    # --- GET (Verificação do Facebook) ---
    if request.method == 'GET':
        token_enviado = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        
        if token_enviado == VERIFY_TOKEN:
            return challenge, 200
        return 'Erro de Token de Verificação', 403

    # --- POST (Chegada de Eventos) ---
    if request.method == 'POST':
        try:
            data = request.json
            
            if 'entry' in data:
                for entry in data['entry']:
                    # 1. Directs e Stories
                    if 'messaging' in entry:
                        for msg_event in entry['messaging']:
                            processar_mensagem_direct(msg_event)

                    # 2. Comentários
                    if 'changes' in entry:
                        for change in entry['changes']:
                            processar_comentario_feed(change)

            return 'Recebido', 200
        except Exception as e:
            print(f"❌ Erro no Webhook: {e}")
            return 'Erro', 500

# --- FUNÇÕES DE PROCESSAMENTO ---

def processar_mensagem_direct(event):
    try:
        sender_id = event.get('sender', {}).get('id')
        message = event.get('message', {})
        msg_id = message.get('mid')
        texto = message.get('text', '').lower()

        if sender_id == MEU_ID_DO_INSTAGRAM: return
        if msg_id in mensagens_processadas: return
        if not texto: return

        print(f"📩 Direct de {sender_id}: {texto}")

        if any(p in texto for p in PALAVRAS_CHAVE):
            print("   ✅ Gatilho Direct! Respondendo...")
            resposta = f"Opa! Tudo bem? 😄\nVi seu interesse! Aqui está o link do nosso Grupo VIP: {LINK_WHATSAPP}"
            enviar_mensagem_texto(sender_id, resposta)
            mensagens_processadas.add(msg_id)

    except Exception as e:
        print(f"❌ Erro Direct: {e}")

def processar_comentario_feed(change):
    try:
        value = change.get('value', {})
        if 'text' in value and 'id' in value:
            comentario_id = value['id']
            texto = value['text'].lower()
            autor_id = value.get('from', {}).get('id')

            if autor_id == MEU_ID_DO_INSTAGRAM: return
            if comentario_id in comentarios_processados: return

            if any(p in texto for p in PALAVRAS_CHAVE):
                print(f"💬 Comentário: '{texto}'")
                msg_direct = f"Olá! Vi seu comentário. Aqui está o link: {LINK_WHATSAPP}"
                enviar_direct_pelo_comentario(comentario_id, msg_direct)
                enviar_resposta_publica(comentario_id, "Te enviei no Direct! 📥")
                comentarios_processados.add(comentario_id)
    except Exception as e:
        print(f"❌ Erro Comentário: {e}")

# --- ENVIOS ---
def enviar_mensagem_texto(recipient_id, texto):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={ACCESS_TOKEN}"
    payload = {"recipient": {"id": recipient_id}, "message": {"text": texto}}
    requests.post(url, json=payload)

def enviar_direct_pelo_comentario(comment_id, mensagem):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={ACCESS_TOKEN}"
    payload = {"recipient": {"comment_id": comment_id}, "message": {"text": mensagem}}
    requests.post(url, json=payload)

def enviar_resposta_publica(comment_id, mensagem):
    url = f"https://graph.facebook.com/v18.0/{comment_id}/replies?access_token={ACCESS_TOKEN}"
    payload = {"message": mensagem}
    requests.post(url, json=payload)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
