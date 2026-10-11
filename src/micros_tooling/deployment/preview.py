"""Human-reviewable differences between immutable deployment receipts."""

import json
from pathlib import Path
from micros_tooling.storage.packages import read_package, image_metadata
from micros_tooling.config.configuration import config_artifacts


def details(packages, firmware=None):
    """Keep contract and setting descriptions with the exact packages they describe."""
    result = {}
    for path in packages:
        path = Path(path)
        package = read_package(path.read_bytes())
        manifest = package["manifest"]
        item = {key: manifest[key] for key in ("version", "image_sha256", "memory", "capabilities", "channels", "schemas")}
        if "board_bindings" in manifest: item["board_bindings"]=manifest["board_bindings"]
        item["slot"] = manifest.get("build_identity", {}).get("slot")
        item["configuration_hex"] = manifest.get("config", "")
        memory = image_metadata(package["image"])
        if manifest["target"] == 2 and firmware is not None:
            from micros_tooling.platforms.esp32.build_service import load_symbol_addresses
            symbols = load_symbol_addresses(Path(firmware))
            item["headroom"] = dict(code_bytes=symbols.get("micros_service_code_capacity",8192) - memory["code_bytes"],
                                    data_bytes=symbols.get("micros_service_data_capacity",4096) - memory["data_bytes"] - memory["bss_bytes"])
        receipt_path = path.parent / "receipt.json"
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text())
            saved = receipt.get("details", {}).get(manifest["name"], {})
            if package["sha256"] in receipt["packages"] and saved.get("configuration_hex") == item["configuration_hex"]:
                if "settings" in saved:
                    item["settings"] = saved["settings"]
        resolved = path.parent / "resolved.json"
        if resolved.exists():
            for service in json.loads(resolved.read_text())["services"]:
                config = service.get("_configuration")
                if service["name"] == manifest["name"] and config:
                    _, payload = config_artifacts(config["name"], config["definition"], config["values"])
                    if payload.hex() == item["configuration_hex"]:
                        item["settings"] = {key: config["values"].get(key, spec["default"])
                                            for key, spec in config["definition"]["fields"].items()}
        result[manifest["name"]] = item
    return result


def changes(current, requested):
    """Return explicit field changes; unknown old state is never treated as empty state."""
    old = (current or {}).get("details", {})
    new = requested.get("details", {})
    result = []
    if current and not old:
        result.append("Previous receipt has no detailed metadata; exact field diff unavailable.")
    for name in sorted(old.keys() | new.keys()):
        if name not in old:
            result.append(f"{name}: selected {new[name]['version']}" + (" (previous details unknown)" if current else ""))
            continue
        if name not in new:
            result.append(f"{name}: removed")
            continue
        for key in sorted(old[name].keys() | new[name].keys()):
            before, after = old[name].get(key), new[name].get(key)
            if before == after or key == "configuration_hex" and "settings" in old[name] and "settings" in new[name]:
                continue
            if key == "settings" and isinstance(before, dict) and isinstance(after, dict):
                for setting in sorted(before.keys() | after.keys()):
                    if before.get(setting) != after.get(setting):
                        result.append(f"{name}.{setting}: {before.get(setting)!r} → {after.get(setting)!r}")
            elif key == "image_sha256":
                result.append(f"{name}: linked executable changes")
            else:
                result.append(f"{name} {key}: {json.dumps(before, sort_keys=True)} → {json.dumps(after, sort_keys=True)}")
    return result
