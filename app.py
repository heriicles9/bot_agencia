import os
from flask import Flask, request
import requests
import json

app = Flask(__name__)

# --- CONFIGURAÇÕES DINÂMICAS ---
ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("FACEBOOK_VERIFY_TOKEN", "minha_senha_padrao")
MEU_ID_DO_INSTAGRAM = os.getenv("INSTAGRAM_ACCOUNT_ID")
LINK_WHATSAPP = os.getenv("CLIENTE_LINK_WHATSAPP")

palavras_env = os.getenv("PALAVRAS_CHAVE", "preço,valor,link,eu quero,🔥,😍,👏,❤️,😮")
PALAVRAS_CHAVE = [p.strip().lower() for p in palavras_env.split(",")]

comentarios_processados = set()
mensagens_processadas = set()

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        if request.args.get('hub.verify_token') == VERIFY_TOKEN:
            return request.args.get('hub.challenge'), 200
        return 'Erro de Token', 403

    if request.method == 'POST':
        try:
            data = request.json
            if 'entry' in data:
                for entry in data['entry']:
                    
                    # === 1. DIRECTS E STORIES ===
                    if 'messaging' in entry:
                        for msg_event in entry['messaging']:
                            processar_mensagem_direct(msg_event)

                    # === 2. COMENTÁRIOS ===
                    if 'changes' in entry:
                        for change in entry.get('changes', []):
                            processar_comentario_feed(change)

            return 'Recebido', 200
        except Exception as e:
            print(f"❌ Erro Geral: {e}")
            return 'Erro', 500

def processar_mensagem_direct(event):
    try:
        sender_id = event.get('sender', {}).get('id')
        message = event.get('message', {})
        msg_id = message.get('mid')
        texto = message.get('text', '').lower()

        if sender_id == MEU_ID_DO_INSTAGRAM: return
        if msg_id in mensagens_processadas: return
        if not texto: return

        # --- FILTRO DE CONVERSA HUMANA ---
        # Se a pessoa mandou um texto longo (> 50 letras), ignora.
        if len(texto) > 50:
            print(f"   💤 Texto longo ({len(texto)} chars). Ignorando para não atrapalhar conversa.")
            return

        print(f"📩 Direct/Story de {sender_id}: {texto}")

        if any(p in texto for p in PALAVRAS_CHAVE):
            print("   ✅ Gatilho detectado! Tentando enviar resposta...")
            
            resposta = f"Fala boleiro! Tudo bem? 😄\nVi seu interesse! Aqui está o meu Whatsapp: {LINK_WHATSAPP}"
            sucesso = enviar_mensagem_texto(sender_id, resposta)
            
            if sucesso:
                mensagens_processadas.add(msg_id)
                print("   🏆 Resposta enviada e confirmada!")
            else:
                print("   🚫 Falha no envio (Veja o erro acima)")

    except Exception as e:
        print(f"❌ Erro no processamento Direct: {e}")

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
                print(f"💬 Comentário: {texto}")
                msg_direct = f"Olá! 👋 Aqui está o link que pediu: {LINK_WHATSAPP}"
                
                enviar_direct_pelo_comentario(comentario_id, msg_direct)
                enviar_resposta_publica(comentario_id, "Te enviei o link no Direct! 📥")
                
                comentarios_processados.add(comentario_id)
    except Exception as e:
        print(f"❌ Erro Comentário: {e}")

# --- FUNÇÕES DE ENVIO COM DEBUG 🕵️‍♂️ ---

def enviar_mensagem_texto(recipient_id, texto):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": texto}
    }
    # Aqui está o segredo: Capturamos a resposta 'r'
    r = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
    
    if r.status_code == 200:
        return True
    else:
        # Se der erro, ELE VAI GRITAR NO LOG AGORA
        print(f"⚠️ ERRO API FACEBOOK: {r.status_code}")
        print(f"📜 Detalhe: {r.text}")
        return False

def enviar_direct_pelo_comentario(comment_id, mensagem):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={ACCESS_TOKEN}"
    payload = {
        "recipient": {"comment_id": comment_id},
        "message": {"text": mensagem}
    }
    r = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
    if r.status_code != 200:
        print(f"⚠️ Erro Direct Comentário: {r.text}")

def enviar_resposta_publica(comment_id, mensagem):
    url = f"https://graph.facebook.com/v18.0/{comment_id}/replies?access_token={ACCESS_TOKEN}"
    payload = {"message": mensagem}
    requests.post(url, json=payload, headers={"Content-Type": "application/json"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
