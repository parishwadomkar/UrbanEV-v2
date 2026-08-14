from __future__ import annotations

from dataclasses import dataclass
from collections import deque


@dataclass(frozen=True)
class HallCertificate:
    month: str
    time_index: int
    component_id: int
    origin_demand_kwh_day: float
    destination_nodes: tuple[int, ...]
    origin_labels: tuple[str, ...]
    total_demand_kwh_day: float
    max_served_kwh_day: float
    unavoidable_slack_kwh_day: float
    source_iteration: int
    certificate_kind: str


@dataclass(frozen=True)
class ScreenSummary:
    certificates: tuple[HallCertificate, ...]
    annual_unavoidable_slack_kwh: float
    max_block_slack_kwh_day: float
    violated_blocks: int


class _Edge:
    __slots__ = ("to", "rev", "cap")

    def __init__(self, to: int, rev: int, cap: float) -> None:
        self.to = int(to)
        self.rev = int(rev)
        self.cap = float(cap)


class _Dinic:
    def __init__(self, n: int) -> None:
        self.n = int(n)
        self.g: list[list[_Edge]] = [[] for _ in range(n)]

    def add_edge(self, fr: int, to: int, cap: float) -> None:
        fwd = _Edge(to, len(self.g[to]), cap)
        rev = _Edge(fr, len(self.g[fr]), 0.0)
        self.g[fr].append(fwd)
        self.g[to].append(rev)

    def max_flow(self, source: int, sink: int, tolerance: float = 1e-10) -> float:
        flow = 0.0
        while True:
            level = [-1] * self.n
            level[source] = 0
            q: deque[int] = deque([source])
            while q:
                v = q.popleft()
                for e in self.g[v]:
                    if e.cap > tolerance and level[e.to] < 0:
                        level[e.to] = level[v] + 1
                        q.append(e.to)
            if level[sink] < 0:
                break
            it = [0] * self.n

            def dfs(v: int, pushed: float) -> float:
                if v == sink:
                    return pushed
                while it[v] < len(self.g[v]):
                    e = self.g[v][it[v]]
                    if e.cap > tolerance and level[v] + 1 == level[e.to]:
                        sent = dfs(e.to, min(pushed, e.cap))
                        if sent > tolerance:
                            e.cap -= sent
                            self.g[e.to][e.rev].cap += sent
                            return sent
                    it[v] += 1
                return 0.0

            while True:
                sent = dfs(source, float("inf"))
                if sent <= tolerance:
                    break
                flow += sent
        return flow

    def reachable(self, source: int, tolerance: float = 1e-10) -> set[int]:
        seen = {source}
        q: deque[int] = deque([source])
        while q:
            v = q.popleft()
            for e in self.g[v]:
                if e.cap > tolerance and e.to not in seen:
                    seen.add(e.to)
                    q.append(e.to)
        return seen


@dataclass(frozen=True)
class _Origin:
    kind: str
    hex_id: int
    demand: float
    reachable_destinations: tuple[int, ...]

    @property
    def label(self) -> str:
        return f"{self.kind}:{self.hex_id}"


@dataclass(frozen=True)
class _Block:
    key: tuple[str, int, int]
    nodes: tuple[int, ...]
    origins: tuple[_Origin, ...]
    total_demand: float
    ndays: float


class FeasibilityNetworkOracle:
    """Max-flow/min-cut relaxation of home and public demand fulfillment.

    Home demand can reach only its own cell. Public demand can reach its own cell
    and every active redirection destination. Destination capacity is the total
    installed public charger capacity. A minimum cut yields a Hall-type lower
    bound on unavoidable slack that remains valid for the exact type-aware MIP.
    """

    def __init__(self, data: dict, components: dict, demand_tolerance: float = 1e-10) -> None:
        self.data = data
        self.components = components
        self.demand_tolerance = float(demand_tolerance)
        outgoing: dict[tuple[str, int, int], set[int]] = {}
        for i, j, mon, t in data["allowed_st"]:
            outgoing.setdefault((str(mon), int(t), int(i)), set()).add(int(j))

        blocks: list[_Block] = []
        for key in components["keys"]:
            mon, t, cid = str(key[0]), int(key[1]), int(key[2])
            nodes = tuple(int(i) for i in components["nodes"][(mon, t, cid)])
            node_set = set(nodes)
            origins: list[_Origin] = []
            for i in nodes:
                home = float(data["demand_event_annual"][(i, mon, t, "home")])
                public = float(data["demand_event_annual"][(i, mon, t, "public")])
                if home > self.demand_tolerance:
                    origins.append(_Origin("home", i, home, (i,)))
                if public > self.demand_tolerance:
                    reach = {i}
                    reach.update(j for j in outgoing.get((mon, t, i), set()) if j in node_set)
                    origins.append(_Origin("public", i, public, tuple(sorted(reach))))
            total = sum(o.demand for o in origins)
            blocks.append(
                _Block(
                    key=(mon, t, cid),
                    nodes=nodes,
                    origins=tuple(origins),
                    total_demand=float(total),
                    ndays=float(data["N_MONTH"][mon]),
                )
            )
        self.blocks = tuple(blocks)

    def _capacity(self, x_values: dict[tuple[int, str], int], i: int) -> float:
        return sum(
            float(self.data["charger_capacity_pub"][c]) * float(x_values[(int(i), str(c))])
            for c in self.data["PUB_TYPES"]
        )

    def _screen_block(
        self,
        block: _Block,
        x_values: dict[tuple[int, str], int],
        source_iteration: int,
        certificate_kind: str,
        tolerance: float,
    ) -> HallCertificate | None:
        if block.total_demand <= tolerance or not block.origins:
            return None

        destinations = tuple(sorted({j for o in block.origins for j in o.reachable_destinations}))
        origin_count = len(block.origins)
        source = 0
        origin_offset = 1
        dest_offset = origin_offset + origin_count
        sink = dest_offset + len(destinations)
        network = _Dinic(sink + 1)
        dest_index = {j: dest_offset + k for k, j in enumerate(destinations)}
        infinity = block.total_demand + 1.0

        for k, origin in enumerate(block.origins):
            oi = origin_offset + k
            network.add_edge(source, oi, origin.demand)
            for j in origin.reachable_destinations:
                network.add_edge(oi, dest_index[j], infinity)
        for j in destinations:
            network.add_edge(dest_index[j], sink, self._capacity(x_values, j))

        max_served = network.max_flow(source, sink)
        unavoidable = max(0.0, block.total_demand - max_served)
        if unavoidable <= tolerance:
            return None

        reachable = network.reachable(source)
        selected_origins = [
            origin for k, origin in enumerate(block.origins) if origin_offset + k in reachable
        ]
        selected_destinations = tuple(
            sorted(j for j in destinations if dest_index[j] in reachable)
        )
        origin_demand = sum(o.demand for o in selected_origins)
        cut_capacity = sum(self._capacity(x_values, j) for j in selected_destinations)
        cut_deficiency = origin_demand - cut_capacity
        check_tol = 1e-7 * max(1.0, block.total_demand)
        if abs(cut_deficiency - unavoidable) > check_tol:
            raise RuntimeError(
                f"Min-cut reconstruction failed for {block.key}: "
                f"flow deficiency={unavoidable:.9f}, cut deficiency={cut_deficiency:.9f}."
            )
        if not selected_origins:
            raise RuntimeError(f"Empty source-side origin set for violated block {block.key}.")

        return HallCertificate(
            month=block.key[0],
            time_index=block.key[1],
            component_id=block.key[2],
            origin_demand_kwh_day=float(origin_demand),
            destination_nodes=selected_destinations,
            origin_labels=tuple(sorted(o.label for o in selected_origins)),
            total_demand_kwh_day=float(block.total_demand),
            max_served_kwh_day=float(max_served),
            unavoidable_slack_kwh_day=float(unavoidable),
            source_iteration=int(source_iteration),
            certificate_kind=str(certificate_kind),
        )

    def screen(
        self,
        x_values: dict[tuple[int, str], int],
        source_iteration: int,
        certificate_kind: str = "dynamic_min_cut",
        tolerance: float = 1e-8,
    ) -> ScreenSummary:
        certificates: list[HallCertificate] = []
        annual_slack = 0.0
        max_block = 0.0
        for block in self.blocks:
            certificate = self._screen_block(
                block=block,
                x_values=x_values,
                source_iteration=source_iteration,
                certificate_kind=certificate_kind,
                tolerance=tolerance,
            )
            if certificate is None:
                continue
            certificates.append(certificate)
            annual_slack += block.ndays * certificate.unavoidable_slack_kwh_day
            max_block = max(max_block, certificate.unavoidable_slack_kwh_day)
        return ScreenSummary(
            certificates=tuple(certificates),
            annual_unavoidable_slack_kwh=float(annual_slack),
            max_block_slack_kwh_day=float(max_block),
            violated_blocks=len(certificates),
        )
