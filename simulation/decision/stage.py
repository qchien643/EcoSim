"""One-stage execution: context in, model gateway, policy result, store commit."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol
from time import monotonic
from gateways.types import GatewayResponse
from gateways.jev import GatewayUnavailable

from simulation.decision.policy import final_status, resolve
from ..context.service import ContextService



class ModelGateway(Protocol):
    def decide(self, stage: str, context: dict[str, Any]) -> GatewayResponse:
        ...


class StageService:
    def __init__(self, store: Any, primary: ModelGateway,
                 fallback: ModelGateway | None = None,
                 context_service: ContextService | None = None):
        self.store = store
        self.primary = primary
        self.fallback = fallback
        self.context_service = context_service or ContextService(store)

    def clone_for_store(self, store: Any) -> "StageService":
        """Create an isolated worker service with the same gateway configuration."""
        if type(self.context_service) is not ContextService:
            raise ValueError("Custom context services require worker_stage_factory")
        return StageService(
            store,
            deepcopy(self.primary),
            deepcopy(self.fallback) if self.fallback is not None else None,
            ContextService(store),
        )

    def _attempt(self, gateway, stage_key, stage, request_context, source):
        """Reuse a persisted response if a crash preceded the event commit."""
        request = {"stage": stage, "context": request_context}
        provider = getattr(gateway, "provider", "unknown")
        model = getattr(gateway, "model", "unknown")
        cached = self.store.model_response(stage_key, request, provider, model)
        if cached is not None:
            return cached["call_id"], GatewayResponse(
                cached["output"], cached["provider"], cached["model"], request
            )
        call_id, _ = self.store.start_model_call(stage_key, request, provider, model)
        start = monotonic()
        try:
            response = gateway.decide(stage, request_context)
        except GatewayUnavailable:
            # A transport/provider failure is not a behavioral action. Keep the
            # failed attempt auditable so the caller can invoke the fallback.
            self.store.fail_model_attempt(call_id, "provider_unavailable")
            return call_id, GatewayResponse(
                {"status": "invalid", "source": source,
                 "reason": "provider_unavailable"},
                provider, model, request,
            )
        except ValueError:
            # A malformed model answer is not a behavioral action or a storage
            # error. The caller may invoke the fallback with the same context.
            self.store.fail_model_attempt(call_id, "invalid_output")
            return call_id, GatewayResponse(
                {"status": "invalid", "source": source,
                 "reason": "invalid_output"},
                provider, model, request,
            )
        except Exception as error:
            self.store.fail_model_attempt(call_id, type(error).__name__)
            raise
        output = {**response.output, "source": response.output.get("source", source)}
        self.store.set_model_identity(call_id, response.provider, response.model)
        result = resolve(stage, output, history=request_context["history"],
                         has_attended=request_context["history"].get("attention_count", 0) > 0,
                         bundle=self.store.run_bundle(request_context["input"]["scope"]["run_id"]))
        self.store.commit_model_attempt(
            call_id, output, result["status"], elapsed_ms=(monotonic() - start) * 1000
        )
        return call_id, GatewayResponse(output, response.provider, response.model, request)

    def execute(self, *, run_id: str, session_id: str, agent_id: str,
                object_type: str, object_id: str, encounter_no: int,
                stage: str, context: dict[str, Any],
                parent_event_id: str | None = None) -> dict[str, Any]:
        stage_key = self.store.stage_key(
            run_id, session_id, agent_id, object_type, object_id,
            encounter_no, stage,
        )
        existing = self.store.event_by_key(stage_key)
        if existing is not None:
            return existing
        context_snapshot = self.context_service.build(
            run_id=run_id,
            session_id=session_id,
            agent_id=agent_id,
            object_type=object_type,
            object_id=object_id,
            encounter_no=encounter_no,
            stage=stage,
            parent_event_id=parent_event_id,
        )
        request_context = {
            **context_snapshot,
            "state": context_snapshot["rendered"]["decision_state"],
            "tag_registry": self.store.run_bundle(run_id)["tag_registry"],
        }
        history = context_snapshot["history"]
        has_attended = history.get("attention_count", 0) > 0

        primary_call, primary = self._attempt(
            self.primary, stage_key, stage, request_context, "jev"
        )
        primary_result = resolve(
            stage, {**primary.output, "source": primary.output.get("source", "jev")},
            history=history, has_attended=has_attended, bundle=self.store.run_bundle(run_id),
        )
        primary_result["source"] = primary.output.get("source", "jev")

        chosen = primary
        chosen_result = primary_result
        if primary_result["status"] != "resolved" and self.fallback is not None:
            fallback_key = f"{stage_key}#fallback"
            fallback_call, fallback = self._attempt(
                self.fallback, fallback_key, stage, request_context, "llm_fallback"
            )
            chosen = fallback
            fallback_result = resolve(
                stage,
                {**fallback.output,
                 "source": fallback.output.get("source", "llm_fallback")},
                history=history, has_attended=has_attended, bundle=self.store.run_bundle(run_id),
            )
            fallback_result["source"] = fallback.output.get("source", "llm_fallback")
            if fallback_result["status"] == "resolved":
                chosen, chosen_result = fallback, fallback_result
                call_id = fallback_call
            else:
                call_id = fallback_call
                chosen_result = {
                    **fallback_result,
                    "status": final_status(
                        primary_result["status"], fallback_result["status"]
                    ),
                }
        else:
            call_id = primary_call
            if primary_result["status"] != "resolved":
                chosen_result = {
                    **primary_result,
                    "status": final_status(primary_result["status"], None),
                }

        result = self.store.commit_stage(
            call_id=call_id,
            stage_key=stage_key,
            response=chosen.output,
            result=chosen_result,
            run_id=run_id,
            session_id=session_id,
            agent_id=agent_id,
            object_type=object_type,
            object_id=object_id,
            encounter_no=encounter_no,
            stage=stage,
            parent_event_id=parent_event_id,
            cursor={
                "session_id": session_id,
                "agent_id": agent_id,
                "object_type": object_type,
                "object_id": object_id,
                "stage": stage,
            },
        )
        return {**result, "source": chosen_result.get("source")}
