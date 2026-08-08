"""Terraform HCL parsing -> normalized resource model.

Static analysis via python-hcl2: no terraform binary and no cloud
credentials are required to audit a configuration.

python-hcl2 8.x quirks handled here:
- string literals arrive with their surrounding quote characters -> stripped
- heredoc values arrive as '"<<LABEL\\n...\\nLABEL"' -> unwrapped to the body
- bare expressions arrive as "${...}" (kept: rules treat ${ as "not a literal")
- __is_block__ / __comments__ metadata keys are injected -> removed
- loads() no longer reports line numbers -> restored via a bounded scan for
  block headers (SPEC.md provenance fallback; no hand-built parser). The
  header scan also yields each block's span (start..end line), which the
  scanner uses to pull evidence snippets from the source without ever reading
  outside the block.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import hcl2

from .. import config

_HEREDOC = re.compile(r"^<<-?(\w+)\r?\n(.*)\r?\n[ \t]*\1[ \t]*$", re.S)
_BLOCK_HEADER = re.compile(r'^[ \t]*(resource|data)[ \t]+"([^"]+)"[ \t]+"([^"]+)"', re.M)


@dataclass
class TFResource:
    mode: str                     # "resource" or "data"
    type: str
    name: str
    attrs: dict[str, Any]
    file: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None

    @property
    def address(self) -> str:
        prefix = "data." if self.mode == "data" else ""
        return f"{prefix}{self.type}.{self.name}"


@dataclass
class ParsedProject:
    resources: list[TFResource] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    sources: dict = field(default_factory=dict)     # file -> raw text (evidence scans)
    errors: list[dict] = field(default_factory=list)

    def managed(self, *types: str) -> list[TFResource]:
        """Managed (non-data) resources, optionally filtered by type."""
        out = [r for r in self.resources if r.mode == "resource"]
        if types:
            out = [r for r in out if r.type in types]
        return out


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        inner = s[1:-1]
        m = _HEREDOC.match(inner)
        if m:
            return m.group(2)
        return inner.replace('\\"', '"')
    return s


def _normalize(value: Any) -> Any:
    """Strip hcl2 metadata keys and quote wrappers, recursively."""
    if isinstance(value, dict):
        return {
            (_strip_quotes(k) if isinstance(k, str) else k): _normalize(v)
            for k, v in value.items()
            if not (isinstance(k, str) and k.startswith("__"))
        }
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, str):
        return _strip_quotes(value)
    return value


def _block_spans(text: str) -> dict:
    """(mode, type, name) -> (start_line, end_line), 1-based inclusive.

    A block's span runs from its header to the line before the next top-level
    block header (or end of file) — the bound for evidence scans.
    """
    headers = [
        (text.count("\n", 0, m.start()) + 1, (m.group(1), m.group(2), m.group(3)))
        for m in _BLOCK_HEADER.finditer(text)
    ]
    total = text.count("\n") + 1
    spans: dict = {}
    for i, (line, key) in enumerate(headers):
        end = headers[i + 1][0] - 1 if i + 1 < len(headers) else total
        spans.setdefault(key, (line, end))
    return spans


def parse_files(named_files: Iterable[tuple[str, str]]) -> ParsedProject:
    project = ParsedProject()
    for path, text in named_files:
        project.files.append(path)
        # CRLF/CR -> LF before hcl2 sees the text: python-hcl2 chokes on \r,
        # and upload bytes arrive verbatim (Saturday finding 1). Normalizing
        # here protects every current and future input path.
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not text.endswith("\n"):
            text += "\n"
        project.sources[path] = text
        try:
            doc = hcl2.loads(text)
        except Exception as exc:  # lark surfaces many exception types
            project.errors.append({"file": path, "error": str(exc)[:400]})
            continue
        spans = _block_spans(text)
        for mode in ("resource", "data"):
            for block in doc.get(mode, []) or []:
                if not isinstance(block, dict):
                    continue
                for rtype_raw, instances in block.items():
                    if not isinstance(instances, dict):
                        continue
                    rtype = _strip_quotes(rtype_raw) if isinstance(rtype_raw, str) else rtype_raw
                    if isinstance(rtype, str) and rtype.startswith("__"):
                        continue
                    for name_raw, body in instances.items():
                        if not isinstance(body, dict):
                            continue
                        name = _strip_quotes(name_raw) if isinstance(name_raw, str) else name_raw
                        if isinstance(name, str) and name.startswith("__"):
                            continue
                        span = spans.get((mode, rtype, name))
                        project.resources.append(TFResource(
                            mode=mode,
                            type=rtype,
                            name=name,
                            attrs=_normalize(body),
                            file=path,
                            start_line=span[0] if span else None,
                            end_line=span[1] if span else None,
                        ))
    return project


def collect_tf_files(root: Path) -> list[Path]:
    files = [p for p in sorted(root.rglob("*.tf")) if ".terraform" not in p.parts]
    return files[: config.MAX_FILES_PER_SCAN]


def parse_path(root: Path) -> ParsedProject:
    named: list[tuple[str, str]] = []
    skipped: list[dict] = []
    for p in collect_tf_files(root):
        rel = p.relative_to(root).as_posix()
        if p.stat().st_size > config.MAX_FILE_BYTES:
            skipped.append({"file": rel, "error": "file exceeds size limit, skipped"})
            continue
        named.append((rel, p.read_text(encoding="utf-8", errors="replace")))
    project = parse_files(named)
    project.errors.extend(skipped)
    return project
