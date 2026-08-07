"""Guardrail rule registry and the built-in enterprise rule pack.

A rule's ``check(resource, project)`` returns a list of violation messages
(empty list = compliant). Each (rule, applicable resource) pair counts as
one check toward the weighted compliance score.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterator, Optional

from .parser import ParsedProject, TFResource


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


SEVERITY_RANK = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}
SEVERITY_WEIGHT = {Severity.CRITICAL: 10, Severity.HIGH: 6, Severity.MEDIUM: 3, Severity.LOW: 1}

CheckFn = Callable[[TFResource, ParsedProject], Optional[list]]


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    description: str
    severity: Severity
    resource_types: tuple    # ("*",) applies to every managed resource
    remediation: str
    references: tuple = ()
    check: CheckFn = None  # type: ignore[assignment]


REGISTRY: dict[str, Rule] = {}


def rule(**meta) -> Callable[[CheckFn], CheckFn]:
    def decorator(fn: CheckFn) -> CheckFn:
        r = Rule(check=fn, **meta)
        if r.id in REGISTRY:
            raise ValueError(f"duplicate rule id {r.id}")
        REGISTRY[r.id] = r
        return fn
    return decorator


def all_rules() -> list[Rule]:
    return sorted(REGISTRY.values(), key=lambda r: r.id)


# ---------------------------------------------------------------------------
# helpers

_INTERP = re.compile(r"\$\{")


def blocks(value: Any) -> list[dict]:
    """Normalize an HCL nested block attribute to a list of dicts."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [b for b in value if isinstance(b, dict)]
    return []


def truthy(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def is_literal_string(value: Any) -> bool:
    """A plain string with no ${...} interpolation (i.e. hardcoded)."""
    return isinstance(value, str) and not _INTERP.search(value)


def world_open(block: dict) -> bool:
    cidrs: list[str] = []
    for key in ("cidr_blocks", "ipv6_cidr_blocks"):
        v = block.get(key)
        if isinstance(v, str):
            cidrs.append(v)
        elif isinstance(v, list):
            cidrs.extend(str(c) for c in v)
    for key in ("cidr_ipv4", "cidr_ipv6", "cidr_block"):
        v = block.get(key)
        if isinstance(v, str):
            cidrs.append(v)
    return any(c in ("0.0.0.0/0", "::/0") for c in cidrs)


ADMIN_PORTS = {22: "SSH", 3389: "RDP"}


def covered_admin_ports(block: dict) -> list[str]:
    proto = str(block.get("protocol", block.get("ip_protocol", "tcp"))).lower()
    if proto in ("-1", "all"):
        return [f"{name} ({port})" for port, name in ADMIN_PORTS.items()]
    if proto not in ("tcp", "6"):
        return []
    try:
        lo = int(block.get("from_port"))
        hi = int(block.get("to_port"))
    except (TypeError, ValueError):
        return []
    return [f"{name} ({port})" for port, name in ADMIN_PORTS.items() if lo <= port <= hi]


def ingress_blocks(res: TFResource) -> list[dict]:
    """Normalized ingress definitions across security-group resource flavors."""
    if res.type == "aws_security_group":
        return blocks(res.attrs.get("ingress"))
    if res.type == "aws_security_group_rule":
        return [res.attrs] if str(res.attrs.get("type", "")).lower() == "ingress" else []
    if res.type == "aws_vpc_security_group_ingress_rule":
        return [res.attrs]
    return []


def port_label(block: dict) -> str:
    proto = str(block.get("protocol", block.get("ip_protocol", ""))).lower()
    if proto in ("-1", "all"):
        return "all traffic"
    lo, hi = block.get("from_port"), block.get("to_port")
    if lo is None:
        return proto or "tcp"
    proto = proto or "tcp"
    return f"{proto}/{lo}" if lo == hi else f"{proto}/{lo}-{hi}"


def companion_targets(companion: TFResource, bucket: TFResource) -> bool:
    """Does a companion resource's `bucket` argument point at this bucket?"""
    v = companion.attrs.get("bucket")
    if not isinstance(v, str):
        return False
    if f"{bucket.type}.{bucket.name}" in v:
        return True
    declared = bucket.attrs.get("bucket")
    return bool(isinstance(declared, str) and declared and v == declared)


def walk_attrs(value: Any, path: str = "") -> Iterator[tuple]:
    """Yield (dotted_path, leaf_value) for every scalar in a nested structure."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from walk_attrs(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from walk_attrs(v, f"{path}[{i}]")
    else:
        yield path, value


def _as_list(v: Any) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


# ---------------------------------------------------------------------------
# Network guardrails

@rule(
    id="GR-NET-001",
    title="Administrative ports must not be exposed to the internet",
    description="Security group ingress must never allow 0.0.0.0/0 or ::/0 to reach "
                "SSH (22) or RDP (3389).",
    severity=Severity.CRITICAL,
    resource_types=("aws_security_group", "aws_security_group_rule",
                    "aws_vpc_security_group_ingress_rule"),
    remediation="Restrict the source CIDR to trusted ranges, or remove direct access and "
                "use SSM Session Manager / a bastion behind SSO.",
    references=("CIS AWS Foundations 5.2",),
)
def net_admin_ports(res: TFResource, project: ParsedProject):
    msgs = []
    for b in ingress_blocks(res):
        if world_open(b):
            ports = covered_admin_ports(b)
            if ports:
                msgs.append(f"Ingress open to the world reaches {', '.join(ports)}.")
    return msgs


@rule(
    id="GR-NET-002",
    title="Ingress from 0.0.0.0/0 must be justified and minimal",
    description="Security group ingress rules that allow the entire internet on any port "
                "violate the least-privilege network guardrail.",
    severity=Severity.HIGH,
    resource_types=("aws_security_group", "aws_security_group_rule",
                    "aws_vpc_security_group_ingress_rule"),
    remediation="Scope the source CIDR down to known networks, or front the service with a "
                "load balancer / WAF and keep instances private.",
    references=("AWS Well-Architected SEC05", "NIST 800-53 SC-7"),
)
def net_world_open(res: TFResource, project: ParsedProject):
    msgs = []
    for b in ingress_blocks(res):
        if world_open(b) and not covered_admin_ports(b):
            msgs.append(f"Ingress rule allows the whole internet on {port_label(b)}.")
    return msgs


# ---------------------------------------------------------------------------
# S3 guardrails

PUBLIC_ACLS = {"public-read", "public-read-write"}


@rule(
    id="GR-S3-001",
    title="S3 buckets must not use public ACLs",
    description="Bucket ACLs of public-read or public-read-write expose object data to "
                "anonymous internet users.",
    severity=Severity.CRITICAL,
    resource_types=("aws_s3_bucket", "aws_s3_bucket_acl"),
    remediation="Set the ACL to 'private' and serve public content through CloudFront with "
                "origin access control.",
    references=("CIS AWS Foundations 2.1",),
)
def s3_public_acl(res: TFResource, project: ParsedProject):
    acl = res.attrs.get("acl")
    if isinstance(acl, str) and acl in PUBLIC_ACLS:
        return [f"Bucket ACL is '{acl}'."]
    return []


@rule(
    id="GR-S3-002",
    title="S3 buckets must declare server-side encryption",
    description="Every bucket must have an explicit server-side encryption configuration "
                "(inline block or aws_s3_bucket_server_side_encryption_configuration).",
    severity=Severity.MEDIUM,
    resource_types=("aws_s3_bucket",),
    remediation="Attach an aws_s3_bucket_server_side_encryption_configuration using "
                "aws:kms with a customer-managed key.",
    references=("CIS AWS Foundations 2.1.1", "NIST 800-53 SC-28"),
)
def s3_encryption(res: TFResource, project: ParsedProject):
    if blocks(res.attrs.get("server_side_encryption_configuration")):
        return []
    for companion in project.managed("aws_s3_bucket_server_side_encryption_configuration"):
        if companion_targets(companion, res):
            return []
    return ["No server-side encryption configuration is attached to this bucket."]


@rule(
    id="GR-S3-003",
    title="S3 buckets must enable all public access block settings",
    description="Each bucket needs an aws_s3_bucket_public_access_block with all four "
                "protections enabled to prevent accidental public exposure.",
    severity=Severity.HIGH,
    resource_types=("aws_s3_bucket",),
    remediation="Add an aws_s3_bucket_public_access_block for the bucket with "
                "block_public_acls, block_public_policy, ignore_public_acls and "
                "restrict_public_buckets all set to true.",
    references=("CIS AWS Foundations 2.1.4",),
)
def s3_public_access_block(res: TFResource, project: ParsedProject):
    flags = ("block_public_acls", "block_public_policy",
             "ignore_public_acls", "restrict_public_buckets")
    for companion in project.managed("aws_s3_bucket_public_access_block"):
        if companion_targets(companion, res):
            missing = [f for f in flags if not truthy(companion.attrs.get(f))]
            if missing:
                return [f"Public access block exists but leaves {', '.join(missing)} disabled."]
            return []
    return ["Bucket has no aws_s3_bucket_public_access_block resource."]


# ---------------------------------------------------------------------------
# IAM guardrails

_STAR_ACTION = re.compile(r'["\']?Action["\']?\s*[:=]\s*(\[\s*)?["\']\*["\']')
_STAR_RESOURCE = re.compile(r'["\']?Resource["\']?\s*[:=]\s*(\[\s*)?["\']\*["\']')


@rule(
    id="GR-IAM-001",
    title="IAM policies must not grant full administrative access",
    description="Customer-managed and inline policies must never allow Action \"*\" on "
                "Resource \"*\".",
    severity=Severity.CRITICAL,
    resource_types=("aws_iam_policy", "aws_iam_role_policy",
                    "aws_iam_user_policy", "aws_iam_group_policy"),
    remediation="Replace the wildcard statement with least-privilege actions scoped to "
                "specific resource ARNs.",
    references=("CIS AWS Foundations 1.16",),
)
def iam_wildcard(res: TFResource, project: ParsedProject):
    policy = res.attrs.get("policy")
    if not isinstance(policy, str):
        return []
    text = policy.strip()
    if text.startswith("{"):
        try:
            doc = json.loads(text)
        except ValueError:
            doc = None
        if isinstance(doc, dict):
            for s in _as_list(doc.get("Statement")):
                if not isinstance(s, dict):
                    continue
                if str(s.get("Effect", "Allow")).lower() != "allow":
                    continue
                if "*" in _as_list(s.get("Action")) and "*" in _as_list(s.get("Resource")):
                    return ['Policy statement allows Action "*" on Resource "*" '
                            "(full administrative access)."]
            return []
    # jsonencode()/templated policies: heuristic scan of the raw expression
    if _STAR_ACTION.search(text) and _STAR_RESOURCE.search(text):
        return ['Policy appears to allow Action "*" on Resource "*" '
                "(full administrative access)."]
    return []


# ---------------------------------------------------------------------------
# RDS guardrails

@rule(
    id="GR-RDS-001",
    title="RDS instances must not be publicly accessible",
    description="Databases must live on private subnets; publicly_accessible = true "
                "assigns a public endpoint.",
    severity=Severity.HIGH,
    resource_types=("aws_db_instance", "aws_rds_cluster_instance"),
    remediation="Set publicly_accessible = false and reach the database through private "
                "networking (VPN, peering or SSM port forwarding).",
    references=("CIS AWS Foundations 2.3.3",),
)
def rds_public(res: TFResource, project: ParsedProject):
    if truthy(res.attrs.get("publicly_accessible")):
        return ["Database instance is publicly accessible."]
    return []


@rule(
    id="GR-RDS-002",
    title="RDS storage must be encrypted at rest",
    description="aws_db_instance must set storage_encrypted = true (Aurora cluster "
                "members inherit encryption from the cluster and are exempt).",
    severity=Severity.HIGH,
    resource_types=("aws_db_instance",),
    remediation="Set storage_encrypted = true (requires recreating the instance; use a "
                "snapshot-copy migration for existing databases).",
    references=("CIS AWS Foundations 2.3.1",),
)
def rds_encryption(res: TFResource, project: ParsedProject):
    if res.attrs.get("cluster_identifier") is not None:
        return []  # encryption is controlled by the aurora cluster
    if not truthy(res.attrs.get("storage_encrypted")):
        return ["storage_encrypted is not enabled for this database instance."]
    return []


# ---------------------------------------------------------------------------
# Compute / storage guardrails

@rule(
    id="GR-EC2-001",
    title="EC2 instances must enforce IMDSv2",
    description="Instances must require session tokens for the metadata service "
                "(http_tokens = \"required\") to blunt SSRF credential theft.",
    severity=Severity.HIGH,
    resource_types=("aws_instance", "aws_launch_template"),
    remediation="Add a metadata_options block with http_endpoint = \"enabled\" and "
                "http_tokens = \"required\".",
    references=("CIS AWS Foundations 5.6",),
)
def ec2_imdsv2(res: TFResource, project: ParsedProject):
    mo = blocks(res.attrs.get("metadata_options"))
    if not mo:
        return ["No metadata_options block; IMDSv2 is not enforced "
                "(http_tokens defaults to 'optional')."]
    msgs = []
    for b in mo:
        if str(b.get("http_tokens", "optional")).lower() != "required":
            msgs.append("metadata_options.http_tokens is not 'required'; the metadata "
                        "service remains open to SSRF-style credential theft.")
    return msgs


@rule(
    id="GR-EBS-001",
    title="Block storage must be encrypted at rest",
    description="aws_ebs_volume resources and instance block devices must set "
                "encrypted = true.",
    severity=Severity.HIGH,
    resource_types=("aws_ebs_volume", "aws_instance"),
    remediation="Set encrypted = true on volumes and block devices (or enable EBS "
                "encryption-by-default for the account).",
    references=("CIS AWS Foundations 2.2.1",),
)
def ebs_encryption(res: TFResource, project: ParsedProject):
    msgs = []
    if res.type == "aws_ebs_volume":
        if not truthy(res.attrs.get("encrypted")):
            msgs.append("EBS volume is not encrypted at rest.")
        return msgs
    for key in ("root_block_device", "ebs_block_device"):
        for b in blocks(res.attrs.get(key)):
            if not truthy(b.get("encrypted")):
                device = b.get("device_name")
                suffix = f" ({device})" if isinstance(device, str) else ""
                msgs.append(f"{key}{suffix} does not set encrypted = true.")
    return msgs


# ---------------------------------------------------------------------------
# Secrets hygiene

SECRET_KEY_PAT = re.compile(
    r"(^|_)(password|passwd|secret|token|api_key|apikey|access_key|private_key|client_secret)($|_)",
    re.IGNORECASE,
)
SAFE_VALUE_PAT = re.compile(r"^(arn:aws|ssm:|resolve:)", re.IGNORECASE)


@rule(
    id="GR-SEC-001",
    title="Secrets must not be hardcoded in Terraform",
    description="Credential-shaped attributes (password, secret, token, *_key) must come "
                "from variables or a secrets manager, never from literals in code.",
    severity=Severity.CRITICAL,
    resource_types=("*",),
    remediation="Move the value to a sensitive variable, SSM Parameter Store or Secrets "
                "Manager, and rotate the exposed credential.",
    references=("CWE-798",),
)
def hardcoded_secrets(res: TFResource, project: ParsedProject):
    msgs = []
    for path, value in walk_attrs(res.attrs):
        leaf = path.split(".")[-1].split("[")[0]
        if not SECRET_KEY_PAT.search(leaf):
            continue
        if is_literal_string(value) and len(value) >= 4 and not SAFE_VALUE_PAT.match(value):
            msgs.append(f"Attribute '{path}' appears to hold a hardcoded secret "
                        "(value redacted).")
    return msgs
