import hashlib
import hmac
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ASAAS_WEBHOOK_TOKEN"] = "test-webhook-token-with-more-than-32-characters"

import app as application


class AplicacaoTestes(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True)
        self.client = application.app.test_client()

        with application.app.app_context():
            application.db.session.remove()
            application.db.drop_all()
            application.db.create_all()
            cliente = application.Cliente(
                "instagram-123",
                "Loja Teste",
                "token-meta",
                "teste_gratis",
                dict(application.DEFAULT_CONFIG),
                datetime.now() + timedelta(days=7),
            )
            application.db.session.add(cliente)
            application.db.session.commit()

    def tearDown(self):
        with application.app.app_context():
            application.db.session.remove()
            application.db.engine.dispose()

    def enviar_evento(self, evento, evento_id, pagamento_id, referencia="instagram-123"):
        return self.client.post(
            "/webhook/asaas",
            headers={"asaas-access-token": "test-webhook-token-with-more-than-32-characters"},
            json={
                "id": evento_id,
                "event": evento,
                "payment": {
                    "id": pagamento_id,
                    "externalReference": referencia,
                },
            },
        )

    def preparar_dashboard(self):
        with self.client.session_transaction() as sessao:
            sessao["user_id"] = "instagram-123"

        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            cliente.config_json = application.aplicar_modelo_segmento(
                cliente.config_json,
                "loja",
            )
            application.db.session.commit()

    def test_dashboard_exibe_quatro_campos_de_ice_breakers(self):
        self.preparar_dashboard()
        resposta = self.client.get("/dashboard")

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data.count(b'name="ice_breakers[]"'), 4)
        self.assertIn(b"Bot\xc3\xb5es de In\xc3\xadcio R\xc3\xa1pido", resposta.data)

    def test_salvar_dashboard_limita_e_sincroniza_quatro_ice_breakers(self):
        self.preparar_dashboard()
        resposta_meta = Mock()

        with patch.object(application.requests, "post", return_value=resposta_meta) as enviar:
            resposta = self.client.post(
                "/dashboard",
                data={
                    "gatilhos[]": ["horario"],
                    "respostas[]": ["Confira nossos horários."],
                    "ice_breakers[]": [
                        "  Qual o horário? ",
                        " ",
                        "Vocês entregam?",
                        "Quais são as ofertas?",
                        "Como falar com a equipe?",
                        "Botão excedente",
                    ],
                },
            )

        self.assertEqual(resposta.status_code, 200)
        esperado = [
            "Qual o horário?",
            "Vocês entregam?",
            "Quais são as ofertas?",
            "Como falar com a equipe?",
        ]
        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            self.assertEqual(cliente.config_json["ice_breakers"], esperado)

        enviar.assert_called_once_with(
            "https://graph.facebook.com/v18.0/me/messenger_profile",
            params={"access_token": "token-meta", "platform": "instagram"},
            json={
                "platform": "instagram",
                "ice_breakers": [{
                    "call_to_actions": [
                        {"question": pergunta, "payload": pergunta}
                        for pergunta in esperado
                    ],
                    "locale": "default",
                }],
            },
            timeout=10,
        )
        resposta_meta.raise_for_status.assert_called_once_with()

    def test_permissao_ice_breakers_e_solicitada_no_login(self):
        self.assertIn("instagram_manage_messages", application.SCOPE)

    def test_clique_ice_breaker_processa_payload_do_postback(self):
        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            config = dict(cliente.config_json)
            config["fluxos"] = [{
                "gatilhos": "horário, abre",
                "resposta": "Funcionamos das 9h às 18h.",
            }]
            cliente.config_json = config
            application.db.session.commit()

            with patch.object(application, "enviar_texto") as enviar:
                application.processar_mensagem(
                    {
                        "sender": {"id": "usuario-instagram"},
                        "postback": {
                            "title": "Qual o horário?",
                            "payload": "Qual o horário?",
                        },
                    },
                    cliente,
                )

        enviar.assert_called_once_with(
            "usuario-instagram",
            "Funcionamos das 9h às 18h.",
            "token-meta",
        )

    def test_postbacks_sem_mid_processam_cliques_com_timestamps_diferentes(self):
        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            config = dict(cliente.config_json)
            config["fluxos"] = [{
                "gatilhos": "horário, abre",
                "resposta": "Funcionamos das 9h às 18h.",
            }]
            cliente.config_json = config
            application.db.session.commit()

            evento = {
                "sender": {"id": "usuario-sem-mid"},
                "postback": {"title": "Qual o horário?", "payload": "Qual o horário?"},
            }
            with patch.object(application, "enviar_texto") as enviar:
                application.processar_mensagem({**evento, "timestamp": 10001}, cliente)
                application.processar_mensagem({**evento, "timestamp": 10002}, cliente)
                application.processar_mensagem({**evento, "timestamp": 10002}, cliente)

        self.assertEqual(enviar.call_count, 2)

    def test_handoff_pausa_conversa_e_respeita_texto_com_acento(self):
        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            config = dict(cliente.config_json)
            config["fluxos"] = [{
                "gatilhos": "horário, abre",
                "resposta": "Funcionamos das 9h às 18h.",
            }]
            cliente.config_json = config
            application.db.session.commit()

            with (
                patch.object(application, "enviar_texto") as enviar,
                patch.object(application, "encontrar_resposta") as encontrar,
            ):
                application.processar_mensagem(
                    {
                        "sender": {"id": "usuario-handoff"},
                        "message": {"text": "Quero falar com alguém", "mid": "handoff-1"},
                    },
                    cliente,
                )
                application.processar_mensagem(
                    {
                        "sender": {"id": "usuario-handoff"},
                        "message": {"text": "Qual o horário?", "mid": "handoff-2"},
                    },
                    cliente,
                )

            config_salva = application.db.session.get(
                application.Cliente,
                "instagram-123",
            ).config_json

        self.assertEqual(config_salva["pausados"], ["usuario-handoff"])
        enviar.assert_called_once_with(
            "usuario-handoff",
            "Certo! Pausei as respostas automáticas para esta conversa. A equipe pode continuar o atendimento pelo Instagram.",
            "token-meta",
        )
        encontrar.assert_not_called()

    def test_dashboard_permite_retomar_automacao_de_conversa_pausada(self):
        self.preparar_dashboard()
        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            config = dict(cliente.config_json)
            config["pausados"] = ["usuario-retomar"]
            cliente.config_json = config
            application.db.session.commit()

        resposta_dashboard = self.client.get("/dashboard")
        self.assertIn(b"usuario-retomar", resposta_dashboard.data)
        resposta = self.client.post(
            "/dashboard/retomar-atendimento",
            data={"sender_id": "usuario-retomar"},
        )

        self.assertEqual(resposta.status_code, 302)
        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            self.assertEqual(cliente.config_json["pausados"], [])

    def test_remover_ice_breakers_envia_delete_para_meta(self):
        self.preparar_dashboard()

        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            config = dict(cliente.config_json)
            config["ice_breakers"] = ["Pergunta existente"]
            cliente.config_json = config
            application.db.session.commit()

        resposta_meta = Mock()
        with patch.object(application.requests, "delete", return_value=resposta_meta) as apagar:
            resposta = self.client.post(
                "/dashboard",
                data={"gatilhos[]": [], "respostas[]": [], "ice_breakers[]": [" ", ""]},
            )

        self.assertEqual(resposta.status_code, 200)
        apagar.assert_called_once_with(
            "https://graph.facebook.com/v18.0/me/messenger_profile",
            params={"access_token": "token-meta", "platform": "instagram"},
            json={"fields": ["ice_breakers"]},
            timeout=10,
        )
        resposta_meta.raise_for_status.assert_called_once_with()
        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            self.assertEqual(cliente.config_json["ice_breakers"], [])

    def test_falha_ao_sincronizar_ice_breakers_informa_que_nao_atualizou_meta(self):
        self.preparar_dashboard()

        with patch.object(
            application.requests,
            "post",
            side_effect=application.requests.Timeout,
        ):
            resposta = self.client.post(
                "/dashboard",
                data={
                    "gatilhos[]": [],
                    "respostas[]": [],
                    "ice_breakers[]": ["Como podemos ajudar?"],
                },
            )

        self.assertIn(b"n\xc3\xa3o foi poss\xc3\xadvel atualizar os bot\xc3\xb5es", resposta.data)
        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            self.assertEqual(
                cliente.config_json["ice_breakers"],
                ["Como podemos ajudar?"],
            )

    def test_homepage_exibe_planos_faq_e_contato_whatsapp(self):
        resposta = self.client.get("/")

        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b'href="#planos"', resposta.data)
        self.assertIn(b'href="#faq"', resposta.data)
        self.assertIn(b'id="planos"', resposta.data)
        self.assertIn(b'id="faq"', resposta.data)
        self.assertIn("R$ 49,90".encode(), resposta.data)
        self.assertIn(b"https://wa.me/5575983479259", resposta.data)
        self.assertIn(b"D\xc3\xbavidas Frequentes", resposta.data)
        self.assertIn(b'href="/termos"', resposta.data)
        self.assertIn(b'href="/privacidade"', resposta.data)

    def test_paginas_legais_publicas(self):
        resposta_termos = self.client.get("/termos")
        resposta_privacidade = self.client.get("/privacidade")

        self.assertEqual(resposta_termos.status_code, 200)
        self.assertIn(b"Termos de Uso", resposta_termos.data)
        self.assertIn(b"Teste e pagamentos", resposta_termos.data)
        self.assertEqual(resposta_privacidade.status_code, 200)
        self.assertIn(b"Pol\xc3\xadtica de Privacidade", resposta_privacidade.data)
        self.assertIn(b"Lei Geral de Prote\xc3\xa7\xc3\xa3o de Dados", resposta_privacidade.data)

    def test_onboarding_aplica_modelo_e_painel_preserva_personalizacao(self):
        with self.client.session_transaction() as sessao:
            sessao["user_id"] = "instagram-123"

        resposta_dashboard = self.client.get("/dashboard")
        self.assertEqual(resposta_dashboard.status_code, 302)
        self.assertEqual(resposta_dashboard.headers["Location"], "/onboarding")

        resposta_onboarding = self.client.post(
            "/onboarding",
            data={"segmento": "supermercado"},
        )
        self.assertEqual(resposta_onboarding.status_code, 302)
        self.assertEqual(resposta_onboarding.headers["Location"], "/dashboard")

        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            self.assertEqual(cliente.config_json["segmento"], "supermercado")
            self.assertNotEqual(
                cliente.config_json["fluxos"][0]["resposta"],
                "R$ 99,00",
            )

        resposta_painel = self.client.get("/dashboard")
        self.assertEqual(resposta_painel.status_code, 200)
        self.assertIn(b"Modelo: Supermercado", resposta_painel.data)

        with patch.object(application.requests, "delete") as remover_ice_breakers:
            salvar_configuracao = self.client.post(
                "/dashboard",
                data={
                    "gatilhos[]": "whatsapp, contato",
                    "respostas[]": "Nossa equipe já vai falar com você.",
                    "msg_padrao": "Atenda de maneira acolhedora e personalizada.",
                    "msg_comentario_publico": "Oi {nome}, confira seu direct!",
                },
            )
        remover_ice_breakers.assert_called_once()
        self.assertEqual(salvar_configuracao.status_code, 200)
        self.assertIn(b"Nossa equipe j\xc3\xa1 vai falar com voc\xc3\xaa.", salvar_configuracao.data)
        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            self.assertEqual(
                cliente.config_json["msg_padrao"],
                "Atenda de maneira acolhedora e personalizada.",
            )

        configuracao_personalizada = {
            "segmento": "supermercado",
            "_modelo_base": {
                "msg_padrao": application.MODELOS_POR_SEGMENTO["supermercado"]["msg_padrao"],
                "fluxos": application.MODELOS_POR_SEGMENTO["supermercado"]["fluxos"],
                "msg_comentario_publico": application.DEFAULT_CONFIG["msg_comentario_publico"],
            },
            "msg_padrao": "Atenda com humor e sem emojis.",
            "fluxos": [{"gatilhos": "meu gatilho", "resposta": "minha resposta"}],
            "msg_comentario_publico": application.DEFAULT_CONFIG["msg_comentario_publico"],
        }
        nova_configuracao = application.aplicar_modelo_segmento(
            configuracao_personalizada,
            "loja",
        )
        self.assertEqual(nova_configuracao["msg_padrao"], "Atenda com humor e sem emojis.")
        self.assertEqual(nova_configuracao["fluxos"], configuracao_personalizada["fluxos"])

    def test_pagamento_concede_30_dias_uma_vez_por_cobranca(self):
        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            cliente.data_expiracao = datetime.now() - timedelta(days=1)
            cliente.config_json = application.aplicar_modelo_segmento(
                cliente.config_json,
                "loja",
            )
            application.db.session.commit()

        confirmado = self.enviar_evento("PAYMENT_CONFIRMED", "evt-confirmado", "pay-1")
        self.assertEqual(confirmado.status_code, 200)

        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            validade_apos_confirmacao = cliente.data_expiracao
            self.assertTrue(cliente.ativo)
            self.assertGreater(validade_apos_confirmacao, datetime.now() + timedelta(days=29))

        recebido = self.enviar_evento("PAYMENT_RECEIVED", "evt-recebido", "pay-1")
        self.assertEqual(recebido.status_code, 200)
        duplicado = self.enviar_evento("PAYMENT_RECEIVED", "evt-recebido", "pay-1")
        self.assertEqual(duplicado.status_code, 200)
        self.assertTrue(duplicado.json["duplicate"])

        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            self.assertEqual(cliente.data_expiracao, validade_apos_confirmacao)
            self.assertEqual(application.AsaasPagamento.query.count(), 1)
            self.assertEqual(application.AsaasEvento.query.count(), 2)

    def test_vencimento_suspende_e_pagamento_posterior_reativa(self):
        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            cliente.config_json = application.aplicar_modelo_segmento(
                cliente.config_json,
                "loja",
            )
            application.db.session.commit()

        with self.client.session_transaction() as sessao:
            sessao["user_id"] = "instagram-123"

        vencido = self.enviar_evento("PAYMENT_OVERDUE", "evt-vencido", "pay-2")
        self.assertEqual(vencido.status_code, 200)
        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            self.assertFalse(cliente.ativo)
            regras_antes = cliente.config_json["fluxos"]

        painel_pausado = self.client.get("/dashboard")
        self.assertIn(b"Acesso suspenso", painel_pausado.data)
        self.client.post(
            "/dashboard",
            data={
                "gatilhos[]": "alterar",
                "respostas[]": "não deve salvar",
                "msg_padrao": "não deve salvar",
            },
        )
        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            self.assertEqual(cliente.config_json["fluxos"], regras_antes)

        recebido = self.enviar_evento("PAYMENT_RECEIVED", "evt-regularizado", "pay-2")
        self.assertEqual(recebido.status_code, 200)
        vencimento_atrasado = self.enviar_evento("PAYMENT_OVERDUE", "evt-atrasado", "pay-2")
        self.assertEqual(vencimento_atrasado.status_code, 200)

        with application.app.app_context():
            cliente = application.db.session.get(application.Cliente, "instagram-123")
            pagamento = application.db.session.get(application.AsaasPagamento, "pay-2")
            self.assertTrue(cliente.ativo)
            self.assertEqual(pagamento.status, "PAID")
            self.assertTrue(pagamento.periodo_concedido)

    def test_webhook_valida_token_e_referencia_do_cliente(self):
        sem_token = self.client.post(
            "/webhook/asaas",
            json={"id": "evt-3", "event": "PAYMENT_RECEIVED", "payment": {"id": "pay-3"}},
        )
        self.assertEqual(sem_token.status_code, 403)

        sem_referencia = self.enviar_evento(
            "PAYMENT_RECEIVED",
            "evt-sem-referencia",
            "pay-3",
            referencia="cliente-inexistente",
        )
        self.assertEqual(sem_referencia.status_code, 422)

        desconhecido = self.client.post(
            "/webhook/asaas",
            headers={"asaas-access-token": "test-webhook-token-with-more-than-32-characters"},
            json={"id": "evt-outro", "event": "PAYMENT_CREATED", "payment": {}},
        )
        self.assertEqual(desconhecido.status_code, 200)
        self.assertTrue(desconhecido.json["ignored"])

    def test_webhook_meta_exige_assinatura_valida(self):
        corpo = b'{"entry":[]}'
        segredo = "segredo-de-teste"
        assinatura = "sha256=" + hmac.new(
            segredo.encode("utf-8"),
            corpo,
            hashlib.sha256,
        ).hexdigest()

        with patch.object(application, "CLIENT_SECRET", segredo):
            sem_assinatura = self.client.post(
                "/webhook",
                data=corpo,
                content_type="application/json",
            )
            assinatura_invalida = self.client.post(
                "/webhook",
                data=corpo,
                content_type="application/json",
                headers={"X-Hub-Signature-256": "sha256=invalida"},
            )
            assinatura_valida = self.client.post(
                "/webhook",
                data=corpo,
                content_type="application/json",
                headers={"X-Hub-Signature-256": assinatura},
            )

        self.assertEqual(sem_assinatura.status_code, 403)
        self.assertEqual(assinatura_invalida.status_code, 403)
        self.assertEqual(assinatura_valida.status_code, 200)

    def test_webhook_meta_nao_verifica_sem_token_configurado(self):
        with patch.object(application, "VERIFY_TOKEN", None):
            resposta = self.client.get(
                "/webhook",
                query_string={"hub.verify_token": "senha_padrao"},
            )

        self.assertEqual(resposta.status_code, 503)

    def test_consultar_gemini_limita_pergunta_a_250_caracteres(self):
        cliente_gemini = Mock()
        cliente_gemini.models.generate_content.return_value.text = "Resposta curta"

        with patch.object(application, "gemini_client", cliente_gemini):
            resposta = application.consultar_gemini("persona", "a" * 250 + "b")

        self.assertEqual(resposta, "Resposta curta")
        conteudo_prompt = cliente_gemini.models.generate_content.call_args.kwargs["contents"]
        self.assertIn("a" * 250, conteudo_prompt)
        self.assertNotIn("b", conteudo_prompt)

    def test_exclusao_de_cliente_requer_post(self):
        with self.client.session_transaction() as sessao:
            sessao["admin_logged_in"] = True

        dashboard = self.client.get("/admin")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(
            b'<form action="/admin/excluir/instagram-123" method="POST"',
            dashboard.data,
        )

        resposta_get = self.client.get("/admin/excluir/instagram-123")
        self.assertEqual(resposta_get.status_code, 405)
        with application.app.app_context():
            self.assertIsNotNone(
                application.db.session.get(application.Cliente, "instagram-123")
            )

        resposta_post = self.client.post("/admin/excluir/instagram-123")
        self.assertEqual(resposta_post.status_code, 302)
        with application.app.app_context():
            self.assertIsNone(
                application.db.session.get(application.Cliente, "instagram-123")
            )

    def test_login_admin_falha_se_senha_nao_estiver_configurada(self):
        with patch.object(application, "ADMIN_PASSWORD", None):
            resposta = self.client.post("/admin/login", data={"senha": "admin123"})

        self.assertEqual(resposta.status_code, 503)


if __name__ == "__main__":
    unittest.main()
