"""
NVMe Helper — pipeline runner.

Chains stages 1-5. Stage modules are named with numeric prefixes
(01_intent_parser.py etc.) so they can't be imported with a normal
`import` statement — loaded here via importlib instead.

Usage:
    python3 run.py "identify controller"
    python3 run.py --mock-intent identify --param cns=0x01 -- "any text"
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

PIPELINE_DIR = Path(__file__).parent / "pipeline"


def _load_stage(filename: str):
    name = filename.replace(".py", "")
    spec = importlib.util.spec_from_file_location(name, PIPELINE_DIR / filename)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load pipeline stage: {filename}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


intent_parser     = _load_stage("01_intent_parser.py")
parameter_gate     = _load_stage("02_parameter_gate.py")
sq_builder         = _load_stage("03_sq_builder.py")
cq_predictor       = _load_stage("04_cq_predictor.py")
output_formatter   = _load_stage("05_output_formatter.py")


def run(user_query: str, mock_intent: dict | None = None, mode: str | None = None) -> str:
    # ── Stage 1: Intent ────────────────────────────────────────────────
    if mock_intent is not None:
        intent = mock_intent
        intent.setdefault("raw_intent", user_query)
    else:
        intent = intent_parser.parse_intent(user_query)
        intent.setdefault("raw_intent", user_query)

    if not intent.get("command"):
        return output_formatter.format_error(
            f"Could not determine command from query. "
            f"Reason: {intent.get('unknown_reason', 'unknown')}"
        )

    # ── Stage 2: Parameter gate ────────────────────────────────────────
    gate_result = parameter_gate.check_parameters(
        intent["command"], intent.get("parameters", {})
    )

    if gate_result["status"] == "not_found":
        return output_formatter.format_error(
            f"Command '{intent['command']}' not found in knowledge base."
        )
    if gate_result["status"] == "no_detailed_kb":
        return output_formatter.format_no_detailed_kb(intent, gate_result)
    if gate_result["status"] == "missing":
        return output_formatter.format_clarification(intent, gate_result)
    if gate_result["status"] == "invalid":
        return output_formatter.format_invalid(intent, gate_result)

    # ── Stage 3: SQ entry ───────────────────────────────────────────────
    sq_result = sq_builder.build_sq_entry(gate_result)

    # ── Stage 4: CQ entry + response prediction ─────────────────────────
    cq_result = cq_predictor.predict_cq(gate_result, sq_result)

    # ── Stage 5: Output ─────────────────────────────────────────────────
    return output_formatter.format_output(intent, gate_result, sq_result, cq_result, mode)


def _parse_kv(pairs: list[str]) -> dict:
    out = {}
    for p in pairs:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", default=None,
                     help="Natural language NVMe request, e.g. \"identify controller\"")
    ap.add_argument("--mock-command", help="Skip the LLM and use this command name directly")
    ap.add_argument("--param", action="append", default=[],
                     help="param=value pair, repeatable (used with --mock-command)")
    ap.add_argument("--mode", choices=["human", "json", "both"], default=None)
    args = ap.parse_args()

    if args.query is None:
        ap.error("query is required, e.g.: python3 run.py \"identify controller\"")
        sys.exit(1)  # unreachable — ap.error() already exits, but makes the
                      # control-flow explicit for static type checkers

    query: str = args.query

    mock = None
    if args.mock_command:
        mock = {
            "command":    args.mock_command,
            "parameters": _parse_kv(args.param),
            "confidence": 1.0,
        }

    print(run(query, mock_intent=mock, mode=args.mode))