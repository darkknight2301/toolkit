"""
pipeline/03_sq_builder.py

Stage 3: SQ Entry Builder (fully deterministic, zero LLM calls)

Fills the 16 CDW (Command Descriptor Words) of the NVMe SQ entry
using the command KB layout + resolved parameters from the gate stage.

Output:
  {
    "sq_entry": {
      "CDW0":  { "raw": "0x00000006", "fields": { "OPC": "0x06", "CID": "caller-assigned", ... } },
      "CDW1":  { "raw": "0x00000000", "desc": "NSID=0x0" },
      ...
      "CDW15": { "raw": "0x00000000" }
    },
    "summary": "Identify Controller (CNS=0x01, NSID=0x0)"
  }
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DEBUG


def build_sq_entry(gate_result: dict) -> dict:
    """
    Build the SQ entry from gate result.

    gate_result must have status="complete" and contain:
      - kb: command KB dict
      - resolved: dict of param_name → value string
      - intent: original intent dict
    """
    assert gate_result["status"] in ("complete", "invalid"), \
        f"SQ builder called with gate status={gate_result['status']}"

    kb       = gate_result["kb"]
    resolved = gate_result["resolved"]
    meta     = kb.get("meta", {})
    sq_kb    = kb.get("sq", {})

    cdws = {}

    # ── CDW0 — always from meta opcode ────────────────────────────────────
    opc = meta.get("opcode", "0x00")
    cdw0_kb = sq_kb.get("CDW0", {})
    cdws["CDW0"] = {
        "raw": _build_cdw0_raw(opc),
        "fields": {
            "OPC":  {"bits": "[7:0]",   "value": opc,                              "desc": "Opcode"},
            "FUSE": {"bits": "[9:8]",   "value": cdw0_kb.get("FUSE", "0x0"),        "desc": "Fused Operation"},
            "PSDT": {"bits": "[15:14]", "value": cdw0_kb.get("PSDT", "0x0"),        "desc": "PRP or SGL for Data Transfer"},
            "CID":  {"bits": "[31:16]", "value": "caller-assigned",                "desc": "Command Identifier"}
        },
        "desc": f"Opcode={opc} ({meta.get('name','')}), normal (non-fused), PRP data transfer"
    }

    # ── CDW1 — NSID ────────────────────────────────────────────────────────
    nsid = resolved.get("nsid", "0x00000000")
    cdws["CDW1"] = {
        "raw":  _to_hex32(nsid),
        "desc": f"NSID={nsid}"
    }

    # ── CDW2, CDW3 — Reserved ──────────────────────────────────────────────
    cdws["CDW2"] = {"raw": "0x00000000", "desc": "Reserved"}
    cdws["CDW3"] = {"raw": "0x00000000", "desc": "Reserved"}

    # ── CDW4, CDW5 — MPTR ─────────────────────────────────────────────────
    cdws["CDW4"] = {"raw": "0x00000000", "desc": "MPTR lower (no metadata)"}
    cdws["CDW5"] = {"raw": "0x00000000", "desc": "MPTR upper (no metadata)"}

    # ── CDW6-9 — PRP / data pointer ────────────────────────────────────────
    cdws["CDW6"] = {"raw": "<PRP1_LO>", "desc": "PRP1 lower 32b — host buffer physical address"}
    cdws["CDW7"] = {"raw": "<PRP1_HI>", "desc": "PRP1 upper 32b"}
    cdws["CDW8"] = {"raw": "0x00000000", "desc": "PRP2 lower (0 if single 4KB page)"}
    cdws["CDW9"] = {"raw": "0x00000000", "desc": "PRP2 upper"}

    # ── CDW10 onwards — command-specific ───────────────────────────────────
    for cdw_name in ["CDW10", "CDW11", "CDW12", "CDW13", "CDW14", "CDW15"]:
        cdw_kb = sq_kb.get(cdw_name)

        if cdw_kb is None:
            cdws[cdw_name] = {"raw": "0x00000000", "desc": "Not used"}
            continue

        if isinstance(cdw_kb, str):
            # Fixed string description (e.g. "0x00000000")
            cdws[cdw_name] = {"raw": cdw_kb if cdw_kb.startswith("0x") else "0x00000000",
                               "desc": cdw_kb}
            continue

        # Structured CDW with named bit fields
        fields, raw = _build_cdw_fields(cdw_kb, resolved)
        cdws[cdw_name] = {
            "raw":    _to_hex32(str(raw)),
            "fields": fields,
            "desc":   _fields_to_desc(fields)
        }

    # ── Summary line ───────────────────────────────────────────────────────
    summary = _build_summary(meta, resolved)

    return {
        "sq_entry": cdws,
        "summary":  summary,
        "command":  meta.get("name", ""),
        "opcode":   opc,
        "queue":    meta.get("queue", "Admin"),
        "spec_ref": meta.get("spec_ref", "")
    }


def _build_cdw_fields(cdw_kb: dict, resolved: dict) -> tuple[dict, int]:
    """
    Parse CDW field definitions from KB, substitute resolved param values.
    Returns (fields dict for output, raw integer value of the CDW).
    """
    fields = {}
    raw = 0

    for field_name, field_def in cdw_kb.items():
        if field_name.startswith("_"):
            continue  # skip comments

        if not isinstance(field_def, dict):
            continue

        bits = field_def.get("bits")
        # Normalise single-bit fields: KB authors (and the LLM extractor)
        # sometimes write a 1-element list like [8] for a single-bit field
        # instead of the expected [hi, lo] pair. Treat [n] as [n, n].
        if isinstance(bits, list) and len(bits) == 1:
            bits = [bits[0], bits[0]]

        value_key = field_def.get("value", "0x0")

        # Resolve value — either a param name or a fixed hex string
        if value_key in resolved:
            value_str = resolved[value_key]
        elif value_key.startswith("0x") or value_key.isdigit():
            value_str = value_key
        elif value_key == "caller-assigned":
            value_str = "caller-assigned"
        else:
            value_str = "0x0"

        fields[field_name] = {
            "bits":  f"[{bits[0]}:{bits[1]}]" if bits and len(bits) >= 2 else "?",
            "value": value_str,
            "desc":  field_def.get("desc", "")
        }

        # Pack into raw integer if we have a numeric value and bit range
        if bits and len(bits) >= 2 and value_str not in ("caller-assigned", "0x0"):
            try:
                int_val = int(value_str, 16) if value_str.startswith("0x") else int(value_str, 0)
                lo = bits[1]
                hi = bits[0]
                mask = (1 << (hi - lo + 1)) - 1
                raw |= (int_val & mask) << lo
            except (ValueError, TypeError):
                pass

    return fields, raw


def _build_cdw0_raw(opc: str) -> str:
    try:
        opc_int = int(opc, 16)
        return f"0x{opc_int:08X}"
    except ValueError:
        return "0x00000000"


def _to_hex32(value: str) -> str:
    """Convert a value string to 8-digit hex (CDW raw format)."""
    if value in ("<PRP1_LO>", "<PRP1_HI>", "caller-assigned"):
        return value
    try:
        if value.startswith("0x") or value.startswith("0X"):
            return f"0x{int(value, 16):08X}"
        return f"0x{int(value, 0):08X}"
    except (ValueError, TypeError):
        return "0x00000000"


def _fields_to_desc(fields: dict) -> str:
    parts = []
    for name, fdef in fields.items():
        if not name.startswith("reserved"):
            parts.append(f"{name}={fdef['value']}")
    return ", ".join(parts)


def _build_summary(meta: dict, resolved: dict) -> str:
    name = meta.get("name", "")
    parts = [name]
    for k, v in resolved.items():
        if v not in ("0x00000000", "0x0000", "0x0"):
            parts.append(f"{k.upper()}={v}")
        elif k in ("cns",):  # always show CNS even if 0
            parts.append(f"{k.upper()}={v}")
    return " ".join(parts)


# ── CLI entrypoint ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) > 1:
        gate_result = json.loads(" ".join(sys.argv[1:]))
    else:
        gate_result = json.loads(sys.stdin.read())

    result = build_sq_entry(gate_result)
    print(json.dumps(result, indent=2))