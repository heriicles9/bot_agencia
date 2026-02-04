import os
from flask import Flask, request
import requests
import json

app = Flask(__name__)

# --- CONFIGURAÇÕES DINÂMICAS ---
ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("FACEBOOK_VERIFY_TOKEN", "minha_senha_secreta_ninja")
MEU_ID_DO_INSTAGRAM = os.getenv("INSTAGRAM_ACCOUNT_ID")
LINK_WHATSAPP = os.getenv("CLIENTE_LINK_WHATSAPP")

# --- MENSAGENS PERSONALIZÁVEIS (LÊ DO RENDER) ---
# O texto padrão (depois da vírgula) é usado se você não configurar nada no Render.
# Nota: O código substitui automaticamente {link} pelo seu link do WhatsApp.
MSG_VENDA_PADRAO = os.getenv("MSG_VENDA", "Olá! Tudo bem? 😄\nVi seu interesse! Aqui está o meu Whatsapp:\n{link}")
MSG_BOAS_VINDAS_PADRAO = os.getenv("MSG_BOAS_VINDAS", "Olá! Seja bem-vindo(a)! 👋\nDigite 'preço' para ver ofertas ou me faça uma pergunta!")

# --- LISTAS DE GATILHOS ---
# 1. Gatilhos de Venda (Interesse)
env_venda = os.getenv("GATILHOS_VENDA", "preço,valor,link,eu quero,🔥,😍,👏,❤️,😮,comprar")
GATILHOS_VENDA = [p.strip().lower() for p in env_venda.split(",")]

# 2. Gatilhos de Boas-Vindas (Saudação)
env_ola = os.getenv("GATILHOS_BOAS_VINDAS", "oi,olá,ola,bom dia,boa tarde,boa noite,start,começar,cheguei,loja")
GATILHOS_BOAS_VINDAS = [p.strip().lower() for p in env_ola.split(",")]

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

        # Filtro de texto muito longo (opcional, mantive o seu)
        if len(texto) > 100:
            print(f"   💤 Texto longo ({len(texto)} chars). Ignorando.")
            return

        print(f"📩 Direct/Story de {sender_id}: {texto}")

        resposta_final = ""

        # LÓGICA DE ESCOLHA DA MENSAGEM
        if any(p in texto for p in GATILHOS_VENDA):
            print("   ✅ Gatilho de VENDA detectado!")
            # Pega msg de venda e troca o {link} pelo link real
            resposta_final = MSG_VENDA_PADRAO.replace("{link}", LINK_WHATSAPP or "")
            
        elif any(p in texto for p in GATILHOS_BOAS_VINDAS):
            print("   👋 Gatilho de BOAS-VINDAS detectado!")
            resposta_final = MSG_BOAS_VINDAS_PADRAO
        
        # Se encontrou uma resposta, envia
        if resposta_final:
            # Corrige a quebra de linha que vem do Render (transforma \n escrito em Enter real)
            resposta_final = resposta_final.replace(r'\n', '\n')
            
            sucesso = enviar_mensagem_texto(sender_id, resposta_final)
            if sucesso:
                mensagens_processadas.add(msg_id)
                print("   🏆 Resposta enviada!")
        else:
            print("   💤 Sem gatilho conhecido.")

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

            # Nos comentários, usamos sempre a lógica de VENDA (interesse)
            if any(p in texto for p in GATILHOS_VENDA):
                print(f"💬 Comentário Venda: {texto}")
                
                # Monta a mensagem de venda
                msg_direct = MSG_VENDA_PADRAO.replace("{link}", LINK_WHATSAPP or "")
                msg_direct = msg_direct.replace(r'\n', '\n')

                enviar_direct_pelo_comentario(comentario_id, msg_direct)
                enviar_resposta_publica(comentario_id, "Te enviei o link no Direct! 📥")
                
                comentarios_processados.add(comentario_id)
    except Exception as e:
        print(f"❌ Erro Comentário: {e}")

# --- FUNÇÕES DE ENVIO ---

def enviar_mensagem_texto(recipient_id, texto):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": texto}
    }
    r = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
    
    if r.status_code == 200:
        return True
    else:
        print(f"⚠️ ERRO API FACEBOOK: {r.status_code} - {r.text}")
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
