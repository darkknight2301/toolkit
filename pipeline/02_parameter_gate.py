"""
pipeline/02_parameter_gate.py

Stage 2 — Parameter Gate (deterministic)

Loads the command KB entry, checks required parameters are present,
validates values against reference tables (e.g. CNS), applies defaults
for optional parameters, and produces the gate_result consumed by
stages 3 (SQ builder), 4 (CQ predictor) and 5 (output formatter).

Output shape:
  {
    "status":   "complete" | "missing" | "invalid" | "not_found" | "no_detailed_kb",
    "kb":       <command KB dict>  | None,
    "opcode_info": <entry from kb/tables/opcodes.json> | None,
    "resolved": { param_name: value_str, ... },
    "missing":  [ { "param": str, "question": str }, ... ],
    "invalid":  [ { "param": str, "value": str, "reason": str }, ... ]
  }
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CMD_DIR, KB_TABLES


def _load_command(command_name: str) -> dict | None:
    """Load command KB entry by name or alias (case-insensitive).
    Searches recursively so kb/commands/admin/*.json and kb/commands/io/*.json
    (or any future subfolder) are all picked up.
    """
    if not command_name:
        return None
    name_lower = command_name.lower()
    for f in CMD_DIR.glob("**/*.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        meta = d.get("meta", {})
        candidates = [meta.get("name", "")] + meta.get("aliases", [])
        if any(name_lower == c.lower() for c in candidates if c):
            return d
    return None


def _lookup_opcode_info(command_name: str) -> dict | None:
    """Look up a command by name in the canonical opcode reference table,
    regardless of whether a detailed kb/commands/*.json entry exists yet.
    Checks both 'admin' and 'nvm' opcode groups.
    """
    if not command_name:
        return None
    name_lower = command_name.lower()
    opcodes = KB_TABLES.get("opcodes", {})
    for group in ("admin", "nvm"):
        for opcode, info in opcodes.get(group, {}).items():
            if info.get("name", "").lower() == name_lower:
                return {"opcode": opcode, "group": group, **info}
    return None


def check_parameters(command_name: str, parameters: dict) -> dict:
    parameters = parameters or {}

    result = {
        "status":       "not_found",
        "kb":           None,
        "opcode_info":  None,
        "resolved":     {},
        "missing":      [],
        "invalid":      [],
    }

    kb = _load_command(command_name)

    if kb is None:
        # Not in the detailed KB — check whether it's at least a recognized
        # opcode/command name before giving up entirely. This distinction
        # matters: "Format NVM" being unsupported today is a very different
        # situation from the user typing a command that doesn't exist.
        opcode_info = _lookup_opcode_info(command_name)
        result["opcode_info"] = opcode_info

        if opcode_info is None:
            result["missing"].append({
                "param":    "command",
                "question": f"Command '{command_name}' was not found in the KB or the "
                            f"opcode reference table. Which NVMe command did you mean?"
            })
        else:
            result["status"] = "no_detailed_kb"
        return result

    result["kb"] = kb
    result["opcode_info"] = _lookup_opcode_info(kb.get("meta", {}).get("name", command_name))
    param_specs = kb.get("parameters", {})
    required    = kb.get("required_parameters", [])

    resolved = {}

    # ── Required parameters ─────────────────────────────────────────────
    for param in required:
        if param in parameters:
            resolved[param] = _normalise_hex(parameters[param])
        else:
            result["missing"].append({
                "param":    param,
                "question": param_specs.get(param, {}).get(
                    "desc", f"Please provide a value for '{param}'."
                )
            })

    # ── Optional parameters — use provided value or KB default ─────────
    for param, spec in param_specs.items():
        if param in required:
            continue
        if param in parameters:
            resolved[param] = _normalise_hex(parameters[param])
        elif "default" in spec:
            resolved[param] = spec["default"]

    if result["missing"]:
        result["status"] = "missing"
        return result

    # ── Command-specific validation: format checks only ─────────────────
    # NOTE: semantic checks (reserved CNS range, NSID-required-but-missing)
    # are intentionally NOT done here. Those are exactly what stage 4
    # (cq_predictor.status_rules) exists to predict — a syntactically valid
    # command that the *controller* would reject with a specific status
    # code. The gate only rejects input that can't be resolved at all.
    if kb.get("meta", {}).get("name", "").lower() == "identify" and "cns" in resolved:
        cns_val = resolved["cns"].lower()
        try:
            int(cns_val, 16)
        except ValueError:
            result["invalid"].append({
                "param":  "cns",
                "value":  cns_val,
                "reason": f"CNS value '{cns_val}' is not a valid hex number."
            })

    result["resolved"] = resolved

    if result["invalid"]:
        result["status"] = "invalid"
    else:
        result["status"] = "complete"

    return result


def _check_reserved_range(cns_val: str, cns_table: dict) -> str:
    try:
        cns_int = int(cns_val, 16)
    except ValueError:
        return f"CNS value '{cns_val}' is not a valid hex number."

    for r in cns_table.get("reserved_ranges", []):
        if int(r["start"], 16) <= cns_int <= int(r["end"], 16):
            return (f"CNS {cns_val} is in a Reserved range "
                    f"({r['start']}-{r['end']}). Controller will return "
                    f"'Invalid Field in Command'.")
    return f"CNS {cns_val} not found in CNS table — verify against spec."


def _normalise_hex(value: str) -> str:
    """Lowercase + ensure 0x prefix where the value already looks like hex."""
    if not isinstance(value, str):
        return value
    v = value.strip()
    if v.lower().startswith("0x"):
        return "0x" + v[2:].lower()
    return v


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print('Usage: python3 02_parameter_gate.py "<Command Name>" \'{"param": "value", ...}\'', file=sys.stderr)
        sys.exit(1)
    cmd_name = sys.argv[1]
    params = json.loads(sys.argv[2])
    r = check_parameters(cmd_name, params)
    print(json.dumps(r, indent=2))