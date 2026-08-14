from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LPBendersCut:
    month: str
    time_index: int
    component_id: int
    constant: float
    coefficients: dict[tuple[int, str], float]
    source_iteration: int
    lp_value: float
    source_kind: str = "incumbent"


@dataclass(frozen=True)
class ComponentLogicOptimalityCut:
    month: str
    time_index: int
    component_id: int
    operation_upper_bound: float
    x_values: dict[tuple[int, str], int]
    source_iteration: int
    source_kind: str = "incumbent"


def build_slot_components(data: dict) -> dict:
    """Build connected redirection components for each month and time slot."""
    hex_ids = [int(i) for i in data["hex_ids"]]
    arcs_by_slot: dict[tuple[str, int], list[tuple[int, int]]] = {
        (str(mon), int(t)): [] for mon in data["MONTHS"] for t in data["INTERVALS"]
    }
    for i, j, mon, t in data["allowed_st"]:
        arcs_by_slot[(str(mon), int(t))].append((int(i), int(j)))

    keys: list[tuple[str, int, int]] = []
    nodes: dict[tuple[str, int, int], tuple[int, ...]] = {}
    node_to_component: dict[tuple[str, int, int], int] = {}

    for mon in data["MONTHS"]:
        for t in data["INTERVALS"]:
            parent = {i: i for i in hex_ids}

            def find(a: int) -> int:
                while parent[a] != a:
                    parent[a] = parent[parent[a]]
                    a = parent[a]
                return a

            def union(a: int, b: int) -> None:
                ra, rb = find(a), find(b)
                if ra == rb:
                    return
                if ra < rb:
                    parent[rb] = ra
                else:
                    parent[ra] = rb

            for i, j in arcs_by_slot[(str(mon), int(t))]:
                union(i, j)

            groups: dict[int, list[int]] = {}
            for i in hex_ids:
                groups.setdefault(find(i), []).append(i)
            ordered = sorted((tuple(sorted(v)) for v in groups.values()), key=lambda v: (v[0], len(v)))
            for cid, component_nodes in enumerate(ordered):
                key = (str(mon), int(t), int(cid))
                keys.append(key)
                nodes[key] = component_nodes
                for i in component_nodes:
                    node_to_component[(str(mon), int(t), int(i))] = int(cid)

    return {
        "keys": keys,
        "nodes": nodes,
        "node_to_component": node_to_component,
        "arcs_by_slot": arcs_by_slot,
    }
