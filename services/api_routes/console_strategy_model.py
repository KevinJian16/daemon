"""Console strategy/semantics/model routes."""
from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request


def register_console_strategy_model_routes(app: FastAPI, *, ctx: Any) -> None:
    @app.get("/console/strategies")
    def list_strategies(cluster_id: str | None = None, stage: str | None = None):
        strategies = ctx.playbook.list_strategies(cluster_id=cluster_id, stage=stage)
        cluster_rows = {row.get("cluster_id", ""): row for row in ctx.playbook.list_clusters()}
        for row in strategies:
            cid = str(row.get("cluster_id") or "")
            cluster = cluster_rows.get(cid) or {}
            row["cluster_display_name"] = cluster.get("display_name", cid)
            row["task_type_compat"] = cluster.get("task_type_compat", "")
            sid = str(row.get("strategy_id") or "")
            if not sid:
                row["risk_level"] = "unknown"
                row["risk_reasons"] = []
                row["release_audit_closed"] = False
                continue
            try:
                audit = ctx.playbook.strategy_audit_status(sid)
            except Exception:
                row["risk_level"] = "high"
                row["risk_reasons"] = ["audit_lookup_failed"]
                row["release_audit_closed"] = False
                continue
            missing_checks = audit.get("missing_checks") if isinstance(audit.get("missing_checks"), list) else []
            missing_count = len(missing_checks)
            if missing_count == 0:
                risk_level = "low"
            elif missing_count <= 2:
                risk_level = "medium"
            else:
                risk_level = "high"
            row["release_audit_closed"] = bool(audit.get("release_audit_closed", False))
            row["risk_level"] = risk_level
            row["risk_reasons"] = missing_checks
        return strategies

    @app.get("/console/strategies/shadow-report")
    def shadow_report(limit: int = 200):
        path = ctx.state / "telemetry" / "shadow_comparisons.jsonl"
        if not path.exists():
            return []
        rows: list[dict] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            ctx.logger.warning("Failed to read shadow report file: %s", exc)
            return []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
            if len(rows) >= max(1, min(limit, 2000)):
                break
        return rows

    @app.post("/console/strategies/{strategy_id}/promote")
    async def promote_strategy(strategy_id: str, request: Request):
        body = await request.json()
        next_stage = str(body.get("next_stage") or "champion")
        reason = str(body.get("reason") or "")
        decided_by = str(body.get("decided_by") or "console")
        row = ctx.playbook.get_strategy(strategy_id)
        if not row:
            raise HTTPException(status_code=404, detail="strategy not found")
        prev_stage = str(row.get("stage") or "candidate")
        try:
            promotion_id = ctx.playbook.promote_strategy(
                strategy_id=strategy_id,
                decision="promote_manual",
                prev_stage=prev_stage,
                next_stage=next_stage,
                reason=reason,
                decided_by=decided_by,
            )
        except ValueError as exc:
            msg = str(exc)
            if msg.startswith("invalid_stage_transition:"):
                raise HTTPException(
                    status_code=409,
                    detail={"ok": False, "error_code": "invalid_stage_transition", "error": msg},
                )
            if msg.startswith("promotion_audit_incomplete:"):
                raise HTTPException(
                    status_code=409,
                    detail={"ok": False, "error_code": "strategy_guard_blocked", "error": msg},
                )
            raise HTTPException(status_code=400, detail={"ok": False, "error": msg})
        ctx.nerve.emit(
            "strategy_promoted",
            {"strategy_id": strategy_id, "prev_stage": prev_stage, "next_stage": next_stage, "promotion_id": promotion_id},
        )
        return {"ok": True, "strategy_id": strategy_id, "promotion_id": promotion_id, "prev_stage": prev_stage, "next_stage": next_stage}

    @app.post("/console/strategies/{strategy_id}/rollback")
    async def rollback_strategy(strategy_id: str, request: Request):
        body = await request.json()
        reason = str(body.get("reason") or "manual_rollback")
        decided_by = str(body.get("decided_by") or "console")
        row = ctx.playbook.get_strategy(strategy_id)
        if not row:
            raise HTTPException(status_code=404, detail="strategy not found")
        target = ctx.playbook.resolve_latest_rollback_target(strategy_id)
        if not target:
            raise HTTPException(
                status_code=409,
                detail={
                    "ok": False,
                    "error_code": "strategy_guard_blocked",
                    "error": "rollback_point_missing_or_previous_champion_unavailable",
                },
            )
        prev = target.get("previous_strategy") if isinstance(target.get("previous_strategy"), dict) else {}
        rollback_to_strategy_id = str(target.get("previous_champion_strategy_id") or "")
        prev_stage = str(prev.get("stage") or "unknown")
        if not rollback_to_strategy_id:
            raise HTTPException(
                status_code=409,
                detail={"ok": False, "error_code": "strategy_guard_blocked", "error": "rollback_target_missing"},
            )
        if prev_stage == "retired":
            raise HTTPException(
                status_code=409,
                detail={"ok": False, "error_code": "strategy_guard_blocked", "error": "rollback_target_retired"},
            )
        try:
            promotion_id = ctx.playbook.promote_strategy(
                strategy_id=rollback_to_strategy_id,
                decision="rollback_manual",
                prev_stage=prev_stage,
                next_stage="champion",
                reason=f"{reason};rollback_from:{strategy_id}",
                decided_by=decided_by,
            )
        except ValueError as exc:
            msg = str(exc)
            if msg.startswith("invalid_stage_transition:"):
                raise HTTPException(
                    status_code=409,
                    detail={"ok": False, "error_code": "invalid_stage_transition", "error": msg},
                )
            raise HTTPException(status_code=400, detail={"ok": False, "error": msg})
        ctx.nerve.emit(
            "strategy_rolled_back",
            {
                "from_strategy_id": strategy_id,
                "to_strategy_id": rollback_to_strategy_id,
                "prev_stage": prev_stage,
                "next_stage": "champion",
                "promotion_id": promotion_id,
            },
        )
        return {
            "ok": True,
            "strategy_id": strategy_id,
            "rollback_to_strategy_id": rollback_to_strategy_id,
            "promotion_id": promotion_id,
            "prev_stage": prev_stage,
            "next_stage": "champion",
        }

    @app.get("/console/strategies/{strategy_id}/experiments")
    def strategy_experiments(strategy_id: str, limit: int = 200):
        row = ctx.playbook.get_strategy(strategy_id)
        if not row:
            raise HTTPException(status_code=404, detail="strategy not found")
        return ctx.playbook.list_experiments(strategy_id=strategy_id, limit=limit)

    @app.get("/console/strategies/{strategy_id}/promotions")
    def strategy_promotions(strategy_id: str, limit: int = 200):
        row = ctx.playbook.get_strategy(strategy_id)
        if not row:
            raise HTTPException(status_code=404, detail="strategy not found")
        return ctx.playbook.list_promotions(strategy_id=strategy_id, limit=limit)

    @app.get("/console/strategies/{strategy_id}/audit")
    def strategy_audit(strategy_id: str):
        try:
            return ctx.playbook.strategy_audit_status(strategy_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="strategy not found")

    @app.get("/console/strategies/release-events")
    def strategy_release_events(strategy_id: str | None = None, cluster_id: str | None = None, limit: int = 500):
        return ctx.playbook.list_release_transitions(strategy_id=strategy_id, cluster_id=cluster_id, limit=limit)

    @app.get("/console/strategies/rollback-points")
    def strategy_rollback_points(cluster_id: str | None = None, limit: int = 200):
        return ctx.playbook.list_rollback_points(cluster_id=cluster_id, limit=limit)

    @app.post("/console/strategies/{strategy_id}/sandbox-submit")
    async def strategy_sandbox_submit(strategy_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="sandbox plan body must be a JSON object")
        result = await ctx.dispatch.submit_sandbox(body, strategy_id=strategy_id)
        if not result.get("ok"):
            code = str(result.get("error_code") or "")
            if code in {"invalid_plan", "semantic_mapping_failed", "strategy_guard_blocked", "strategy_not_found"}:
                raise HTTPException(status_code=400, detail=result)
            if code.startswith("temporal_"):
                raise HTTPException(status_code=503, detail=result)
            raise HTTPException(status_code=500, detail=result)
        return result

    @app.get("/console/semantics")
    def console_semantics():
        catalog = {}
        rules = {}
        try:
            catalog = json.loads(ctx.semantic_catalog_path.read_text(encoding="utf-8")) if ctx.semantic_catalog_path.exists() else {}
        except Exception as exc:
            ctx.logger.warning("Failed to load semantic catalog: %s", exc)
        try:
            rules = json.loads(ctx.semantic_rules_path.read_text(encoding="utf-8")) if ctx.semantic_rules_path.exists() else {}
        except Exception as exc:
            ctx.logger.warning("Failed to load semantic mapping rules: %s", exc)
        return {
            "catalog": catalog,
            "mapping_rules": rules,
            "clusters_db": ctx.playbook.list_clusters(),
        }

    @app.put("/console/semantics/catalog")
    async def set_semantic_catalog(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="catalog body must be a JSON object")
        try:
            return ctx.write_semantic_target("catalog", body, changed_by="console", reason="semantic_catalog_update")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})

    @app.put("/console/semantics/mapping-rules")
    async def set_semantic_rules(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="mapping rules body must be a JSON object")
        try:
            return ctx.write_semantic_target("mapping_rules", body, changed_by="console", reason="semantic_mapping_rules_update")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})

    @app.get("/console/semantics/{target}/versions")
    def semantic_versions(target: str, limit: int = 50):
        try:
            cfg_key, _ = ctx.semantic_target_spec(target)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return ctx.compass.versions(cfg_key, limit=max(1, min(limit, 200)))

    @app.post("/console/semantics/{target}/rollback/{version}")
    def semantic_rollback(target: str, version: int):
        try:
            cfg_key, _ = ctx.semantic_target_spec(target)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        value = ctx.compass.version_value(cfg_key, version)
        if value is None or not isinstance(value, dict):
            raise HTTPException(status_code=404, detail="semantic config version not found")
        try:
            result = ctx.write_semantic_target(target, value, changed_by="console", reason=f"rollback_to:{version}")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})
        result["rolled_back_to"] = version
        return result

    @app.get("/console/model-policy")
    def get_model_policy():
        if not ctx.model_policy_path.exists():
            return {}
        try:
            return json.loads(ctx.model_policy_path.read_text(encoding="utf-8"))
        except Exception as exc:
            ctx.logger.warning("Failed to read model policy: %s", exc)
            raise HTTPException(status_code=500, detail="model policy parse failed")

    @app.get("/console/model-registry")
    def get_model_registry():
        if not ctx.model_registry_path.exists():
            return {}
        try:
            data = json.loads(ctx.model_registry_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                ctx.validate_model_registry(data)
            return data
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=f"model registry invalid: {exc}")
        except Exception as exc:
            ctx.logger.warning("Failed to read model registry: %s", exc)
            raise HTTPException(status_code=500, detail="model registry parse failed")

    @app.put("/console/model-policy")
    async def set_model_policy(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="policy body must be a JSON object")
        registry = {}
        if ctx.model_registry_path.exists():
            try:
                registry = json.loads(ctx.model_registry_path.read_text(encoding="utf-8"))
                if isinstance(registry, dict):
                    ctx.validate_model_registry(registry)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"ok": False, "error": f"model_registry_invalid:{exc}"})
            except Exception as exc:
                raise HTTPException(status_code=400, detail={"ok": False, "error": f"model_registry_unreadable:{exc}"})
        aliases = ctx.model_registry_aliases(registry if isinstance(registry, dict) else {})
        try:
            ctx.validate_model_policy(body, aliases)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc), "error_code": "invalid_model_policy"})
        current = {}
        if ctx.model_policy_path.exists():
            try:
                current = json.loads(ctx.model_policy_path.read_text(encoding="utf-8"))
            except Exception:
                current = {}
        version = str(body.get("_version") or current.get("_version") or "1.0.0")
        body["_version"] = version
        body["_updated"] = ctx.utc()[:10]
        ctx.model_policy_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        sync_result = ctx.sync_compass_provider_budgets_from_policy(body, overwrite=True)
        cv_version = ctx.compass.record_config_version("model_policy", body, changed_by="console", reason="model_policy_update")
        ctx.nerve.emit("fabric_updated", {"fabric": "model_policy", "path": str(ctx.model_policy_path)})
        return {
            "ok": True,
            "path": str(ctx.model_policy_path),
            "_version": version,
            "config_version": cv_version,
            "budget_sync": sync_result,
        }

    @app.put("/console/model-registry")
    async def set_model_registry(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="registry body must be a JSON object")
        try:
            ctx.validate_model_registry(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc), "error_code": "invalid_model_registry"})
        aliases = ctx.model_registry_aliases(body)
        current_policy = {}
        if ctx.model_policy_path.exists():
            try:
                current_policy = json.loads(ctx.model_policy_path.read_text(encoding="utf-8"))
            except Exception:
                current_policy = {}
        if isinstance(current_policy, dict) and current_policy:
            try:
                ctx.validate_model_policy(current_policy, aliases)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail={"ok": False, "error": str(exc), "error_code": "model_policy_incompatible_with_registry"},
                )
        body["_updated"] = ctx.utc()[:10]
        ctx.model_registry_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        cv_version = ctx.compass.record_config_version("model_registry", body, changed_by="console", reason="model_registry_update")
        ctx.nerve.emit("fabric_updated", {"fabric": "model_registry", "path": str(ctx.model_registry_path)})
        return {"ok": True, "path": str(ctx.model_registry_path), "config_version": cv_version}

    @app.get("/console/model-policy/versions")
    def model_policy_versions(limit: int = 50):
        return ctx.compass.versions("model_policy", limit=max(1, min(limit, 200)))

    @app.get("/console/model-registry/versions")
    def model_registry_versions(limit: int = 50):
        return ctx.compass.versions("model_registry", limit=max(1, min(limit, 200)))

    @app.post("/console/model-policy/rollback/{version}")
    def model_policy_rollback(version: int):
        value = ctx.compass.version_value("model_policy", version)
        if value is None or not isinstance(value, dict):
            raise HTTPException(status_code=404, detail="model policy version not found")
        registry = {}
        if ctx.model_registry_path.exists():
            try:
                registry = json.loads(ctx.model_registry_path.read_text(encoding="utf-8"))
                if isinstance(registry, dict):
                    ctx.validate_model_registry(registry)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"model registry invalid: {exc}")
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"model registry unreadable: {exc}")
        aliases = ctx.model_registry_aliases(registry if isinstance(registry, dict) else {})
        try:
            ctx.validate_model_policy(value, aliases)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"ok": False, "error": str(exc), "error_code": "invalid_model_policy"},
            )
        value["_updated"] = ctx.utc()[:10]
        ctx.model_policy_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        sync_result = ctx.sync_compass_provider_budgets_from_policy(value, overwrite=True)
        cv_version = ctx.compass.record_config_version("model_policy", value, changed_by="console", reason=f"rollback_to:{version}")
        ctx.nerve.emit("fabric_updated", {"fabric": "model_policy", "path": str(ctx.model_policy_path), "rollback_from_version": version})
        return {
            "ok": True,
            "rolled_back_to": version,
            "config_version": cv_version,
            "budget_sync": sync_result,
        }

    @app.post("/console/model-registry/rollback/{version}")
    def model_registry_rollback(version: int):
        value = ctx.compass.version_value("model_registry", version)
        if value is None or not isinstance(value, dict):
            raise HTTPException(status_code=404, detail="model registry version not found")
        try:
            ctx.validate_model_registry(value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc), "error_code": "invalid_model_registry"})
        aliases = ctx.model_registry_aliases(value)
        current_policy = {}
        if ctx.model_policy_path.exists():
            try:
                current_policy = json.loads(ctx.model_policy_path.read_text(encoding="utf-8"))
            except Exception:
                current_policy = {}
        if isinstance(current_policy, dict) and current_policy:
            try:
                ctx.validate_model_policy(current_policy, aliases)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail={"ok": False, "error": str(exc), "error_code": "model_policy_incompatible_with_registry"},
                )
        value["_updated"] = ctx.utc()[:10]
        ctx.model_registry_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        cv_version = ctx.compass.record_config_version("model_registry", value, changed_by="console", reason=f"rollback_to:{version}")
        ctx.nerve.emit("fabric_updated", {"fabric": "model_registry", "path": str(ctx.model_registry_path), "rollback_from_version": version})
        return {"ok": True, "rolled_back_to": version, "config_version": cv_version}

    @app.get("/console/model-usage")
    def model_usage(since: str | None = None, until: str | None = None, limit: int = 1000):
        records = ctx.cortex.usage_between(since=since, until=until, limit=limit)
        by_provider: dict[str, dict[str, int]] = {}
        by_model: dict[str, dict[str, int]] = {}
        by_routine: dict[str, dict[str, int]] = {}
        fallback_chain_hits: dict[str, int] = {}

        for row in records:
            provider = str(row.get("provider") or "unknown")
            model = str(row.get("model") or "unknown")
            routine = str(row.get("routine") or "unknown")
            in_t = int(row.get("in_tokens") or 0)
            out_t = int(row.get("out_tokens") or 0)
            success = bool(row.get("success"))

            p = by_provider.setdefault(provider, {"calls": 0, "errors": 0, "in_tokens": 0, "out_tokens": 0})
            p["calls"] += 1
            p["in_tokens"] += in_t
            p["out_tokens"] += out_t
            if not success:
                p["errors"] += 1

            m = by_model.setdefault(model, {"calls": 0, "errors": 0, "in_tokens": 0, "out_tokens": 0})
            m["calls"] += 1
            m["in_tokens"] += in_t
            m["out_tokens"] += out_t
            if not success:
                m["errors"] += 1

            r = by_routine.setdefault(routine, {"calls": 0, "errors": 0, "in_tokens": 0, "out_tokens": 0})
            r["calls"] += 1
            r["in_tokens"] += in_t
            r["out_tokens"] += out_t
            if not success:
                r["errors"] += 1
            chain = row.get("fallback_chain")
            if isinstance(chain, list) and chain:
                key = "->".join(str(x) for x in chain if str(x))
                if key:
                    fallback_chain_hits[key] = fallback_chain_hits.get(key, 0) + 1

        task_rows = ctx.store.load_tasks()
        by_semantic_cluster: dict[str, int] = {}
        by_capability: dict[str, int] = {}
        by_risk_level: dict[str, int] = {}
        for row in task_rows if isinstance(task_rows, list) else []:
            plan_row = row.get("plan") if isinstance(row.get("plan"), dict) else {}
            cluster = str(
                row.get("semantic_cluster")
                or plan_row.get("cluster_id")
                or ""
            )
            if cluster:
                by_semantic_cluster[cluster] = by_semantic_cluster.get(cluster, 0) + 1
            fp = plan_row.get("semantic_fingerprint") if isinstance(plan_row.get("semantic_fingerprint"), dict) else {}
            risk = str(fp.get("risk_level") or "").strip().lower()
            if risk:
                by_risk_level[risk] = by_risk_level.get(risk, 0) + 1
            steps = plan_row.get("steps") or plan_row.get("graph", {}).get("steps") or []
            if isinstance(steps, list):
                for st in steps:
                    if not isinstance(st, dict):
                        continue
                    cid = str(st.get("capability_id") or "")
                    if cid:
                        by_capability[cid] = by_capability.get(cid, 0) + 1

        return {
            "records": records,
            "summary": {
                "by_provider": by_provider,
                "by_model": by_model,
                "by_routine": by_routine,
                "by_semantic_cluster": by_semantic_cluster,
                "by_capability": by_capability,
                "by_risk_level": by_risk_level,
                "fallback_chain_hits": fallback_chain_hits,
            },
        }
