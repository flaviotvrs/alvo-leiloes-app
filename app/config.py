import os

MIN_COMPARAVEIS_CONFIANCA_ALTA = int(os.environ.get("MIN_COMPARAVEIS_CONFIANCA_ALTA", "3"))

# Formato "provedor/modelo" do litellm — troca de provedor/modelo é só mudar esta
# variável de ambiente, sem alterar código (ver app/agents/mercado/extrator_llm.py).
MERCADO_EXTRACTOR_LLM_MODEL = os.environ.get("MERCADO_EXTRACTOR_LLM_MODEL", "anthropic/claude-sonnet-5")

# Nível de log do worker/agente mercado-extractor (DEBUG pra depurar por que
# um portal não está produzindo comparáveis usáveis, INFO no dia a dia).
WORKER_LOG_LEVEL = os.environ.get("WORKER_LOG_LEVEL", "INFO").upper()
