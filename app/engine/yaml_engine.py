"""YAML guardrail pack: load, validate, evaluate.

Rules are data (SPEC.md): one YAML file with a closed operator vocabulary —
exists, absent, eq, contains, open_port. The pack is loaded from
GUARDRAIL_RULES_FILE (default: <repo>/rules.yaml) on every scan, so edits and
overrides need no restart and never a code change.

An invalid pack (unknown operator, missing field, bad severity, duplicate id)
raises RulePackError at load time — a startup error by design.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from .. import config
from .parser import ParsedProject, TFResource

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}
SEVERITY_WEIGHT = {"CRITICAL": 10, "HIGH": 5, "MEDIUM": 2, "LOW": 1}  # spec weights

OPERATORS = ("exists", "absent", "eq", "contains", "open_port")

RULE_FIELDS = {"id", "severity", "resource_type", "check", "message", "remediation"}

_CLAUSE_KEYS = {
    "exists": {"op", "attr"},
    "absent": {"op", "attr", "companion_type"},
    "eq": {"op", "attr", "value"},
    "contains": {"op", "attr", "value"},
    "open_port": {"op", "port", "cidr"},
}


class RulePackError(Exception):
    """Invalid rules file — raised at load time."""


@dataclass(frozen=True)
class Clause:
    op: str
    attr: Optional[str] = None
    value: Any = None
    companion_type: Optional[str] = None
    port: Optional[int] = None
    cidr: Optional[str] = None


@dataclass(frozen=True)
class YamlRule:
    id: str
    severity: str
    resource_type: tuple
    check: tuple  # of Clause, any-of semantics
    message: str
    remediation: str


def rules_path() -> Path:
    return Path(os.environ.get("GUARDRAIL_RULES_FILE", str(config.BASE_DIR / "rules.yaml")))


def _as_tuple(v: Any) -> tuple:
    return tuple(v) if isinstance(v, list) else (v,)


def _parse_clause(raw: Any, rule_id: str) -> Clause:
    if not isinstance(raw, dict) or "op" not in raw:
        raise RulePackError(f"rule {rule_id}: each check clause must be a mapping with an 'op'")
    op = raw["op"]
    if op not in OPERATORS:
        raise RulePackError(
            f"rule {rule_id}: unknown operator {op!r}; allowed: {', '.join(OPERATORS)}")
    extra = set(raw) - _CLAUSE_KEYS[op]
    if extra:
        raise RulePackError(f"rule {rule_id}: operator {op!r} does not take {sorted(extra)}")
    if op == "open_port":
        if not isinstance(raw.get("port"), int) or not isinstance(raw.get("cidr"), str):
            raise RulePackError(f"rule {rule_id}: open_port needs integer 'port' and string 'cidr'")
        return Clause(op=op, port=raw["port"], cidr=raw["cidr"])
    if not isinstance(raw.get("attr"), str):
        raise RulePackError(f"rule {rule_id}: operator {op!r} needs a string 'attr'")
    if op in ("eq", "contains") and "value" not in raw:
        raise RulePackError(f"rule {rule_id}: operator {op!r} needs a 'value'")
    return Clause(op=op, attr=raw["attr"], value=raw.get("value"),
                  companion_type=raw.get("companion_type"))


def load_rules(path: Optional[Path] = None) -> list:
    path = path or rules_path()
    if not path.is_file():
        raise RulePackError(f"rules file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RulePackError(f"rules file is not valid YAML: {exc}") from exc
    if not isinstance(data, list) or not data:
        raise RulePackError("rules file must be a non-empty YAML list of rules")

    rules: list[YamlRule] = []
    seen: set = set()
    for raw in data:
        if not isinstance(raw, dict):
            raise RulePackError("every rule must be a mapping")
        rid = raw.get("id", "?")
        missing = RULE_FIELDS - set(raw)
        if missing:
            raise RulePackError(f"rule {rid}: missing fields {sorted(missing)}")
        extra = set(raw) - RULE_FIELDS
        if extra:
            raise RulePackError(f"rule {rid}: unexpected fields {sorted(extra)}")
        if rid in seen:
            raise RulePackError(f"duplicate rule id {rid}")
        seen.add(rid)
        if raw["severity"] not in SEVERITIES:
            raise RulePackError(f"rule {rid}: severity must be one of {', '.join(SEVERITIES)}")
        if not isinstance(raw["check"], list) or not raw["check"]:
            raise RulePackError(f"rule {rid}: 'check' must be a non-empty list of clauses")
        rules.append(YamlRule(
            id=str(rid),
            severity=raw["severity"],
            resource_type=_as_tuple(raw["resource_type"]),
            check=tuple(_parse_clause(c, rid) for c in raw["check"]),
            message=str(raw["message"]),
            remediation=str(raw["remediation"]),
        ))
    return rules


# ---------------------------------------------------------------------------
# clause evaluation

def _blocks(value: Any) -> list:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [b for b in value if isinstance(b, dict)]
    return []


def _ingress_blocks(res: TFResource) -> list:
    if res.type == "aws_security_group":
        return _blocks(res.attrs.get("ingress"))
    if res.type == "aws_security_group_rule":
        return [res.attrs] if str(res.attrs.get("type", "")).lower() == "ingress" else []
    if res.type == "aws_vpc_security_group_ingress_rule":
        return [res.attrs]
    return []


def _covers_port(block: dict, port: int) -> bool:
    proto = str(block.get("protocol", block.get("ip_protocol", "tcp"))).lower()
    if proto in ("-1", "all"):
        return True
    if proto not in ("tcp", "6"):
        return False
    try:
        return int(block.get("from_port")) <= port <= int(block.get("to_port"))
    except (TypeError, ValueError):
        return False


def _block_cidrs(block: dict) -> list:
    out: list = []
    for key in ("cidr_blocks", "ipv6_cidr_blocks"):
        v = block.get(key)
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            out.extend(str(c) for c in v)
    for key in ("cidr_ipv4", "cidr_ipv6"):
        v = block.get(key)
        if isinstance(v, str):
            out.append(v)
    return out


def _eval_open_port(clause: Clause, res: TFResource) -> tuple:
    for block in _ingress_blocks(res):
        if clause.cidr in _block_cidrs(block) and _covers_port(block, clause.port):
            return True, clause.cidr
    return False, None


def evaluate_clause(clause: Clause, res: TFResource, project: ParsedProject) -> tuple:
    """-> (matched, evidence_hint). Slice 1 implements open_port; the four
    scalar operators are valid vocabulary but their implementations land in
    slice 2 with the rules that use them."""
    if clause.op == "open_port":
        return _eval_open_port(clause, res)
    raise RulePackError(
        f"operator {clause.op!r} is not implemented yet (arrives in slice 2); "
        "no rule in the current pack may use it")
