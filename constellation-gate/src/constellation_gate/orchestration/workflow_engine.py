from __future__ import annotations

from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket
from constellation_node_sdk.transport.provenance import RoutingProvenance

from constellation_gate.orchestration.condition_eval import SafeConditionEvaluator
from constellation_gate.orchestration.workflow_models import WorkflowDefinition, WorkflowStep
from constellation_gate.resilience.deadline import PacketDeadline
from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistry


class WorkflowEngine:
    """
    Packet-native sequential workflow engine executed inside Gate.

    Gate remains the routing authority. Each workflow step is emitted as a child
    packet back through Gate-owned dispatch.
    """

    def __init__(
        self,
        definitions: dict[str, WorkflowDefinition],
        dispatcher: Dispatcher,
        *,
        local_node: str = "gate",
        condition_evaluator: SafeConditionEvaluator | None = None,
        registry: NodeRegistry | None = None,
    ) -> None:
        self._definitions = {
            name.strip().lower(): definition for name, definition in definitions.items()
        }
        self._dispatcher = dispatcher
        self._local_node = local_node.strip().lower()
        self._condition_evaluator = condition_evaluator or SafeConditionEvaluator()
        self._registry = registry
        if self._registry is not None:
            self.validate_definitions_against_registry()

    @property
    def registry(self) -> NodeRegistry | None:
        return self._registry

    def validate_definitions_against_registry(self) -> None:
        """Ensure workflow step actions are not backed by a private action index.

        When the shared registry already has registrations, every step action must
        either be another workflow name or an action advertised in that registry.
        Empty registries defer checks until nodes register (execute still resolves
        via the same registry through Dispatcher).
        """
        if self._registry is None:
            return
        registered_actions = self._registry.all_supported_actions()
        if not registered_actions:
            return
        known = set(self._definitions) | registered_actions
        for workflow_name, definition in self._definitions.items():
            for step in definition.steps:
                action = step.action.strip().lower()
                if action not in known:
                    raise ValueError(
                        f"workflow {workflow_name!r} step action {action!r} is not "
                        "present in the shared NodeRegistry (registration/workflow "
                        "must use the same registry)"
                    )

    def has_workflow(self, name: str) -> bool:
        return name.strip().lower() in self._definitions

    async def execute(
        self,
        packet: TransportPacket,
        *,
        deadline: PacketDeadline | None = None,
    ) -> TransportPacket:
        """Run a composite workflow.

        Every step goes through the same Gate-owned dispatcher and consumes the
        SAME packet deadline. A workflow must not be able to buy itself a fresh
        budget per step: N steps under one 30s packet budget is 30s total, not
        N x 30s.
        """
        workflow_name = packet.header.action.strip().lower()
        if workflow_name not in self._definitions:
            raise LookupError(f"no workflow defined for action: {workflow_name}")

        definition = self._definitions[workflow_name]
        current_payload: dict[str, Any] = dict(packet.payload)
        latest_response_payload: dict[str, Any] | None = None
        current_packet = packet

        for step in definition.steps:
            if not self._should_execute_step(
                step,
                payload=current_payload,
                response=latest_response_payload,
                accumulated=current_payload,
            ):
                continue

            step_packet = current_packet.derive(
                packet_type="request",
                action=step.action,
                source_node=self._local_node,
                destination_node=self._local_node,
                reply_to=self._local_node,
                payload=dict(current_payload),
                provenance=RoutingProvenance(
                    origin_kind="gate",
                    requested_action=step.action,
                    resolved_by_gate=False,
                    original_source_node=packet.address.source_node,
                ),
                timeout_ms=self._step_timeout_ms(
                    step_timeout_ms=step.timeout_ms,
                    packet_timeout_ms=current_packet.header.timeout_ms,
                    deadline=deadline,
                ),
            )

            step_response = await self._dispatcher.dispatch(step_packet, deadline=deadline)
            latest_response_payload = dict(step_response.payload)
            current_payload = self._merge_payload(
                step=step,
                current=current_payload,
                response=latest_response_payload,
            )
            current_packet = step_response

        return packet.derive(
            packet_type="response",
            source_node=self._local_node,
            destination_node=packet.address.reply_to,
            reply_to=self._local_node,
            payload=current_payload,
            provenance=RoutingProvenance(
                origin_kind="gate",
                requested_action=workflow_name,
                resolved_by_gate=True,
                original_source_node=packet.address.source_node,
            ),
        )

    @staticmethod
    def _step_timeout_ms(
        *,
        step_timeout_ms: int | None,
        packet_timeout_ms: int | None,
        deadline: PacketDeadline | None,
    ) -> int | None:
        """Clamp a step's declared timeout to the packet's remaining budget.

        A step config may declare a generous per-step timeout; it may not use it
        to outlive the packet that authorized the work.
        """
        declared = step_timeout_ms if step_timeout_ms is not None else packet_timeout_ms
        if deadline is None:
            return declared
        remaining_ms = int(deadline.remaining_or_raise() * 1000)
        remaining_ms = max(1, remaining_ms)
        if declared is None:
            return remaining_ms
        return min(declared, remaining_ms)

    def _should_execute_step(
        self,
        step: WorkflowStep,
        *,
        payload: dict[str, Any],
        response: dict[str, Any] | None,
        accumulated: dict[str, Any],
    ) -> bool:
        if step.condition is None:
            return True
        return self._condition_evaluator.evaluate(
            step.condition,
            payload=payload,
            response=response,
            action=step.action,
            accumulated=accumulated,
        )

    @staticmethod
    def _merge_payload(
        *,
        step: WorkflowStep,
        current: dict[str, Any],
        response: dict[str, Any],
    ) -> dict[str, Any]:
        if step.merge_strategy == "identity":
            return dict(response)

        if step.merge_strategy == "merge_results":
            merged = dict(current)
            response_data = response.get("data")
            if isinstance(response_data, dict):
                merged.update(response_data)
                return merged
            merged.update(response)
            return merged

        merged = dict(current)
        merged.update(response)
        return merged
