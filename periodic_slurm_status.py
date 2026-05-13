"""
Non-science and other meta plots.
"""
import pyslurm # type: ignore[import-not-found]
import matplotlib

matplotlib.use("Agg")
import click
import math
import pwd
import re
import subprocess
from datetime import datetime
from typing import List, Tuple, Any, Union
from dataclasses import dataclass, field
from enum import Enum, auto

import matplotlib.pyplot as plt
import numpy as np



class PartitionType(Enum):
    REGULAR = auto()
    GPU = auto()
    LOGIN = auto()

@dataclass
class PartitionProfile:
    name: str
    type: PartitionType
    title: str
    output_template: str = "{name}_stat_1.png"

    def get_node_filter(self, parts: dict) -> List[str]:
        """Return node names for this partition."""
        # TODO: specialize per-type once GPU/LOGIN profiles are added.
        return _expandNodeList(parts.get(self.name, {}).get("nodes", ""))
    
    def get_title(self) -> str:
        return f"MIDWAY3 {self.title}"

@dataclass
class PlotConfig:
    cores_per_node: int = 48
    cpus_per_node: int = 2
    n_hyper: int = 1  # Enable HTing with 2
    alloc_states: List[str] = field(default_factory=lambda: ["ALLOCATED", "MIXED"])
    idle_states: List[str] = field(default_factory=lambda: ["IDLE"])
    down_states: List[str] = field(default_factory=lambda: [
        "DOWN", "DRAINED", "ERROR", "FAIL", "FAILING", "POWER_DOWN", "IDLE+DRAIN", "DOWN*+DRAIN", "UNKNOWN"
    ])
    n_groups: int = 6
    fig_size: Tuple[float, float] = (18.9, 11.2)
    dpi: int = 350
    output_dpi: int = 100
    health_panel_pos: Tuple[float, float] = (0.8, 0.88)
    stats_panel_pos: Tuple[float, float] = (0.006, 0.91)
    header_pos: Tuple[float, float] = (1 - 0.994, 0.99)
    updated_pos: Tuple[float, float] = (0.995, 0.995)

def get_partition_profiles(partition: str) -> PartitionProfile:
    # TODO (scaling refactor): detect GPU/LOGIN partitions from parts/nodes data.
    return PartitionProfile(
        name=partition,
        type=PartitionType.REGULAR,  
        title=f"{partition} Status",
    )
def _expandNodeList(nodeListStr: str) -> List[str]:
        if not nodeListStr:
            return []
        cmd = ["scontrol", "show", "hostnames", nodeListStr]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True, 
                text=True, 
                check=True, 
                timeout=10)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"Timeout while expanding node list '{nodeListStr}': {e}") from e
        
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Error while expanding node list '{nodeListStr}': {e.stderr.strip()}") from e

        

        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

def _node_sort_key(nodeName: str) -> Tuple[str, int]:
        match = re.match(r"^(.*?)-(\d+)$", nodeName)
        if match:
            return (match.group(1), int(match.group(2)))
        return (nodeName, 0)

def _build_node_groups(nodeNames: List[str], n_groups: int = 6) -> List[Tuple[str, List[str]]]:
        sorted_nodes = sorted(nodeNames, key=_node_sort_key)
        if not sorted_nodes:
            return []

        n_groups = min(n_groups, len(sorted_nodes))
        chunk_size = int(np.ceil(len(sorted_nodes) / n_groups))
        groups = []
        for i in range(n_groups):
            group_nodes = sorted_nodes[i * chunk_size : (i + 1) * chunk_size]
            if group_nodes:
                groups.append((f"group {i + 1}", list(reversed(group_nodes))))
        return groups

def _normalize_partitions(raw_parts: Union[dict, List[Any]]) -> dict:
        """Return partitions with stable dict fields across PySlurm API versions."""
        if isinstance(raw_parts, list):
                return {} 
        normalized = {}
        for name, part in raw_parts.items():
            if isinstance(part, dict):
                nodes = part.get("nodes", "")
                total_nodes = part.get("total_nodes")
                total_cpus = part.get("total_cpus")
            else:
                nodes = getattr(part, "nodes", "")
                total_nodes = getattr(part, "total_nodes", None)
                total_cpus = getattr(part, "total_cpus", None)

            if total_nodes is None:
                total_nodes = len(_expandNodeList(nodes)) if nodes else 0
            if total_cpus is None:
                total_cpus = 0

            normalized[name] = {
                "nodes": nodes,
                "total_nodes": int(total_nodes),
                "total_cpus": int(total_cpus),
            }

        return normalized

def collect_slurm_data() -> Tuple[dict, dict, dict, dict, datetime]:
    """Fetch current SLURM jobs, stats, nodes, and partitions."""
    try:
        jobs = pyslurm.job().get()
        stats = pyslurm.statistics().get()
        nodes = pyslurm.node().get()
        if hasattr(pyslurm, "Partitions"):
            parts = _normalize_partitions(pyslurm.Partitions.load())
        else:
            parts = _normalize_partitions(pyslurm.partition().get())
        cur_time = datetime.fromtimestamp(stats["req_time"])
        return jobs, stats, nodes, parts, cur_time
    except Exception as e:
        raise RuntimeError(f"Failed to collect SLURM data: {e}")
    
def filter_data_by_partition(jobs: dict, 
                             nodes: dict, 
                             parts: dict, 
                             profile: PartitionProfile) -> Tuple[List[dict], List[dict], List[str], List[dict]]:
    """Filter jobs and nodes for the given partition."""
    if profile.name not in parts:
        raise RuntimeError(f"Partition '{profile.name}' not found in SLURM.")
    
    nodes_in_part = profile.get_node_filter(parts)
    nodes_in_part_set = set(nodes_in_part)
    
    jobs_running = [j for j in jobs.values() if j.get("partition") == profile.name and j["job_state"] == "RUNNING"]
    jobs_pending = [j for j in jobs.values() if j.get("partition") == profile.name and j["job_state"] == "PENDING"]
    
    # Attach job info to nodes
    for job in jobs_running:
        for node_name in job.get("cpus_allocated", {}):
            if node_name in nodes_in_part_set and node_name in nodes:
                if "cur_job_owner" not in nodes[node_name]:
                    nodes[node_name]["cur_job_owner"] = pwd.getpwuid(job["user_id"])[4].split(",")[0]
                    nodes[node_name]["cur_job_id"] = job["job_id"]
                    nodes[node_name]["cur_job_runtime"] = job["run_time_str"]
    
    nodes_main = [nodes[name] for name in nodes_in_part if name in nodes]
    
    
    return jobs_running, jobs_pending, nodes_in_part, nodes_main

def compute_statistics(
    jobs_running: List[dict],
    jobs_pending: List[dict],
    nodes_main: List[dict],
    parts: dict,
    profile: PartitionProfile,
    config: PlotConfig,
    cur_time: datetime
) -> dict:
    """Compute node/core statistics."""
    # Node categorization
    nodes_idle = [n for n in nodes_main if any(n["state"] == s for s in config.idle_states)]
    nodes_alloc = [n for n in nodes_main if any(n["state"] == s for s in config.alloc_states)]
    nodes_down = [n for n in nodes_main if any(n["state"] == s for s in config.down_states)]

    # Core calculations
    n_cores = parts[profile.name]["total_cpus"]
    if n_cores == 0:
        n_cores = parts[profile.name]["total_nodes"] * config.cores_per_node
    n_cores_alloc = int(sum(j.get("num_cpus", 0) for j in jobs_running) / config.n_hyper)
    n_cores_idle = int(n_cores - n_cores_alloc)

    # Load stats
    cluster_load = float(n_cores_alloc) / n_cores * 100 if n_cores else 0.0
    cpu_load_alloc_mean = (
        np.mean(
            [
                float(n["cpu_load"]) / (n.get("cpus", config.cores_per_node) / config.n_hyper)
                for n in nodes_alloc
            ]
        )
        if nodes_alloc
        else 0.0
    )

    # Job stats
    pending_reasons = [j["state_reason"] for j in jobs_pending]
    n_pending_resources = pending_reasons.count("Resources")
    n_pending_priority = pending_reasons.count("Priority")
    n_pending_dependency = pending_reasons.count("Dependency")
    n_pending_userheld = pending_reasons.count("JobHeldUser")

    next_job_starting = (
        jobs_pending[pending_reasons.index("Resources")] if "Resources" in pending_reasons else None
    )
    if next_job_starting:
        next_job_starting["user_name"] = pwd.getpwuid(next_job_starting["user_id"])[0]

    queue_pressure = float(len(jobs_pending)) / len(jobs_running) if jobs_running else math.inf
    pending_wait_seconds = []
    for job in jobs_pending:
        submit_time = job.get("submit_time")
        if submit_time is None:
            continue
        pending_wait_seconds.append(max(0, int(cur_time.timestamp()) - int(job["submit_time"])))
    p90_wait_seconds = (
        int(np.percentile(pending_wait_seconds, 90)) if pending_wait_seconds else None
    )

    user_cores: dict[str, float] = {}
    for job in jobs_running:
        uid = job.get("user_id")
        if uid is None:
            continue
        try:
            username = pwd.getpwuid(uid).pw_name
        except KeyError:
            username = str(uid)
        user_cores[username] = user_cores.get(username, 0.0) + (
            float(job.get("num_cpus", 0)) / config.n_hyper
        )

    if user_cores:
        top_user, top_user_cores = max(user_cores.items(), key=lambda item: item[1])
    else:
        top_user, top_user_cores = ("n/a", 0.0)

    return {
        "nodes_idle": nodes_idle,
        "nodes_alloc": nodes_alloc,
        "nodes_down": nodes_down,
        "n_cores": n_cores,
        "n_cores_alloc": n_cores_alloc,
        "n_cores_idle": n_cores_idle,
        "cluster_load": cluster_load,
        "cpu_load_alloc_mean": cpu_load_alloc_mean,
        "jobs_running": len(jobs_running),
        "jobs_pending": len(jobs_pending),
        "n_pending_resources": n_pending_resources,
        "n_pending_priority": n_pending_priority,
        "n_pending_dependency": n_pending_dependency,
        "n_pending_userheld": n_pending_userheld,
        "queue_pressure": queue_pressure,
        "p90_wait_seconds": p90_wait_seconds,
        "top_user": top_user,
        "top_user_cores": top_user_cores,
        "next_job_starting": next_job_starting,
    }

def generate_plot(
    nodes_in_part: List[str],
    nodes_main: List[dict],
    stats: dict,
    profile: PartitionProfile,
    config: PlotConfig,
    cur_time: datetime,
) -> plt.Figure:

    """Generate the matplotlib plot."""
    nodeGroups = _build_node_groups(nodes_in_part, config.n_groups)
    if not nodeGroups:
        raise RuntimeError(f"No nodes to plot for partition {profile.name}.")
    
    node_dict = {n["name"]: n for n in nodes_main}
    maxNodesPerRack = max(len(rackNodes) for _, rackNodes in nodeGroups)
    nodeHeadroom = 1
    nodes_down_set = {n["name"] for n in stats["nodes_down"]}
    nodes_alloc_set = {n["name"] for n in stats["nodes_alloc"]}
    nodes_idle_set = {n["name"] for n in stats["nodes_idle"]}

    fig = plt.figure(figsize=config.fig_size, tight_layout=False, dpi=config.dpi)

    for i, (groupName, rackNodes) in enumerate(nodeGroups):
        print(groupName, len(rackNodes))

        ax = fig.add_subplot(1, len(nodeGroups), i + 1)

        ax.set_xlim((0, 1))
        ax.set_ylim((-1, maxNodesPerRack + nodeHeadroom))
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.get_xaxis().set_visible(False)
        ax.get_yaxis().set_visible(False)
        # Use a custom rack frame so the top border sits below the header text.
        for spine in ["top", "right", "left", "bottom"]:
            ax.spines[spine].set_visible(False)
        rack_bottom = -1
        rack_top = len(rackNodes)
        ax.plot([0, 1], [rack_bottom, rack_bottom], "-", lw=1.5, color="black")
        ax.plot([0, 1], [rack_top, rack_top], "-", lw=1.5, color="black")
        ax.plot([0, 0], [rack_bottom, rack_top], "-", lw=2.0, color="black")
        ax.plot([1, 1], [rack_bottom, rack_top], "-", lw=2.5, color="black")

        # draw representation of each node
        for j, name in enumerate(rackNodes):
            # Look up this node's actual core count from SLURM; fall back to config default
            # if the field is missing (e.g. node draining or not yet reporting).
            node = node_dict.get(name)
            node_cores = int(node["cpus"]) if node and "cpus" in node else config.cores_per_node
            cores_per_socket = node_cores / config.cpus_per_node

            # circle: color by status
            color = "gray"
            if name in nodes_down_set:
                color = "red"
            elif name in nodes_alloc_set:
                color = "green"
            elif name in nodes_idle_set:
                color = "orange"
            ax.plot(0.14, j, "o", color=color, markersize=10.0)
            textOpts: dict[str, Any] = {
                "fontsize": 8.0,
                "horizontalalignment": "left",
                "verticalalignment": "center",
            }

            pad = 0.10
            xmin = 0.18
            xmax = 0.475
            padx = 0.002
            dx = (xmax - xmin) / cores_per_socket

            # load
            load = 0.0
            if node is not None:
                try:
                    load = float(node["cpu_load"]) / (node_cores / config.n_hyper)
                except (KeyError, ZeroDivisionError):
                    pass
            ax.text(xmax + padx * 10, j, "%.0f%%" % load, color="#333333", **textOpts)

            # individual cores (simplified, assuming cpusPerNode <= 2 for now)
            for k in range(config.cpus_per_node):
                if k == 0:
                    y0 = j - 0.5 + pad
                    y1 = j - pad / 2
                elif k == 1:
                    y0 = j + pad / 2
                    y1 = j + 0.5 - pad
                else:
                    continue  # Skip if >2, as per earlier bug

                cores_loaded = int(cores_per_socket * load / 100)
                cores_total = int(cores_per_socket)

                for m in range(min(cores_loaded, cores_total)):
                    ax.fill_between(
                        [xmin + m * dx + padx, xmin + (m + 1) * dx - padx],
                        [y0, y0],
                        [y1, y1],
                        facecolor=color,
                        alpha=0.3,
                    )
                for m in range(min(cores_loaded, cores_total), cores_total):
                    ax.fill_between(
                        [xmin + m * dx + padx, xmin + (m + 1) * dx - padx],
                        [y0, y0],
                        [y1, y1],
                        facecolor="gray",
                        alpha=0.3,
                    )

            # node name
            ax.text(0.02, j, name.replace("midway3-", ""), color="#222222", **textOpts)

            try:
                node = node_dict[name]
                if "cur_job_id" in node:
                    id = node["cur_job_id"]
                    ax.text(
                        xmax + 0.14 + padx * 10,
                        j,
                        id,
                        color="#333333",
                        **textOpts,
                    )
            except IndexError:
                pass

    fig.subplots_adjust(left=0.005, right=0.995, bottom=0.005, top=0.82, wspace=0.05)

    stats_lines = [
        "nodes: %d total, %d idle, %d allocated, %d down"
        % (
            len(nodes_main),
            len(stats["nodes_idle"]),
            len(stats["nodes_alloc"]),
            len(stats["nodes_down"]),
        ),
        "cores: %d total, %d allocated, %d idle/unavailable"
        % (stats["n_cores"], stats["n_cores_alloc"], stats["n_cores_idle"]),
        "load: %.1f%% cluster, %.1f%% mean node CPU"
        % (stats["cluster_load"], stats["cpu_load_alloc_mean"]),
        "jobs: %d running, %d waiting, %d userheld, %d dependent"
        % (
            stats["jobs_running"],
            stats["n_pending_resources"] + stats["n_pending_priority"],
            stats["n_pending_userheld"],
            stats["n_pending_dependency"],
        ),
    ]
    statsText = "\n".join(stats_lines)
    updatedText = "Last Updated\n%s\n%s" % (
        cur_time.strftime("%a %d %b"),
        cur_time.strftime("%H:%M"),
    )
    


    if stats["p90_wait_seconds"] is None:
        p90_wait_str = "n/a"
    elif stats["p90_wait_seconds"] < 3600:
        p90_wait_str = f"{stats['p90_wait_seconds'] // 60}m"
    else:
        p90_wait_str = f"{stats['p90_wait_seconds'] / 3600.0:.1f}h"

    if math.isinf(stats["queue_pressure"]):
        queue_pressure_str = "inf"
    else:
        queue_pressure_str = f"{stats['queue_pressure']:.2f}"

    health_lines = [
        "Health Panel (quick guide)",
        f"queue pressure (pending/running): {queue_pressure_str}",
        f"p90 wait (90% start sooner): {p90_wait_str}",
    ]
    healthText = "\n".join(health_lines)
    headerBox = dict(facecolor="white", alpha=0.75, edgecolor="none", pad=2.0)

    ax.annotate(
            profile.get_title(),
            config.header_pos,
            xycoords="figure fraction",
            fontsize=34.0,
            horizontalalignment="left",
            verticalalignment="top",
            bbox=headerBox,
        )
    ax.annotate(
            updatedText,
            config.updated_pos,
            xycoords="figure fraction",
            fontsize=12.0,
            horizontalalignment="right",
            verticalalignment="top",
            color="green",
            bbox=headerBox,
        )
    ax.annotate(
            healthText,
            config.health_panel_pos,
            xycoords="figure fraction",
            fontsize=12.0,
            horizontalalignment="left",
            verticalalignment="top",
            linespacing=1.3,
            bbox=headerBox,
        )
    ax.annotate(
            statsText,
            config.stats_panel_pos,
            xycoords="figure fraction",
            fontsize=16.5,
            horizontalalignment="left",
            verticalalignment="top",
            linespacing=1.35,
            bbox=headerBox,
        )
    return fig
def periodic_slurm_status(partition: str, output_image: str, nosave: bool = False) -> None:
    """Collect current statistics from the SLURM scheduler and make plots."""
    profile = get_partition_profiles(partition)
    config = PlotConfig()

    try:
        jobs, stats, nodes, parts, curTime = collect_slurm_data()
        jobs_running, jobs_pending, nodes_in_part, nodes_main = filter_data_by_partition(jobs, nodes, parts, profile)
        computed_stats = compute_statistics(jobs_running, jobs_pending, nodes_main, parts, profile, config, curTime)
        fig = generate_plot(nodes_in_part, nodes_main, computed_stats, profile, config, curTime)
        if not nosave:
            fig.savefig(output_image, dpi=config.output_dpi)
            print(f"Saved SLURM status plot to {output_image}")
        else:
            print("Dry run mode: plot generated but not saved.")
    except Exception as e:
        print(f"Error generating SLURM status plot: {e}")



@click.command()
@click.option('--partition', '-p', help= 'SLURM partition name', default='caslake')
@click.option('--dry-run', '-n', is_flag=True, help='Compatibility flag; historical data storage is disabled.')
def main(partition: str, dry_run: bool):
    """Entry point for command-line execution."""
    profile = get_partition_profiles(partition)
    output_image = profile.output_template.format(name=profile.name, partition=profile.name)
    periodic_slurm_status(partition=partition, output_image=output_image, nosave=dry_run)

    

if __name__ == "__main__":
    main()
