"""Acronous LLM — fuzzy logic engine.

Implements Mamdani-style fuzzy inference on CPU:
  * Membership functions: triangular, trapezoidal, gaussian
  * Rule base with AND/OR (min/max) and defuzzification (centroid)
Used to blend RAG confidence, model certainty and safety signals into a
single "should I answer from memory / generate / refuse" decision, which
makes the brain more robust than a hard threshold.
"""
import math
from typing import Callable, Dict, List, Tuple


def tri(x, a, b, c):
    if x <= a or x >= c:
        return 0.0
    if a < x <= b:
        return (x - a) / max(b - a, 1e-9)
    return (c - x) / max(c - b, 1e-9)


def trap(x, a, b, c, d):
    if x <= a or x >= d:
        return 0.0
    if a < x <= b:
        return (x - a) / max(b - a, 1e-9)
    if b < x <= c:
        return 1.0
    return (d - x) / max(d - c, 1e-9)


def gauss(x, mean, sigma):
    if sigma <= 0:
        return 0.0
    return math.exp(-((x - mean) ** 2) / (2 * sigma * sigma))


class FuzzyVariable:
    def __init__(self, name: str, universe: Tuple[float, float]):
        self.name = name
        self.lo, self.hi = universe
        self.sets: Dict[str, Callable[[float], float]] = {}

    def add_set(self, label: str, mf: Callable[[float], float]):
        self.sets[label] = mf
        return self

    def fuzzify(self, value: float) -> Dict[str, float]:
        v = min(max(value, self.lo), self.hi)
        return {label: float(mf(v)) for label, mf in self.sets.items()}


class FuzzyRule:
    def __init__(self, antecedents: List[Tuple[str, str]], consequent: Tuple[str, str],
                 weight: float = 1.0, op: str = "and"):
        self.antecedents = antecedents  # [(var_name, set_label), ...]
        self.consequent = consequent     # (var_name, set_label)
        self.weight = weight
        self.op = op

    def fire(self, fuzzified: Dict[str, Dict[str, float]]) -> float:
        vals = []
        for var, label in self.antecedents:
            vals.append(fuzzified.get(var, {}).get(label, 0.0))
        if not vals:
            return 0.0
        if self.op == "and":
            strength = min(vals)
        else:
            strength = max(vals)
        return float(strength * self.weight)


class FuzzyEngine:
    """Mamdani fuzzy inference system with centroid defuzzification."""

    def __init__(self):
        self.inputs: Dict[str, FuzzyVariable] = {}
        self.outputs: Dict[str, FuzzyVariable] = {}
        self.rules: List[FuzzyRule] = []

    def add_input(self, var: FuzzyVariable):
        self.inputs[var.name] = var

    def add_output(self, var: FuzzyVariable):
        self.outputs[var.name] = var

    def add_rule(self, rule: FuzzyRule):
        self.rules.append(rule)

    def infer(self, values: Dict[str, float]) -> Dict[str, float]:
        fuzzified = {name: var.fuzzify(values.get(name, 0.0)) for name, var in self.inputs.items()}
        # aggregate consequent membership
        agg: Dict[str, Dict[str, float]] = {name: {s: 0.0 for s in var.sets} for name, var in self.outputs.items()}
        for rule in self.rules:
            strength = rule.fire(fuzzified)
            out_var, out_set = rule.consequent
            if out_var in agg and out_set in agg[out_var]:
                agg[out_var][out_set] = max(agg[out_var][out_set], strength)

        # centroid defuzzification over a sampled universe
        result = {}
        for name, var in self.outputs.items():
            lo, hi = var.lo, var.hi
            num = 0.0
            den = 0.0
            n = 200
            for i in range(n + 1):
                x = lo + (hi - lo) * i / n
                # membership = max of all sets scaled by aggregated strength
                mu = 0.0
                for label, mf in var.sets.items():
                    mu = max(mu, min(mf(x), agg[name].get(label, 0.0)))
                num += x * mu
                den += mu
            result[name] = (num / den) if den > 1e-9 else (lo + hi) / 2.0
        return result


def build_default_engine() -> FuzzyEngine:
    """A ready-to-use engine blending RAG confidence / model certainty / safety."""
    eng = FuzzyEngine()
    rag = FuzzyVariable("rag_confidence", (0.0, 1.0))
    rag.add_set("low", lambda x: tri(x, 0.0, 0.0, 0.35))
    rag.add_set("medium", lambda x: tri(x, 0.25, 0.5, 0.75))
    rag.add_set("high", lambda x: trap(x, 0.65, 0.85, 1.0, 1.05))
    eng.add_input(rag)

    cert = FuzzyVariable("model_certainty", (0.0, 1.0))
    cert.add_set("low", lambda x: tri(x, 0.0, 0.0, 0.4))
    cert.add_set("high", lambda x: trap(x, 0.6, 0.8, 1.0, 1.05))
    eng.add_input(cert)

    safety = FuzzyVariable("safety", (0.0, 1.0))
    safety.add_set("risky", lambda x: tri(x, 0.0, 0.0, 0.4))
    safety.add_set("safe", lambda x: trap(x, 0.6, 0.8, 1.0, 1.05))
    eng.add_input(safety)

    out = FuzzyVariable("action", (0.0, 1.0))  # 0=refuse, 0.5=generate, 1.0=memory
    out.add_set("refuse", lambda x: tri(x, 0.0, 0.0, 0.34))
    out.add_set("generate", lambda x: tri(x, 0.33, 0.5, 0.67))
    out.add_set("memory", lambda x: trap(x, 0.66, 0.83, 1.0, 1.05))
    eng.add_output(out)

    eng.add_rule(FuzzyRule([("rag_confidence", "high"), ("safety", "safe")], ("action", "memory"), 1.0))
    eng.add_rule(FuzzyRule([("rag_confidence", "low")], ("action", "generate"), 0.8))
    eng.add_rule(FuzzyRule([("safety", "risky")], ("action", "refuse"), 1.0))
    eng.add_rule(FuzzyRule([("model_certainty", "high"), ("rag_confidence", "medium")], ("action", "generate"), 0.7))
    return eng
