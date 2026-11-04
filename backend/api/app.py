"""HTTP gateway for the backend contract; no simulation policy lives here."""

import json
import os
import time
from pathlib import Path
from typing import Annotated, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.exceptions import HTTPException

from backend.contracts import SPEC, issues_for, request_schema
from backend.runtime import BackendRunExecutor
from backend import templates
from backend.store import (
    BackendConflictError, BackendNotFoundError, BackendStore, BackendValidationError,
)
from . import stream, views

app = FastAPI(title="ecoSim Backend MVP", version="1.0.0")
app.openapi = lambda: SPEC
Limit = Annotated[int, Query(ge=1, le=200)]
After = Annotated[str | None, Query(min_length=1, max_length=512)]
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]


def _store():
    return BackendStore(os.environ.get(
        "ECOSIM_DATABASE", str(Path("data") / "ecosim-backend.sqlite")),
        # One connection per request; FastAPI may move sequential dependency
        # setup/endpoint/cleanup between worker threads.
        check_same_thread=False)


def database():
    store = _store()
    try:
        yield store
    finally:
        store.close()


DB = Annotated[BackendStore, Depends(database)]


@app.exception_handler(ValueError)
@app.exception_handler(RequestValidationError)
@app.exception_handler(HTTPException)
async def error_response(request: Request, error):
    fields = []
    if isinstance(error, BackendNotFoundError):
        status, code, message = 404, "NOT_FOUND", str(error)
    elif isinstance(error, BackendConflictError):
        status, code, message = 409, "CONFLICT", str(error)
    elif isinstance(error, BackendValidationError):
        status, code, message = 422, "INVALID_INPUT", "Input validation failed."
        fields = [{**i, "severity": i.get("severity", "error")} for i in error.issues]
    elif isinstance(error, RequestValidationError):
        status = 400 if all(e["loc"][0] in {"query", "path"} for e in error.errors()) else 422
        code, message = "INVALID_REQUEST", "Request validation failed."
        fields = [{"path": ".".join(map(str, e["loc"])), "code": "INVALID_VALUE",
                   "message": "Value does not satisfy the request contract.", "severity": "error"}
                  for e in error.errors()]
    elif isinstance(error, HTTPException):
        status, code, message = error.status_code, "HTTP_ERROR", "Request could not be processed."
    else:
        status, code, message = 400, "INVALID_QUERY", "Invalid query or cursor."
    return JSONResponse(status_code=status, content={
        "error": {"code": code, "message": message, "fields": fields, "retryable": False}})


def body(value, path, method="post"):
    errors = issues_for(value, request_schema(path, method))
    if errors:
        raise BackendValidationError(errors)
    return value


def _run_in_background(run_id, *, resume=False, claimed=False):
    store = _store()
    try:
        from gateways.jev import build_jev_gateway
        from gateways.openai import build_openai_gateway
        try:
            fallback = build_openai_gateway()
        except ValueError:
            fallback = None
        BackendRunExecutor(store).execute(
            run_id, primary=build_jev_gateway(), fallback=fallback, resume=resume, claimed=claimed)
    except Exception as error:
        if store.get_run(run_id)["status"] == "running":
            store.finish_run(run_id, "failed", type(error).__name__)
    finally:
        store.close()


@app.get("/api/v1/industries")
def list_industries(store: DB):
    return [views.industry(store.get_industry(r["industry_id"], r["profile_version"]))
            for r in store.list_industries()]


@app.get("/api/v1/industries/{industry_id}/profiles/{profile_version}")
def get_industry(industry_id: str, profile_version: str, store: DB):
    return views.bundle(store.get_industry(industry_id, profile_version))


@app.get("/api/v1/datasets")
def list_datasets(store: DB):
    return [views.public("Dataset", {**r, "name": r["source_name"]})
            for r in store.list_datasets()]


@app.get("/api/v1/cohorts")
def list_cohorts(store: DB, industry_id: str | None = None, limit: Limit = 50, after: After = None):
    rows = [views.public("Cohort", r) for r in store.list_cohorts()
            if industry_id is None or r["industry_id"] == industry_id]
    return views.page(rows, scope=f"cohorts:{industry_id}", key=lambda r: r["cohort_id"],
                      limit=limit, after=after)


@app.get("/api/v1/cohorts/{cohort_id}/members")
def cohort_members(cohort_id: str, store: DB, limit: Limit = 50, after: After = None):
    scope = f"members:{cohort_id}"
    previous = views.read_cursor(after, scope) if after else ""
    if not isinstance(previous, str):
        raise ValueError("Invalid member cursor")
    rows = store.cohort_members(cohort_id, limit + 1, previous)
    return {"items": rows[:limit], "next_cursor":
            views.cursor(scope, rows[limit - 1]["cohort_persona_id"]) if len(rows) > limit else None}


@app.get("/api/v1/scenario-templates")
def list_scenario_templates():
    return [templates.summary(item) for item in templates.catalog()]

@app.get("/api/v1/scenario-templates/{template_id}")
def get_scenario_template(template_id: str):
    return templates.get_template(template_id)

@app.post("/api/v1/scenario-templates/{template_id}/instantiate", status_code=201)
def instantiate_scenario_template(template_id: str, payload: dict, store: DB, idempotency_key: Key):
    body(payload, "/scenario-templates/{template_id}/instantiate")
    return templates.instantiate(store, template_id, payload, idempotency_key)

@app.post("/api/v1/campaigns", status_code=201)
def create_campaign(payload: dict, store: DB):
    body(payload, "/campaigns")
    return views.campaign(store.create_campaign(payload))


@app.get("/api/v1/campaigns")
def list_campaigns(store: DB, limit: Limit = 50, after: After = None):
    return views.page([views.campaign(r) for r in store.list_campaigns()],
                      scope="campaigns", key=lambda r: r["campaign_id"], limit=limit, after=after)


@app.get("/api/v1/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, store: DB):
    return views.campaign(store.get_campaign(campaign_id))


@app.put("/api/v1/campaigns/{campaign_id}")
def update_campaign(campaign_id: str, payload: dict, store: DB):
    body(payload, "/campaigns/{campaign_id}", "put")
    return views.campaign(store.update_campaign(
        campaign_id, payload["campaign"], payload["expected_revision"]))


@app.post("/api/v1/campaigns/{campaign_id}/scenarios", status_code=201)
def create_scenario(campaign_id: str, payload: dict, store: DB):
    body(payload, "/campaigns/{campaign_id}/scenarios")
    return views.public("Scenario", store.create_scenario(campaign_id, payload))


@app.get("/api/v1/campaigns/{campaign_id}/scenarios")
def list_scenarios(campaign_id: str, store: DB, limit: Limit = 50, after: After = None):
    return views.page([views.public("Scenario", r) for r in store.list_scenarios(campaign_id)],
                      scope=f"scenarios:{campaign_id}", key=lambda r: r["scenario_id"],
                      limit=limit, after=after)


@app.get("/api/v1/scenarios/{scenario_id}")
def get_scenario(scenario_id: str, store: DB):
    return views.public("Scenario", store.get_scenario(scenario_id))


@app.put("/api/v1/scenarios/{scenario_id}")
def replace_scenario(scenario_id: str, payload: dict, store: DB):
    body(payload, "/scenarios/{scenario_id}", "put")
    return views.public("Scenario", store.replace_scenario(
        scenario_id, payload["setup"], payload["expected_revision"]))


@app.post("/api/v1/scenarios/{scenario_id}/validate")
def validate_scenario(scenario_id: str, payload: dict, store: DB):
    body(payload, "/scenarios/{scenario_id}/validate")
    with views.read_snapshot(store):
        return store.validate_scenario(scenario_id, payload["expected_revision"])


@app.get("/api/v1/scenarios/{scenario_id}/participants")
def scenario_participants(scenario_id: str, store: DB, limit: Limit = 50, after: After = None):
    with views.read_snapshot(store):
        revision = store.get_scenario(scenario_id)["revision"]
        rows = [views.participant(r) for r in store.scenario_participants(scenario_id)]
        return {"scenario_revision": revision, **views.page(
            rows, scope=f"participants:{scenario_id}:{revision}", key=lambda r: r["agent_id"],
            limit=limit, after=after)}


@app.post("/api/v1/scenarios/{scenario_id}/freeze")
def freeze_scenario(scenario_id: str, payload: dict, store: DB):
    body(payload, "/scenarios/{scenario_id}/freeze")
    return views.public("Scenario", store.freeze_scenario(scenario_id, payload["expected_revision"]))


@app.post("/api/v1/scenarios/{scenario_id}/runs", status_code=201)
def create_run(scenario_id: str, payload: dict, store: DB, idempotency_key: Key):
    body(payload, "/scenarios/{scenario_id}/runs")
    return views.public("Run", store.create_run(
        scenario_id, payload["execution"], idempotency_key=idempotency_key,
        expected_revision=payload["expected_revision"]))


@app.get("/api/v1/scenarios/{scenario_id}/runs")
def list_runs(scenario_id: str, store: DB, limit: Limit = 50, after: After = None):
    store.get_scenario(scenario_id)
    rows = store.connection.execute(
        "SELECT run_id FROM runs WHERE scenario_id=? ORDER BY created_at, run_id", (scenario_id,))
    return views.page([views.public("Run", store.get_run(r["run_id"])) for r in rows],
                      scope=f"runs:{scenario_id}", key=lambda r: r["run_id"], limit=limit, after=after)


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str, store: DB):
    return views.public("Run", store.get_run(run_id))

@app.get("/api/v1/runs/{run_id}/configuration")
def export_run_configuration(run_id: str, store: DB):
    run = store.get_run(run_id)
    # ponytail: export only; add import validation when importing configurations is in scope.
    content = {
        "format_version": "ecosim-run-configuration-v1",
        "snapshot_hash": run["snapshot_hash"],
        "input_snapshot": run["input_snapshot"],
    }
    return Response(
        json.dumps(content, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="ecosim-run-configuration.json"',
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/v1/runs/{run_id}/sessions")
def run_sessions(run_id: str, store: DB):
    with views.read_snapshot(store):
        return views.sessions(store, run_id)


@app.get("/api/v1/runs/{run_id}/objects")
def run_objects(run_id: str, store: DB):
    setup = store.get_run(run_id)["input_snapshot"]["setup"]
    return {key: setup[key] for key in ("business", "shops", "posts", "products")}


@app.get("/api/v1/runs/{run_id}/agents")
def run_agents(run_id: str, store: DB, limit: Limit = 50, after: After = None):
    relationships = {r["agent_id"]: r for r in store.run_relationships(run_id)}
    rows = [views.participant({
        **r, "group_id": relationships[r["agent_id"]]["group_id"],
        "initial_relationship": relationships[r["agent_id"]]["initial_state"],
    }) for r in store.run_agents(run_id)]
    return views.page(rows, scope=f"agents:{run_id}", key=lambda r: r["agent_id"],
                      limit=limit, after=after)


def command(store, tasks, run_id, key, resume):
    result = store.claim_command(
        run_id, operation="resume_run" if resume else "start_run", idempotency_key=key, resume=resume)
    if result.pop("newly_claimed", False):
        tasks.add_task(_run_in_background, run_id, claimed=True, resume=resume)
    return views.public("Run", result)


@app.post("/api/v1/runs/{run_id}/start", status_code=202)
def start_run(run_id: str, background_tasks: BackgroundTasks, store: DB, idempotency_key: Key):
    return command(store, background_tasks, run_id, idempotency_key, False)


@app.post("/api/v1/runs/{run_id}/resume", status_code=202)
def resume_run(run_id: str, background_tasks: BackgroundTasks, store: DB, idempotency_key: Key):
    return command(store, background_tasks, run_id, idempotency_key, True)


@app.get("/api/v1/runs/{run_id}/report")
def run_report(run_id: str, store: DB):
    with views.read_snapshot(store):
        return views.report(store, run_id)


@app.get("/api/v1/runs/{run_id}/events")
def run_events(run_id: str, store: DB, limit: Limit = 20):
    with views.read_snapshot(store):
        return {"items": views.recent_events(store, run_id, limit)}

@app.get("/api/v1/runs/{run_id}/metrics")
def metric_series(run_id: str, store: DB, scope_type: Literal["run", "article", "shop", "product"],
                  scope_id: str, metric_name: str):
    with views.read_snapshot(store):
        store.get_run(run_id)
        try:
            rows = BackendRunExecutor(store).metric_series(
                run_id, metric_name, scope_type=scope_type, scope_id=scope_id)
        except ValueError as error:
            raise BackendValidationError([{
                "path": "metrics", "code": "INVALID_METRIC_SCOPE", "message": str(error)}]) from error
        return [views.metric_point(store, r) for r in rows]


@app.get("/api/v1/runs/{run_id}/metric-definitions")
def metric_definitions(run_id: str, store: DB):
    return views.metric_definitions(store.run_bundle(run_id))


@app.get("/api/v1/runs/{run_id}/agents/{agent_id}/history")
def agent_history(
    run_id: str, agent_id: str, store: DB, limit: Limit = 50, after: After = None,
    session_no: Annotated[int | None, Query(ge=1)] = None,
    object_type: Literal["article", "product"] | None = None, object_id: str | None = None,
    stage: Literal["A1", "A1R", "A2", "A3", "A4", "A5", "B1", "B1R", "B2", "B3"] | None = None,
    include_all_scores: bool = False,
):
    with views.read_snapshot(store):
        return views.history(
            store, run_id, agent_id, limit=limit, after=after, session_no=session_no,
            object_type=object_type, object_id=object_id, stage=stage,
            include_all_scores=include_all_scores)


@app.get("/api/v1/runs/{run_id}/progress")
def run_progress(run_id: str, store: DB):
    return stream.progress(store, run_id)


@app.get("/api/v1/runs/{run_id}/updates")
def run_updates(run_id: str, store: DB, after: After = None, limit: Limit = 50):
    return stream.updates(store, run_id, after=after, limit=limit)


@app.get("/api/v1/runs/{run_id}/stream")
def run_stream(
    run_id: str, after: After = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID", min_length=1,
                                              max_length=512)] = None,
):
    after = last_event_id if last_event_id is not None else after
    store = _store()
    try:
        with views.read_snapshot(store):
            initial = stream.updates(store, run_id, after=after, limit=100)
            if not initial["items"] and store.run_status(run_id) in {"completed", "failed"}:
                return Response(status_code=204)
    finally:
        store.close()

    def messages():
        batch = initial
        heartbeat = time.monotonic()
        while True:
            for item in batch["items"]:
                yield (f"id: {item['cursor']}\nevent: {item['type']}\n"
                       f"data: {json.dumps(item, ensure_ascii=False)}\n\n")
                if item["type"] in {"run_completed", "run_failed"}:
                    return
            after = batch["next_cursor"]
            if time.monotonic() - heartbeat >= 15:
                yield ": heartbeat\n\n"
                heartbeat = time.monotonic()
            time.sleep(0.25)
            store = _store()
            try:
                batch = stream.updates(store, run_id, after=after, limit=100)
            finally:
                store.close()

    return StreamingResponse(messages(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
