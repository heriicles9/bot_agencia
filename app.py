import os
from flask import Flask, request
import requests
import json

app = Flask(__name__)

# --- CONFIGURAÇÕES DINÂMICAS (DO RENDER) ---
ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN") # Mudei o nome para padronizar com o painel anterior
VERIFY_TOKEN = os.getenv("FACEBOOK_VERIFY_TOKEN", "minha_senha_padrao")
MEU_ID_DO_INSTAGRAM = os.getenv("INSTAGRAM_ACCOUNT_ID")
LINK_WHATSAPP = os.getenv("CLIENTE_LINK_WHATSAPP")

# Pega palavras-chave do Render (ex: "preço,valor,eu quero,🔥,😍")
palavras_env = os.getenv("PALAVRAS_CHAVE", "preço,valor,link,eu quero,🔥,😍,👏")
PALAVRAS_CHAVE = [p.strip().lower() for p in palavras_env.split(",")]

# --- MEMÓRIA (Para não repetir respostas) ---
comentarios_processados = set()
mensagens_processadas = set()

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    # --- GET (Verificação do Facebook) ---
    if request.method == 'GET':
        if request.args.get('hub.verify_token') == VERIFY_TOKEN:
            return request.args.get('hub.challenge'), 200
        return 'Erro de Token', 403

    # --- POST (Recebimento de Eventos) ---
    if request.method == 'POST':
        try:
            data = request.json
            
            if 'entry' in data:
                for entry in data['entry']:
                    
                    # === 1. NOVOS DIRECTS E STORIES (Campo 'messaging') ===
                    if 'messaging' in entry:
                        for msg_event in entry['messaging']:
                            try:
                                sender_id = msg_event.get('sender', {}).get('id')
                                message = msg_event.get('message', {})
                                msg_id = message.get('mid')
                                texto = message.get('text', '').lower()

                                # Travas de Segurança
                                if sender_id == MEU_ID_DO_INSTAGRAM: continue
                                if msg_id in mensagens_processadas: continue
                                if not texto: continue 

                                print(f"📩 Direct/Story de {sender_id}: {texto}")

                                # Verifica Gatilhos
                                if any(p in texto for p in PALAVRAS_CHAVE):
                                    print("   ✅ Gatilho Direct Detectado! Respondendo...")
                                    
                                    resposta = f"Opa! Tudo bem? 😄\nVi seu interesse! Aqui está o link do nosso Grupo VIP: {LINK_WHATSAPP}"
                                    enviar_mensagem_texto(sender_id, resposta)
                                    
                                    mensagens_processadas.add(msg_id)
                            except Exception as e:
                                print(f"❌ Erro no Direct: {e}")

                    # === 2. NOVOS COMENTÁRIOS (Campo 'changes') ===
                    if 'changes' in entry:
                        for change in entry.get('changes', []):
                            try:
                                value = change.get('value', {})
                                if 'text' in value and 'id' in value:
                                    comentario_id = value['id']
                                    texto = value['text'].lower()
                                    autor_id = value.get('from', {}).get('id')

                                    # Travas
                                    if autor_id == MEU_ID_DO_INSTAGRAM: continue
                                    if comentario_id in comentarios_processados: continue

                                    # Lógica
                                    if any(p in texto for p in PALAVRAS_CHAVE):
                                        print(f"💬 Comentário Detectado: {texto}")
                                        
                                        # Envia Direct (Respondendo o comentário)
                                        msg_direct = f"Olá! 👋 Aqui está o link que pediu: {LINK_WHATSAPP}"
                                        enviar_direct_pelo_comentario(comentario_id, msg_direct)
                                        
                                        # Responde Público
                                        enviar_publico(comentario_id, "Te enviei o link no Direct! 📥")
                                        
                                        comentarios_processados.add(comentario_id)
                            except Exception as e:
                                print(f"❌ Erro no Comentário: {e}")

            return 'Recebido', 200
        except Exception as e:
            print(f"❌ Erro Geral: {e}")
            return 'Erro', 500

# --- FUNÇÕES DE ENVIO ---

def enviar_mensagem_texto(recipient_id, texto):
    """Envia mensagem para quem mandou Direct ou respondeu Story (usa ID do usuário)"""
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": texto}
    }
    requests.post(url, json=payload, headers={"Content-Type": "application/json"})

def enviar_direct_pelo_comentario(comment_id, mensagem):
    """Envia direct para quem comentou no post (usa ID do comentário)"""
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={ACCESS_TOKEN}"
    payload = {
        "recipient": {"comment_id": comment_id},
        "message": {"text": mensagem}
    }
    requests.post(url, json=payload, headers={"Content-Type": "application/json"})

def enviar_publico(comment_id, mensagem):
    """Responde publicamente no feed"""
    url = f"https://graph.facebook.com/v18.0/{comment_id}/replies?access_token={ACCESS_TOKEN}"
    payload = {"message": mensagem}
    requests.post(url, json=payload, headers={"Content-Type": "application/json"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
