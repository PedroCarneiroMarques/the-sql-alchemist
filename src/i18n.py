from __future__ import annotations

from config import get_config

SUPPORTED_LOCALES = ("en", "pt")
_LOCALE = "en"

TRANSLATIONS: dict[str, dict[str, str]] = {
    "locale.en": {"en": "English", "pt": "English"},
    "locale.pt": {"en": "Portuguese", "pt": "Português"},
    "app.title": {"en": "The Neural Bridge", "pt": "A Ponte Neural"},
    "app.subtitle": {
        "en": "Natural language analytics powered by Streamlit, DuckDB and Ollama.",
        "pt": "Análise em linguagem natural com Streamlit, DuckDB e Ollama.",
    },
    "app.footer": {
        "en": (
            "DuckDB + Ollama + Streamlit integrated with model fallback, suggested prompts, "
            "business impact, watchdog quality checks, airline rivalry analysis, and result explanations."
        ),
        "pt": (
            "DuckDB + Ollama + Streamlit com fallback de modelos, sugestões de perguntas, "
            "impacto de negócio, watchdog, rivalidade entre companhias e explicações de resultados."
        ),
    },
    "app.file_not_found": {"en": "Data file not found: {path}", "pt": "Ficheiro não encontrado: {path}"},
    "settings.title": {"en": "Settings", "pt": "Definições"},
    "settings.language": {"en": "Language", "pt": "Idioma"},
    "settings.model_profile": {"en": "Model profile", "pt": "Perfil do modelo"},
    "settings.execution_strategy": {"en": "Execution strategy", "pt": "Estratégia de execução"},
    "settings.custom_model_chain": {"en": "Custom model chain", "pt": "Cadeia de modelos personalizada"},
    "settings.execution_order": {"en": "Execution order", "pt": "Ordem de execução"},
    "settings.model_chain_help": {
        "en": "The app tries models in order, then falls back to keyword SQL if needed.\n\nActive chain: {chain}",
        "pt": "A app tenta os modelos por ordem e recorre a SQL por palavras-chave se necessário.\n\nCadeia ativa: {chain}",
    },
    "settings.business_impact": {"en": "Business Impact", "pt": "Impacto de Negócio"},
    "settings.delay_cost": {"en": "Delay cost per minute (€)", "pt": "Custo de atraso por minuto (€)"},
    "settings.cancellation_cost": {"en": "Cancellation cost (€)", "pt": "Custo de cancelamento (€)"},
    "settings.watchdog": {"en": "Watchdog", "pt": "Watchdog"},
    "settings.sensitivity": {"en": "Sensitivity", "pt": "Sensibilidade"},
    "settings.global_filters": {"en": "Global Filters", "pt": "Filtros Globais"},
    "settings.airlines": {"en": "Airlines", "pt": "Companhias aéreas"},
    "settings.airline_wars": {"en": "Airline Wars", "pt": "Guerra das Companhias"},
    "settings.airline_a": {"en": "Airline A", "pt": "Companhia A"},
    "settings.airline_b": {"en": "Airline B", "pt": "Companhia B"},
    "settings.destination": {"en": "Destination", "pt": "Destino"},
    "settings.clear_chat": {"en": "Clear chat history", "pt": "Limpar histórico do chat"},
    "tab.visuals": {"en": "Visuals", "pt": "Visuais"},
    "tab.chat": {"en": "Chat", "pt": "Chat"},
    "visuals.real_time": {"en": "Real-Time Analytics", "pt": "Análise em Tempo Real"},
    "visuals.total_flights": {"en": "Total Flights", "pt": "Total de Voos"},
    "visuals.avg_latency": {"en": "Avg Latency", "pt": "Latência Média"},
    "visuals.delayed_flights": {"en": "Delayed Flights", "pt": "Voos Atrasados"},
    "visuals.total_cost": {"en": "Total Cost (€)", "pt": "Custo Total (€)"},
    "visuals.delay_cost": {"en": "Delay Cost (€)", "pt": "Custo de Atraso (€)"},
    "visuals.cancellation_cost": {"en": "Cancellation Cost (€)", "pt": "Custo de Cancelamento (€)"},
    "visuals.reliable_rows": {"en": "Reliable Rows", "pt": "Linhas Fiáveis"},
    "visuals.review_rows": {"en": "Review Rows", "pt": "Linhas para Revisão"},
    "visuals.high_risk_rows": {"en": "High Risk Rows", "pt": "Linhas de Alto Risco"},
    "visuals.result_explanation": {"en": "Result Explanation", "pt": "Explicação do Resultado"},
    "visuals.no_data": {"en": "No data available for the current filter selection.", "pt": "Sem dados para a seleção de filtros atual."},
    "visuals.latency_timeline": {"en": "Latency Timeline", "pt": "Linha do Tempo de Latência"},
    "visuals.impacted_airlines": {"en": "Impacted Airlines", "pt": "Companhias Impactadas"},
    "visuals.no_delayed_flights": {"en": "No delayed flights in current selection.", "pt": "Sem voos atrasados na seleção atual."},
    "visuals.cost_of_chaos": {"en": "Cost of Chaos", "pt": "Custo do Caos"},
    "visuals.no_cost_impact": {"en": "No cost impact available for the current selection.", "pt": "Sem impacto de custo para a seleção atual."},
    "visuals.watchdog_distribution": {"en": "Watchdog Quality Distribution", "pt": "Distribuição de Qualidade do Watchdog"},
    "visuals.no_route_comparison": {
        "en": "No route comparison data available for the selected airline pair and destination.",
        "pt": "Sem dados de comparação de rota para o par de companhias e destino selecionados.",
    },
    "visuals.filtered_data": {"en": "Filtered Data", "pt": "Dados Filtrados"},
    "visuals.estimated_cost_by_airline": {"en": "Estimated Total Cost by Airline", "pt": "Custo Total Estimado por Companhia"},
    "chat.ask_analyst": {"en": "Ask the Analyst", "pt": "Pergunte ao Analista"},
    "chat.input_placeholder": {"en": "Ask a question about the flights data", "pt": "Faça uma pergunta sobre os dados de voos"},
    "chat.suggested_questions": {"en": "Suggested Questions", "pt": "Perguntas Sugeridas"},
    "chat.model_used": {"en": "Model used: {model}", "pt": "Modelo usado: {model}"},
    "chat.answered_with": {"en": "Answered with: {model}", "pt": "Respondido com: {model}"},
    "chat.reload_failed": {"en": "Could not reload stored query results.", "pt": "Não foi possível recarregar os resultados guardados."},
    "chat.unknown_error": {"en": "Unknown error", "pt": "Erro desconhecido"},
    "chat.model_attempts": {"en": "Model attempts", "pt": "Tentativas de modelo"},
    "chat.earlier_failed_attempts": {"en": "Earlier failed attempts", "pt": "Tentativas anteriores falhadas"},
    "chat.auto_chart": {"en": "Auto Chart", "pt": "Gráfico Automático"},
    "chat.download_csv": {"en": "Download result CSV", "pt": "Descarregar CSV do resultado"},
    "export.download_cost_csv": {"en": "Download cost by airline CSV", "pt": "Descarregar CSV de custo por companhia"},
    "export.download_wars_csv": {"en": "Download Airline Wars CSV", "pt": "Descarregar CSV da Guerra das Companhias"},
    "export.download_filtered_csv": {"en": "Download filtered data CSV", "pt": "Descarregar CSV dos dados filtrados"},
    "export.download_watchdog_csv": {"en": "Download watchdog summary CSV", "pt": "Descarregar CSV do resumo watchdog"},
    "profile.fast": {"en": "Fast — single lightweight model", "pt": "Rápido — um modelo leve"},
    "profile.balanced": {"en": "Balanced — default fallback chain", "pt": "Equilibrado — cadeia de fallback predefinida"},
    "profile.accurate": {"en": "Accurate — larger models first", "pt": "Preciso — modelos maiores primeiro"},
    "watchdog.relaxed": {"en": "Relaxed — fewer alerts", "pt": "Relaxado — menos alertas"},
    "watchdog.normal": {"en": "Normal — balanced anomaly scoring", "pt": "Normal — pontuação equilibrada"},
    "watchdog.strict": {"en": "Strict — more high-risk flags", "pt": "Estrito — mais sinalizações de alto risco"},
    "cli.ready": {
        "en": (
            "The SQL Alchemist CLI is ready.\n"
            "Type a natural-language question, or use one of the commands below:\n"
            "  /help        Show commands\n"
            "  /suggest     Show suggested questions\n"
            "  /filter      Choose airlines for dashboard and wars\n"
            "  /profile     Show or set model profile (fast|balanced|accurate)\n"
            "  /watchdog    Show or set watchdog sensitivity\n"
            "  /dashboard   Show KPI summary + Watchdog\n"
            "  /wars        Interactive Airline Wars comparison\n"
            "  /export      Save last result to exports/\n"
            "  /models      Show active model chain\n"
            "  /quit        Exit"
        ),
        "pt": (
            "A CLI do SQL Alchemist está pronta.\n"
            "Escreva uma pergunta em linguagem natural ou use um dos comandos:\n"
            "  /help        Mostrar comandos\n"
            "  /suggest     Mostrar perguntas sugeridas\n"
            "  /filter      Escolher companhias para dashboard e guerras\n"
            "  /profile     Ver ou definir perfil do modelo (fast|balanced|accurate)\n"
            "  /watchdog    Ver ou definir sensibilidade do watchdog\n"
            "  /dashboard   Mostrar KPIs + Watchdog\n"
            "  /wars        Comparação interativa Guerra das Companhias\n"
            "  /export      Guardar último resultado em exports/\n"
            "  /models      Mostrar cadeia de modelos ativa\n"
            "  /quit        Sair"
        ),
    },
    "cli.title": {"en": "Neural Flight Bridge CLI", "pt": "CLI da Ponte Neural"},
    "cli.prompt": {"en": "The Alchemist", "pt": "O Alquimista"},
    "cli.session_closed": {"en": "Session closed.", "pt": "Sessão terminada."},
    "cli.help": {
        "en": (
            "Commands: /suggest, /filter, /profile, /watchdog, /dashboard, /wars, /export, /models.\n"
            "Profiles: /profile fast | /profile balanced | /profile accurate\n"
            "Watchdog: /watchdog relaxed | /watchdog normal | /watchdog strict\n"
            "Quick wars: /wars AirlineA AirlineB Destination\n"
            "Quick export: /export my_file.csv"
        ),
        "pt": (
            "Comandos: /suggest, /filter, /profile, /watchdog, /dashboard, /wars, /export, /models.\n"
            "Perfis: /profile fast | /profile balanced | /profile accurate\n"
            "Watchdog: /watchdog relaxed | /watchdog normal | /watchdog strict\n"
            "Guerra rápida: /wars CompanhiaA CompanhiaB Destino\n"
            "Exportação rápida: /export meu_ficheiro.csv"
        ),
    },
    "cli.active_profile": {"en": "Active profile", "pt": "Perfil ativo"},
    "cli.watchdog": {"en": "Watchdog", "pt": "Watchdog"},
    "cli.airline_filter": {"en": "Airline filter", "pt": "Filtro de companhias"},
    "cli.all_airlines": {"en": "all airlines", "pt": "todas as companhias"},
    "cli.current_filter": {"en": "Current filter", "pt": "Filtro atual"},
    "cli.filter_updated": {"en": "Filter updated", "pt": "Filtro atualizado"},
    "cli.filter_cleared": {"en": "Filter cleared", "pt": "Filtro limpo"},
    "cli.active_chain": {"en": "Active chain", "pt": "Cadeia ativa"},
    "cli.available_profiles": {"en": "Available profiles", "pt": "Perfis disponíveis"},
    "cli.profile_usage": {"en": "Use /profile fast|balanced|accurate to switch.", "pt": "Use /profile fast|balanced|accurate para mudar."},
    "cli.active": {"en": " (active)", "pt": " (ativo)"},
    "cli.profile_set": {"en": "Profile set to {profile}", "pt": "Perfil definido para {profile}"},
    "cli.active_watchdog": {"en": "Active watchdog sensitivity", "pt": "Sensibilidade watchdog ativa"},
    "cli.watchdog_usage": {"en": "Use /watchdog relaxed|normal|strict to switch.", "pt": "Use /watchdog relaxed|normal|strict para mudar."},
    "cli.watchdog_set": {"en": "Watchdog sensitivity set to {value}.", "pt": "Sensibilidade watchdog definida para {value}."},
    "cli.nothing_to_export": {"en": "Nothing to export yet. Run a query or /dashboard first.", "pt": "Nada para exportar. Execute uma consulta ou /dashboard primeiro."},
    "cli.exported_rows": {"en": "Exported {rows:,} rows to", "pt": "Exportadas {rows:,} linhas para"},
    "cli.not_enough_wars_data": {"en": "Not enough data for Airline Wars.", "pt": "Dados insuficientes para a Guerra das Companhias."},
    "cli.wars_cancelled": {"en": "Airline Wars cancelled.", "pt": "Guerra das Companhias cancelada."},
    "cli.export_tip": {"en": "Tip: use /export to save this result as CSV.", "pt": "Dica: use /export para guardar este resultado em CSV."},
    "cli.export_dashboard_tip": {"en": "Tip: use /export to save the dashboard view as CSV.", "pt": "Dica: use /export para guardar a vista do dashboard em CSV."},
    "cli.no_rows": {"en": "No rows returned.", "pt": "Nenhuma linha devolvida."},
    "cli.showing_rows": {"en": "Showing {shown} of {total} rows.", "pt": "A mostrar {shown} de {total} linhas."},
    "cli.model_attempts": {"en": "Model attempts", "pt": "Tentativas de modelo"},
    "cli.dashboard_kpis": {"en": "Dashboard KPIs", "pt": "KPIs do Dashboard"},
    "cli.total_flights": {"en": "Total Flights", "pt": "Total de Voos"},
    "cli.avg_latency": {"en": "Avg Latency", "pt": "Latência Média"},
    "cli.delayed_flights": {"en": "Delayed Flights", "pt": "Voos Atrasados"},
    "cli.total_cost": {"en": "Total Cost", "pt": "Custo Total"},
    "cli.choose": {"en": "Choose", "pt": "Escolher"},
    "cli.choose_multi": {"en": "Choose (comma-separated numbers or names)", "pt": "Escolher (números ou nomes separados por vírgula)"},
    "cli.choose_all_hint": {"en": " ('all' = select all, 'none' = clear)", "pt": " ('all' = selecionar tudo, 'none' = limpar)"},
    "cli.select_airlines": {"en": "Select airlines", "pt": "Selecionar companhias"},
    "cli.active_model_chain": {"en": "Active model chain", "pt": "Cadeia de modelos ativa"},
    "cli.sql_via": {"en": "SQL via {model}", "pt": "SQL via {model}"},
    "cli.query_result": {"en": "Query Result", "pt": "Resultado da Consulta"},
    "cli.cost_of_chaos": {"en": "Cost of Chaos", "pt": "Custo do Caos"},
    "cli.watchdog_preview": {"en": "Watchdog Preview", "pt": "Pré-visualização Watchdog"},
    "cli.data_not_found": {"en": "Data file not found: {path}", "pt": "Ficheiro de dados não encontrado: {path}"},
    "cli.startup_failed": {"en": "Startup failed: {error}", "pt": "Falha ao iniciar: {error}"},
}


def normalize_locale(locale: str | None) -> str:
    value = (locale or "en").lower().strip().replace("_", "-")
    if value.startswith("pt"):
        return "pt"
    return "en"


def configure_locale(locale: str | None = None) -> str:
    global _LOCALE
    if locale is None:
        locale = get_config().get("UI_LOCALE", "en")
    _LOCALE = normalize_locale(locale)
    return _LOCALE


def get_locale() -> str:
    return _LOCALE


def t(key: str, **kwargs: object) -> str:
    entry = TRANSLATIONS.get(key, {})
    text = entry.get(_LOCALE) or entry.get("en") or key
    return text.format(**kwargs) if kwargs else text


def profile_label(profile_key: str) -> str:
    return t(f"profile.{profile_key}")


def watchdog_label(sensitivity_key: str) -> str:
    return t(f"watchdog.{sensitivity_key}")
