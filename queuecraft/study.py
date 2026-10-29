"""Dispatch only explicitly supported registered experiment versions.

The prior five-minute experiment is pinned to its original Git revision. Its
horizon class and recorder-end semantics cannot be silently replaced by current
implementations while retaining its old registration name.
"""
from __future__ import annotations
import json
from pathlib import Path


def study(sessions: Path, plan_path: Path, output: Path, *, calibration_path: Path | None = None, raw_archive_path: Path | None = None) -> dict:
    version=json.loads(plan_path.read_text()).get('version')
    if isinstance(version,str) and version.startswith('prospective-15m-'):
        from .prospective import study as prospective_study
        return prospective_study(sessions,plan_path,output,calibration_path=calibration_path,raw_archive_path=raw_archive_path)
    raise ValueError('historical/unsupported study plan: the first5m experiment is pinned to source cbbcb3cb5b9da2083b1a79b71dcd43ac30c52f2b; current joint planning and explicit recorder metadata require a new prospective registration')
