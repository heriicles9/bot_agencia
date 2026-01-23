import os
from flask import Flask, request
import requests
import json

app = Flask(__name__)

# --- CONFIGURAÇÕES DINÂMICAS (PUXA DO RENDER) ---
# Se não encontrar no Render, usa um valor padrão ou dá erro
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "minha_senha_padrao")
MEU_ID_DO_INSTAGRAM = os.getenv("MEU_ID_DO_INSTAGRAM")
LINK_WHATSAPP = os.getenv("LINK_WHATSAPP")

# Pega as palavras-chave do Render (separadas por vírgula)
# Exemplo no Render: "preço,valor,link,comprar"
palavras_env = os.getenv("PALAVRAS_CHAVE", "preço,valor,link")
PALAVRAS_CHAVE = [p.strip().lower() for p in palavras_env.split(",")]

comentarios_processados = set()

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    # --- GET (Verificação) ---
    if request.method == 'GET':
        if request.args.get('hub.verify_token') == VERIFY_TOKEN:
            return request.args.get('hub.challenge'), 200
        return 'Erro de Token', 403

    # --- POST (Recebimento) ---
    if request.method == 'POST':
        try:
            data = request.json
            if 'entry' in data:
                for entry in data['entry']:
                    for change in entry.get('changes', []):
                        value = change.get('value', {})
                        
                        if 'text' in value and 'id' in value:
                            comentario_id = value['id']
                            texto = value['text'].lower()
                            autor_id = value.get('from', {}).get('id')

                            # TRAVAS
                            if autor_id == MEU_ID_DO_INSTAGRAM: continue
                            if comentario_id in comentarios_processados: continue

                            # LÓGICA
                            if any(p in texto for p in PALAVRAS_CHAVE):
                                # 1. Envia Direct
                                msg_direct = f"Olá! 👋 Aqui está o link que pediu: {LINK_WHATSAPP}"
                                enviar_direct(comentario_id, msg_direct)
                                
                                # 2. Responde Público
                                enviar_publico(comentario_id, "Te enviei o link no Direct! 📥")
                                
                                comentarios_processados.add(comentario_id)
            return 'Recebido', 200
        except Exception as e:
            print(f"Erro: {e}")
            return 'Erro', 500

def enviar_direct(comment_id, mensagem):
    url = "https://graph.facebook.com/v18.0/me/messages"
    payload = {
        "recipient": {"comment_id": comment_id},
        "message": {"text": mensagem},
        "access_token": ACCESS_TOKEN
    }
    requests.post(url, json=payload, headers={"Content-Type": "application/json"})

def enviar_publico(comment_id, mensagem):
    url = f"https://graph.facebook.com/v18.0/{comment_id}/replies"
    payload = {"message": mensagem, "access_token": ACCESS_TOKEN}
    requests.post(url, json=payload, headers={"Content-Type": "application/json"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)