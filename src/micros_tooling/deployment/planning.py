"""Read-only, versioned deployment reports over verified release receipts."""

import json

from micros_tooling.deployment.deploy import NO_BANK, running


def _services(receipt):
    result = {s["name"]: dict(version=s["version"])
              for s in (receipt or {}).get("services", [])}
    for name, detail in (receipt or {}).get("details", {}).items():
        result.setdefault(name, {}).update(detail)
    return result


def restart_scope(status, old, new, force=False):
    """Conservative preview; firmware verifies exact image bytes at activation."""
    all_names = sorted(old.keys() | new.keys())
    if force or not status.get("selective_deploy"):
        return "whole_application", all_names, "Forced activation or base lacks selective deployment."
    if old.keys() != new.keys() or not old:
        return "whole_application", all_names, "Service membership changed or the previous release is unknown."
    if not running(status, len(old)):
        return "whole_application", all_names, "Current application is not fully running."
    required = {"slot", "image_sha256", "configuration_hex", "capabilities", "memory", "channels", "board_bindings"}
    if any(not required <= d.keys() for d in [*old.values(), *new.values()]):
        return "device_decides", all_names, "Missing comparison metadata; firmware determines restart scope."
    def order(items):
        return sorted(items, key=lambda n: (any(c["access"] == "publish" for c in items[n]["channels"]), n))
    def channels(items):
        return {str(c["key"]): {k: v for k, v in c.items() if k != "access"}
                for d in items.values() for c in d["channels"]}
    if (order(old) != order(new) or channels(old) != channels(new) or
        any(old[n]["slot"] != new[n]["slot"] or old[n]["board_bindings"] != new[n]["board_bindings"] for n in old)):
        return "whole_application", all_names, "Shared channel, wiring, ordering or slot layout changed."
    affected = [n for n in sorted(old) if any(old[n][k] != new[n][k]
                for k in ("image_sha256", "configuration_hex", "capabilities", "memory"))]
    return "selective", affected, "Only changed services reload; peers pause briefly for flash writes and the mapping switch."


def _semantic(detail):
    result = {key: value for key, value in detail.items() if key != "headroom"}
    # Key channels by their stable numeric identity and direction, not list position.
    if "channels" in result:
        result["channels"] = {f'{c["key"]}:{c["access"]}': c for c in result["channels"]}
    if "board_bindings" in result:
        result["board_bindings"] = dict(result["board_bindings"])
        result["board_bindings"]["gpio"] = {
            str(g["line"]): g for g in result["board_bindings"].get("gpio", [])}
    if "capabilities" in result:
        result["capabilities"] = dict(result["capabilities"])
        if "gpio" in result["capabilities"]:
            result["capabilities"]["gpio"] = sorted(result["capabilities"]["gpio"])
    return result


def _diff(path, before, after):
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(before.keys() | after.keys()):
            if key not in before or key not in after:
                result.append(dict(path=[*path, key],
                                   action="add" if key in after else "remove",
                                   before=before.get(key), after=after.get(key)))
            else:
                result.extend(_diff([*path, key], before[key], after[key]))
        return result
    return [dict(path=path, action="change", before=before, after=after)]


def resource_totals(receipt):
    """Reservations only; channel payload capacity excludes runtime bookkeeping."""
    details = (receipt or {}).get("details", {})
    names = set(_services(receipt))
    complete = bool(names) and names <= details.keys()
    result = {}
    for metric, section, field in (
        ("requested_stack_bytes", "memory", "stack_bytes"),
        ("arena_bytes", "memory", "arena_bytes"),
        ("handles", "capabilities", "handles"),
        ("timers", "capabilities", "timers"),
    ):
        result[metric] = (sum(details[n][section][field] for n in names)
                          if complete and all(field in details[n].get(section, {}) for n in names)
                          else None)
    channels = {}
    if complete and all("channels" in details[n] for n in names):
        for name in sorted(names):
            for channel in details[name]["channels"]:
                channels[channel["key"]] = channel
        result["channel_payload_bytes"] = sum(c["depth"] * c["max_payload"] for c in channels.values())
    else:
        result["channel_payload_bytes"] = None
    result["image_bytes"] = (receipt or {}).get("resources", {}).get("image_bytes")
    return result


def deployment_plan(inspection, current, requested, *, device=None, force=False):
    """Explain one inspected board transition without making any remote requests."""
    status = inspection["before"]
    selection = status["activation"]
    empty = selection["good"] == NO_BANK
    # Do not accidentally use a recent receipt describing some other board selection.
    if current and (empty or current.get("banks", {}).get(str(selection["good"])) != selection["good_sha256"]
                    or current.get("firmware_sha256") != requested.get("firmware_sha256")):
        current = None
    baseline = "empty" if empty else "known" if current else "unknown"
    old, new = _services(current), _services(requested)
    changes, warnings = [], []
    if baseline == "unknown":
        warnings.append("Previous configuration unknown: no retained release matches the selected graph.")
    for name in sorted(old.keys() | new.keys()):
        path = ["services", name]
        if name not in old:
            changes.append(dict(path=path, action="select" if baseline == "unknown" else "add",
                                before=None, after=_semantic(new[name])))
        elif name not in new:
            changes.append(dict(path=path, action="remove", before=_semantic(old[name]), after=None))
        else:
            before, after = _semantic(old[name]), _semantic(new[name])
            if "settings" in before and "settings" in after:
                before.pop("configuration_hex", None)
                after.pop("configuration_hex", None)
            for key in sorted(before.keys() | after.keys()):
                if key not in before or key not in after:
                    # Missing descriptive metadata is not a deployment change.
                    warnings.append(f"{name}: {key} metadata unavailable for one release; comparison unknown.")
                else:
                    changes.extend(_diff([*path, key], before[key], after[key]))
    installed = inspection["unchanged"]
    action = ("deploy" if force or not installed else
              "none" if running(status, len(requested["services"])) else "restart")
    scope, affected, reason = restart_scope(status, old, new, force)
    before_resources, after_resources = resource_totals(current), resource_totals(requested)
    admission = inspection["plan"].get("resources", {})
    for key in after_resources:
        admission_key = "channel_bytes" if key == "channel_payload_bytes" else key
        if admission_key in admission:
            after_resources[key] = admission[admission_key]
    resources = {}
    for key, after in after_resources.items():
        before = 0 if empty else before_resources[key]
        resources[key] = dict(before=before, after=after,
                              delta=after - before if before is not None and after is not None else None)
    return dict(
        format=1, kind="deployment-plan", device=device,
        identity=status.get("identity"),
        baseline=dict(state=baseline, release=current.get("id") if current else None,
                      graph_sha256=selection["good_sha256"] if not empty else None),
        desired=dict(release=requested["id"], packages=requested["packages"],
                     base_sha256=requested["firmware_sha256"]),
        changes=changes, resources=resources, warnings=warnings,
        execution=dict(action=action, forced=force, base_update=False,
                       candidate_bank=inspection["candidate"] if action == "deploy" else None,
                       stops_current_graph=action == "deploy" and scope == "whole_application",
                       restart_scope=scope, restart_reason=reason,
                       stages_while_running=bool(status.get("selective_deploy")) and not force and action == "deploy",
                       affected_services=affected if action == "deploy" else sorted(old.keys() | new.keys()) if action != "none" else [],
                       current_service_names_known=baseline != "unknown",
                       flash_writes=action == "deploy",
                       health_check="runtime liveness; physical behavior requires separate verification"),
    )


def format_plan(plan):
    identity = plan.get("identity") or {}
    lines = [f'Deployment plan: {plan["device"] or identity.get("device_id", "selected board")}']
    if identity.get("device_id"):
        lines.append(f'Hardware: {identity["device_id"]}')
    lines.append(f'Baseline: {plan["baseline"]["state"]}')
    lines.append(f'Requested release: {plan["desired"]["release"]}')
    lines.extend("Warning: " + warning for warning in plan["warnings"])
    lines.append("")
    for change in plan["changes"]:
        path = ".".join(change["path"])
        action = change["action"]
        if len(change["path"]) == 2:
            suffix = " (previous configuration unknown)" if action == "select" else ""
            lines.append(f'{dict(add="+", remove="-", select="?")[action]} {path}: {action}{suffix}')
        else:
            lines.append(f'~ {path}: {json.dumps(change["before"], sort_keys=True)} → '
                         f'{json.dumps(change["after"], sort_keys=True)}')
    if not plan["changes"]:
        lines.append("No differences in comparable release metadata.")
    lines.append("\nResource reservations (not measured runtime heap):")
    for key, values in plan["resources"].items():
        before = "unknown" if values["before"] is None else str(values["before"])
        after = "unknown" if values["after"] is None else str(values["after"])
        delta = f' ({values["delta"]:+d})' if values["delta"] is not None else ""
        lines.append(f'  {key}: {before} → {after}{delta}')
    lines.append("  Channel payload bytes exclude runtime bookkeeping.")
    action = plan["execution"]["action"]
    lines.append("\nAction: " + {
        "none": "Already installed and running; no device changes or flash writes.",
        "restart": "Restart the installed application; no flash writes.",
        "deploy": "Deploy complete application graph; all current services pause during transfer, then the requested graph starts.",
    }[action])
    if action == "deploy" and plan["execution"].get("stages_while_running"):
        lines[-1] = "\nAction: Stage while current services run. " + plan["execution"]["restart_reason"]
        lines.append("Services to reload: " + (", ".join(plan["execution"]["affected_services"]) or "none"))
    lines.append("Base firmware unchanged.")
    return "\n".join(lines)
