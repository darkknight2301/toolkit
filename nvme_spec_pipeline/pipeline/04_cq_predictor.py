"""
pipeline/04_cq_predictor.py

Stage 4: CQ Entry + Response Structure Predictor (fully deterministic)

Given the resolved parameters and command KB, predicts:
  - CQ entry (DWORD0-3) including status code
  - Expected response data structure (field layout)

Zero LLM calls. All status codes from KB status_rules or status_codes table.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import KB_TABLES, DEBUG


def predict_cq(gate_result: dict, sq_result: dict) -> dict:
    """
    Predict CQ entry and response structure.

    Returns:
      {
        "cq_entry": {
          "DWORD0": ...,
          "DWORD1": ...,
          "DWORD2": ...,
          "DWORD3": { "SCT": ..., "SC": ..., "meaning": ..., "DNR": ... }
        },
        "status": { "SCT": ..., "SC": ..., "meaning": ..., "DNR": ... },
        "response": { ... } | None,
        "notes": [ ... ]
      }
    """
    kb       = gate_result["kb"]
    resolved = gate_result["resolved"]
    invalid  = gate_result.get("invalid", [])

    cq_kb   = kb.get("cq_prediction", {})
    notes   = []

    # ── Determine status ───────────────────────────────────────────────────
    status = _resolve_status(resolved, invalid, cq_kb, notes)

    # ── Build CQ DWORD0-3 ─────────────────────────────────────────────────
    dw3_raw = _build_dword3(status)

    cq_entry = {
        "DWORD0": {
            "raw":  "0x00000000",
            "desc": cq_kb.get("DWORD0", "Command specific (0 for this command)")
        },
        "DWORD1": {
            "raw":  "0x00000000",
            "desc": "Reserved"
        },
        "DWORD2": {
            "raw":  "0x????",
            "desc": "SQHD[15:0]=SQ Head Pointer (controller-assigned), SQID[31:16]=SQ Identifier"
        },
        "DWORD3": {
            "raw":  dw3_raw,
            "fields": {
                "CID": "echoed from SQ entry CDW0[31:16]",
                "P":   "phase tag (toggled per cycle)",
                "SC":  status["SC"],
                "SCT": status["SCT"],
                "DNR": str(status.get("DNR", False)).lower()
            },
            "desc": f"Status: {status['meaning']} (SCT={status['SCT']} SC={status['SC']})"
        }
    }

    # ── Response structure ─────────────────────────────────────────────────
    response = None
    if status["SC"] == "0x00" and status["SCT"] == "0x0":
        response = _resolve_response(kb, resolved, notes)

    return {
        "cq_entry":  cq_entry,
        "status":    status,
        "response":  response,
        "notes":     notes
    }


def _resolve_status(resolved: dict, invalid: list, cq_kb: dict, notes: list) -> dict:
    """
    Walk status_rules in order — first matching condition wins.
    Falls back to success if nothing matches and no invalid params.
    """
    # Fast path: invalid parameter detected by gate
    if invalid:
        for inv in invalid:
            notes.append(f"Parameter validation: {inv['reason']}")
        return {
            "SCT":     "0x0",
            "SC":      "0x02",
            "meaning": "Invalid Field in Command",
            "DNR":     True,
            "source":  "parameter_validation"
        }

    status_rules = cq_kb.get("status_rules", [])

    # Evaluate each rule's condition deterministically
    for rule in status_rules:
        condition = rule.get("condition", "")
        if _evaluate_condition(condition, resolved):
            if DEBUG:
                print(f"[cq_predictor] Matched rule: {condition}", file=sys.stderr)
            return {
                "SCT":     rule.get("SCT", "0x0"),
                "SC":      rule.get("SC", "0x00"),
                "meaning": rule.get("meaning", ""),
                "DNR":     rule.get("DNR", False),
                "source":  "kb_status_rule",
                "rule":    condition,
                "note":    rule.get("note", "")
            }

    # Default: success
    notes.append("No error conditions matched — predicting Successful Completion.")
    return {
        "SCT":     "0x0",
        "SC":      "0x00",
        "meaning": "Successful Completion",
        "DNR":     False,
        "source":  "default"
    }


def _evaluate_condition(condition: str, resolved: dict) -> bool:
    """
    Evaluate a status_rule condition string against resolved parameters.
    Conditions are human-readable KB strings — we match on key phrases.
    This is intentionally simple: add more matchers as KB grows.
    """
    c = condition.lower()

    # ── CNS validity check ─────────────────────────────────────────────────
    if "cns value is valid" in c:
        cns = resolved.get("cns", "")
        return _cns_is_valid(cns) and _all_required_present(resolved)

    if "cns value is reserved" in c:
        cns = resolved.get("cns", "")
        return _cns_is_reserved(cns)

    # ── NSID checks ────────────────────────────────────────────────────────
    if "nsid is 0x0 or invalid" in c:
        nsid = resolved.get("nsid", "0x00000000")
        cns  = resolved.get("cns", "0x01")
        return _nsid_required_but_missing(nsid, cns)

    # Default: don't match (let next rule or default handle it)
    return False


def _cns_is_valid(cns: str) -> bool:
    if not cns:
        return False
    try:
        val = int(cns, 16) if cns.startswith("0x") else int(cns, 0)   
    except ValueError:
        return False

    # Reserved ranges per spec (from cns_values.json)
    reserved = list(range(0x09, 0x10)) + list(range(0x1A, 0xF0))
    return val not in reserved


def _cns_is_reserved(cns: str) -> bool:
    return not _cns_is_valid(cns)


def _nsid_required_but_missing(nsid: str, cns: str) -> bool:
    """CNS values that require a valid NSID (non-zero, non-broadcast)."""
    cns_requires_nsid = {"0x00", "0x03", "0x05", "0x08", "0x11", "0x12"}
    try:
        cns_norm = f"0x{int(cns, 0):02x}"
        nsid_int = int(nsid, 0) if nsid.startswith("0x") else int(nsid, 0)
    except (ValueError, TypeError):
        return False
    return cns_norm in cns_requires_nsid and nsid_int in (0x0, 0xFFFFFFFF)


def _all_required_present(resolved: dict) -> bool:
    return bool(resolved.get("cns"))


def _resolve_response(kb: dict, resolved: dict, notes: list) -> dict | None:
    """Return the expected response data structure for the predicted-success case."""
    resp_kb = kb.get("response", {})
    if not resp_kb or resp_kb.get("type") == "none":
        return None

    cns = resolved.get("cns", "").lower()
    # Normalise CNS to canonical hex key e.g. "0x01"
    try:
        cns_int = int(cns, 0)
        cns_key = f"0x{cns_int:02x}"
    except (ValueError, TypeError):
        cns_key = cns

    per_cns = resp_kb.get("per_cns", {})
    cns_resp = per_cns.get(cns_key) or per_cns.get(cns_key.upper())

    base = {
        "type":       resp_kb.get("type"),
        "size_bytes": resp_kb.get("size_bytes"),
        "note":       resp_kb.get("note", "")
    }

    if cns_resp:
        base["desc"]     = cns_resp.get("desc", "")
        base["spec_ref"] = cns_resp.get("spec_ref", "")
        base["fields"]   = cns_resp.get("fields", {})
    else:
        notes.append(
            f"No per-CNS response structure defined for CNS={cns}. "
            f"Add to kb/commands/{kb['meta']['name'].lower()}.json → response.per_cns."
        )

    return base


def _build_dword3(status: dict) -> str:
    """Compute approximate raw DWORD3 value for display (CID=0, P=0, status bits)."""
    try:
        sc  = int(status["SC"], 16)
        sct = int(status["SCT"], 16)
        dnr = 1 if status.get("DNR") else 0
        # DWORD3: [16]=P=0, [24:17]=SC, [27:25]=SCT, [31]=DNR
        raw = (sc << 17) | (sct << 25) | (dnr << 31)
        return f"0x{raw:08X}"
    except Exception:
        return "0x????????"


# ── CLI entrypoint ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Expects two JSON args: gate_result and sq_result
    if len(sys.argv) > 2:
        gate_result = json.loads(sys.argv[1])
        sq_result   = json.loads(sys.argv[2])
    else:
        data = json.loads(sys.stdin.read())
        gate_result = data["gate"]
        sq_result   = data["sq"]

    result = predict_cq(gate_result, sq_result)
    print(json.dumps(result, indent=2))