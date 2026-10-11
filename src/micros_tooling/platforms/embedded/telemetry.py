"""Expand the versioned MKR wire report into the common management schema."""

SERVICE_FIELDS = (
    "name version state result steps callbacks arena_reserved stack_reserved "
    "stack_free_bytes handles_limit handles_open timers_limit timers_open "
    "gpio_granted gpio_open publish_mask subscribe_mask hook_max_us "
    "callback_max_us timer_late_max_us image_bytes"
).split()
CHANNEL_FIELDS = (
    "key policy depth payload_bytes publishers subscribers backlog published "
    "missed age_us retained_bytes"
).split()
STATES = (
    "Unloaded",
    "Loaded",
    "Initializing",
    "Starting",
    "Running",
    "Stopping",
    "Stopped",
    "Failed",
)


def tables(status, serial=False):
    status = dict(status)
    status.pop("samd_telemetry", None)
    status.pop("embedded_telemetry", None)
    rows = status.pop("service_rows")
    channels = status.pop("channel_rows")
    pins = status.pop("gpio_rows")
    if len(rows) > 4 or len(channels) > 4 or len(pins) > 4:
        raise ValueError("Invalid embedded telemetry table")

    def unpack(fields, row):
        if len(fields) != len(row):
            raise ValueError("Invalid embedded telemetry row")
        return dict(zip(fields, row))

    status["activation"] = dict(
        good=status.get("good"),
        previous=status.get("previous"),
        candidate=status.get(
            "candidate", status.get("active") if status.get("pending") else 0xFFFFFFFF
        ),
        attempts=status.get("attempts", 0),
        pending=status.get("pending", 0),
        sequence=status.get("sequence", 0),
        good_sha256=status.get("good_sha256"),
    )
    status["services"] = [unpack(SERVICE_FIELDS, row) for row in rows]
    for s in status["services"]:
        s["arena_pool"] = "RAM"
        s["stack_free"] = s["stack_free_bytes"]
        s["handles"] = s["handles_open"]
        if not serial:
            s["state"] = STATES[s["state"]] if 0 <= s["state"] < len(STATES) else "Unknown"
    status["channels"] = [unpack(CHANNEL_FIELDS, row) for row in channels]
    status["labels_source"] = "device_graph"
    return status


def expand(status, serial=False):
    if not isinstance(status, dict):
        return status
    if status.get("platform") == "samd21":
        from micros_tooling.platforms.samd21.telemetry import expand as samd_expand

        return samd_expand(status, serial=serial)
    if status.get("platform") != "esp8266" or status.get("embedded_telemetry") != 1:
        return status
    pins = status["gpio_rows"]
    result = tables(status, serial)
    result["reset_reason"] = result.get("reset_cause")
    result["board"] = dict(
        profile="ESP8266 4 MiB",
        flash_mb=4,
        recovery_pin=None,
        gpio=[
            dict(name="GPIO" + str(pin), line=i, pin=pin, output=bool(output), level=level)
            for i, (pin, output, level) in enumerate(pins)
        ],
    )
    active = result.get("active", 0xFFFFFFFF)
    base_slot = result.get("base_ota", {}).get("slot", 0)
    parts = [
        dict(name="ROM loader / bootloader", offset=0, size=32768),
        dict(name="Partition table", offset=32768, size=4096),
        dict(name="nvs", offset=36864, size=16384),
        dict(name="otadata", offset=53248, size=8192),
        dict(name="phy_init", offset=61440, size=4096),
    ]
    slots = []
    for window in (0, 1):
        if window:
            parts.append(dict(name="Base boot journal", offset=1048576, size=8192))
            parts.append(
                dict(name="Unallocated flash", offset=1056768, size=57344, unknown=True)
            )
        parts.append(
            dict(name="ota_" + str(window), offset=window * 1048576 + 65536, size=720896)
        )
        for bank in (0, 1):
            offset = window * 1048576 + 786432 + bank * 131072
            if window != base_slot or bank != active:
                parts.append(
                    dict(
                        name="Alternate service bank",
                        offset=offset,
                        size=131072,
                        reservedCapacity=True,
                        note="Reserved service deployment and rollback capacity.",
                    )
                )
                continue
            parts.append(dict(name="Active graph reservation", offset=offset, size=4096))
            for i in range(4):
                region = dict(offset=offset + 4096 + i * 31744, size=31744)
                if i < len(result["services"]):
                    service = result["services"][i]
                    slot = dict(
                        slot=i,
                        name=service["name"],
                        offset=4096 + i * 31744,
                        reserved_bytes=31744,
                        image_bytes=service["image_bytes"],
                    )
                    slots.append(slot)
                    region.update(name=service["name"], image=slot)
                else:
                    region.update(name="Unused service slot " + str(i), reservedCapacity=True)
                parts.append(region)
    parts.append(dict(name="Unallocated flash", offset=2097152, size=2097152, unknown=True))
    result["flash"] = dict(
        total_bytes=4194304, partitions=parts, services=dict(slot_bytes=31744, slots=slots)
    )
    return result
