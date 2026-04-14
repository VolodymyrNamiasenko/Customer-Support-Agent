import re
from dataclasses import dataclass, field
from typing import List
from rules_config import get_signal_list, load_rules_config

_rules_config = load_rules_config()
INTEGRATION_SIGNALS = get_signal_list(_rules_config, "integration_signals")
NON_CREATION_SIGNALS = get_signal_list(_rules_config, "non_creation_signals")
HALLUCINATED_ACTIONS = get_signal_list(_rules_config, "hallucinated_actions")
ENTITY_CREATION_LANGUAGE = get_signal_list(_rules_config, "entity_creation_language")
SAFE_RESPONSE_SIGNALS = get_signal_list(_rules_config, "safe_response_signals")
@dataclass
class ValidationResult:
    is_valid: bool
    entity_is_integrated: bool
    has_non_creation_signal: bool
    matched_signals: List[str] = field(default_factory=list)
    matched_non_creation: List[str] = field(default_factory=list)
    matched_patterns: List[str] = field(default_factory=list)
    matched_entity_creation: List[str] = field(default_factory=list)
    matched_safe_signals: List[str] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)
    warning: str = ""


def _find_regex_matches(patterns: list, text: str) -> List[str]:
    """Return list of pattern strings that matched in text."""
    matched = []
    for pattern in patterns:
        clean = pattern.replace("\n", "").replace("  ", " ")
        if re.search(clean, text, re.IGNORECASE):
            matched.append(clean)
    return matched


def validate_response(
    context: str, answer: str, reasoning: str = ""
) -> ValidationResult:
    """
    Post-inference hallucination check.

    Two-layer detection:
      Layer 1: Classic integration keywords (INTEGRATION_SIGNALS)
      Layer 2: Soft non-creation signals via regex (NON_CREATION_SIGNALS)

    If EITHER layer fires → entity should not be manually created.
    Then check the model's output for hallucinated creation actions.
    """
    ctx_lower = context.lower()
    full_output = f"{reasoning} {answer}".lower()

    # ── Layer 1: keyword signals ──
    matched_signals = [s for s in INTEGRATION_SIGNALS if s in ctx_lower]
    is_integrated = bool(matched_signals)

    # ── Layer 2: regex-based soft signals ──
    matched_non_creation = _find_regex_matches(NON_CREATION_SIGNALS, ctx_lower)
    has_non_creation_signal = bool(matched_non_creation)

    # If neither layer fires, allow the response through
    entity_blocked = is_integrated or has_non_creation_signal

    if not entity_blocked:
        return ValidationResult(
            is_valid=True,
            entity_is_integrated=False,
            has_non_creation_signal=False,
            matched_signals=[],
            matched_non_creation=[],
            matched_patterns=[],
            violations=[],
            warning="",
        )

    # ── Determine if answer explicitly marks creation as impossible ──
    matched_safe_signals = _find_regex_matches(SAFE_RESPONSE_SIGNALS, full_output)
    answer_is_safe = bool(matched_safe_signals)

    # ── Check output for hallucinated creation actions (for diagnostics) ──
    matched_patterns = _find_regex_matches(HALLUCINATED_ACTIONS, full_output)
    matched_entity_creation = _find_regex_matches(ENTITY_CREATION_LANGUAGE, full_output)

    # New logic: If entity is blocked and answer does NOT explicitly say creation is not possible, block it.
    if entity_blocked and not answer_is_safe:
        trigger_source = []
        if is_integrated:
            trigger_source.append(
                f"integration signals: {matched_signals[:3]}"
            )
        if has_non_creation_signal:
            trigger_source.append(
                f"non-creation signals: {matched_non_creation[:3]}"
            )
        warning = (
            f"BLOCKED: Context contains {' and '.join(trigger_source)}, "
            "but the response does not explicitly state that creation is not possible. "
            "This is treated as a hallucination risk."
        )
        return ValidationResult(
            is_valid=False,
            entity_is_integrated=is_integrated,
            has_non_creation_signal=has_non_creation_signal,
            matched_signals=matched_signals,
            matched_non_creation=matched_non_creation,
            matched_patterns=matched_patterns,
            matched_entity_creation=matched_entity_creation,
            matched_safe_signals=matched_safe_signals,
            violations=matched_patterns + matched_entity_creation,
            warning=warning,
        )

    # Entity is integrated/blocked but model didn't hallucinate actions — OK
    return ValidationResult(
        is_valid=True,
        entity_is_integrated=is_integrated,
        has_non_creation_signal=has_non_creation_signal,
        matched_signals=matched_signals,
        matched_non_creation=matched_non_creation,
        matched_patterns=[],
        matched_entity_creation=[],
        matched_safe_signals=matched_safe_signals,
        violations=[],
        warning="",
    )


def hallucination_metric(example, pred, trace=None):
    """
    DSPy-compatible metric. Returns 1.0 if answer is
    safe, 0.0 if it contains hallucinated actions for
    integrated entities.
    """
    check = validate_response(
        context=example.context,
        answer=pred.answer,
        reasoning=getattr(pred, "reasoning", ""),
    )
    return 1.0 if check.is_valid else 0.0


# ──────────────────────────────────────────────────────────
# Quick self-test
# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Test case: Sales Order — should be BLOCKED
    test_context = (
        '"Sales orders" page divided into two main areas; '
        "Top area is the Headers : contains a list of the selected Sales orders... "
        "Note : there is no attribute/parameter which track who created the "
        "sales order, as these orders will not be created on Pules digital."
    )

    test_answer_bad = (
        "To add a new sales order, follow these steps: "
        "1. Open the Sales Orders management directory by navigating to "
        "Manufacturing → Sales & Operations Planning → FG orders → Sales orders. "
        "2. Click on the 'New' button to create a new sales order. "
        "3. Select the sales channel and sales segment from the drop-down menus. "
        "4. Enter the customer, product, and quantity. "
        "5. The system will automatically generate a sales order number. "
        "6. Click Save to save the new sales order."
    )

    test_answer_good = (
        "Sales orders cannot be manually created in Pulse Digital. "
        "As noted in the documentation, these orders are imported from SAP. "
        "To view existing sales orders, navigate to Manufacturing → "
        "Sales & Operations Planning → FG orders → Sales orders."
    )

    print("=" * 60)
    print("TEST 1: Hallucinated creation steps (should be BLOCKED)")
    print("=" * 60)
    result1 = validate_response(test_context, test_answer_bad)
    print(f"  is_valid:              {result1.is_valid}")
    print(f"  entity_is_integrated:  {result1.entity_is_integrated}")
    print(f"  has_non_creation_signal: {result1.has_non_creation_signal}")
    print(f"  matched_non_creation:  {result1.matched_non_creation[:2]}")
    print(f"  violations:            {result1.violations[:3]}")
    print(f"  warning:               {result1.warning[:120]}...")
    print()

    print("=" * 60)
    print("TEST 2: Correct answer (should PASS)")
    print("=" * 60)
    result2 = validate_response(test_context, test_answer_good)
    print(f"  is_valid:              {result2.is_valid}")
    print(f"  has_non_creation_signal: {result2.has_non_creation_signal}")
    print(f"  violations:            {result2.violations}")
    print()

    # Test case: Material Categories — classic integration (should BLOCK bad answer)
    test_context_blueprint = (
        "Material Categories — SAP Interface: Material master Int. — "
        "Integration approach: SAP CPI interface — Master system: SAP — "
        "Slave system: Pulse Digital — Dataflow: SAP to Pulse Digital"
    )

    test_answer_blueprint_bad = (
        "To create a new material category: "
        "1. Navigate to MDM → Material Categories. "
        "2. Click the Add button to create a new category."
    )

    print("=" * 60)
    print("TEST 3: Blueprint integration — bad answer (should be BLOCKED)")
    print("=" * 60)
    result3 = validate_response(test_context_blueprint, test_answer_blueprint_bad)
    print(f"  is_valid:              {result3.is_valid}")
    print(f"  entity_is_integrated:  {result3.entity_is_integrated}")
    print(f"  matched_signals:       {result3.matched_signals[:3]}")
    print(f"  violations:            {result3.violations[:3]}")
    print(f"  warning:               {result3.warning[:120]}...")
