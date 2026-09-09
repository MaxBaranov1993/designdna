"""Правила проекта и декларативные ограничения: /api/rules, /api/constraints."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

import qualitygate
import rules as project_rules
from api.common import err

router = APIRouter()


class ProjectRulesReq(BaseModel):
    text: str = ""


class ConstraintsCheckReq(BaseModel):
    ir: dict
    constraints: list  # [{path, lock?, min?, max?, enum?, max_len?}]


@router.get("/api/rules")
def get_rules():
    """Правила, по которым работают генератор и судья: встроенные + правила проекта."""
    return project_rules.payload()


@router.post("/api/rules/project")
def save_rules(req: ProjectRulesReq):
    try:
        project_rules.save_project_rules(req.text)
    except ValueError as e:
        return err(422, str(e))
    return project_rules.payload()


@router.post("/api/constraints/check")
def constraints_check(req: ConstraintsCheckReq):
    """Проверка декларативных ограничений (локи полей по путям + диапазоны)."""
    try:
        violations = qualitygate.check_constraints(req.ir, req.constraints)
    except ValueError as e:
        return err(422, str(e))
    return {"ok": not violations, "violations": violations}
