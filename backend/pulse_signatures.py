import dspy
from backend.rules_config import build_rules_text, load_rules_config


class PulseSupportSignature(dspy.Signature):
    """Dynamic rules are injected at import time from config/pulse_rules.json."""

    context = dspy.InputField(
        desc=(
            "Tagged snippets: [BLUEPRINT] for integration rules, [MANUAL] for UI procedures."
        )
    )
    history_summary = dspy.InputField(
        desc=(
            "Brief summary of recent conversation context (if available). "
            "Use it to resolve references like 'that' or 'what about sales orders'."
        )
    )
    question = dspy.InputField()
    reasoning = dspy.OutputField(
        desc=(
            "FIRST state integration status (Integrated or Manual). "
            "THEN explain your logic. If Integrated, explain WHY no steps are possible."
        )
    )
    answer = dspy.OutputField(
        desc=(
            "If entity is Integrated/Read-Only: state it cannot be manually created "
            "and explain the SAP sync process. If Manual: provide step-by-step guide "
            "with roles and navigation paths."
        )
    )


_rules_config = load_rules_config()
PulseSupportSignature.__doc__ = build_rules_text(_rules_config)
