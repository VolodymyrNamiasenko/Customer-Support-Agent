import os
import json
from typing import Any, Dict, List

import dspy

from backend.config import MODEL_NAME, OLLAMA_BASE_URL, OPTIMIZED_PROGRAM_PATH
from backend.pulse_signatures import PulseSupportSignature
from backend.hallucination_guard import validate_response


class PulseAssistant(dspy.Module):
    def __init__(self):
        super().__init__()
        self.generate_answer = dspy.ChainOfThought(PulseSupportSignature)

    def forward(self, context, question):
        return self.generate_answer(context=context, question=question)


_predictor = None


def get_predictor():
    global _predictor
    if _predictor is not None:
        return _predictor
    predictor = PulseAssistant()
    if os.path.exists(OPTIMIZED_PROGRAM_PATH):
        try:
            predictor.load(OPTIMIZED_PROGRAM_PATH)
        except Exception:
            pass
    _predictor = predictor
    return _predictor


def run_inference(context_text: str, question: str, temperature: float, max_tokens: int):
    lm = dspy.LM(
        MODEL_NAME,
        api_base=OLLAMA_BASE_URL,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    with dspy.context(lm=lm):
        predictor = get_predictor()
        result = predictor(context=context_text, question=question)
        reasoning = getattr(result, "reasoning", "")
        answer = result.answer
        check = validate_response(context=context_text, answer=answer, reasoning=reasoning)
        if not check.is_valid:
            answer = (
                "This entity is managed by SAP integration and cannot be manually "
                "created or modified in Pulse. Please check the SAP source system for changes."
            )
        return result, answer, check
