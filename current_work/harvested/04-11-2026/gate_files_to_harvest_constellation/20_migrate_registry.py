from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry


def load_registry_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError("registry yaml must be a mapping")
    return payload


def build_registry(payload: dict) -> NodeRegistry:
    registry = NodeRegistry()
    nodes = payload.get("nodes", {})
    if not isinstance(nodes, dict):
        raise ValueError("'nodes' must be a mapping")

    for node_name, config in nodes.items():
        if not isinstance(config, dict):
            raise ValueError(f"node config for {node_name!r} must be a mapping")

        registration = NodeRegistration(
            node_name=node_name,
            internal_url=config["internal_url"],
            supported_actions=tuple(config["supported_actions"]),
            priority_class=config.get("priority_class", "P2"),
            max_concurrent=config.get("max_concurrent", 50),
            health_endpoint=config.get("health_endpoint", "/v1/health"),
            timeout_ms=config.get("timeout_ms", 30_000),
            metadata=config.get("metadata", {}),
        )
        registry.register_node(node_name, registration)

    return registry


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and export node registry config")
    parser.add_argument(
        "--input",
        default="src/constellation_gate/config/node_registry.yaml",
        help="Path to node registry YAML",
    )
    parser.add_argument(
        "--output",
        default="registry_export.json",
        help="Path to exported normalized registry snapshot",
    )
    args = parser.parse_args()

    source_path = Path(args.input)
    payload = load_registry_yaml(source_path)
    registry = build_registry(payload)
    snapshot = {
        name: registration.model_dump(mode="json")
        for name, registration in registry.snapshot().items()
    }

    output_path = Path(args.output)
    output_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
    print(f"exported {len(snapshot)} nodes to {output_path}")


if __name__ == "__main__":
    main()
