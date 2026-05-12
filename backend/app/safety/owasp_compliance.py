OWASP_CONTROLS = {
    'LLM01_PROMPT_INJECTION': 'PromptIntegrityEnvelope',
    'LLM02_SENSITIVE_INFO_DISCLOSURE': 'DomainGateway',
    'LLM05_INSECURE_OUTPUT_HANDLING': 'Sandbox + output validation',
    'LLM06_EXCESSIVE_AGENCY': 'ActionSafetyGate + permissions',
    'LLM10_UNBOUNDED_CONSUMPTION': 'Rate limits + budgets',
}
def compliance_report():
    return {k: {'control': v, 'status': 'planned/implemented'} for k,v in OWASP_CONTROLS.items()}
