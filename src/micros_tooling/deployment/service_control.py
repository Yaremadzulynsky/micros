"""Restart one live service without changing the installed application."""
from micros_tooling.storage.packages import require


def restart_service(remote, index):
    status = remote.status()
    require(status.get("service_restart") == 1,
            "This base does not support individual service restart; update the base first.")
    services = status["services"]
    require(type(index) is int and 0 <= index < len(services),
            "Select a zero-based service index from micros status.")
    selection = status["activation"]
    require(not selection["pending"] and selection["good"] in (0, 1)
            and not status.get("physical_recovery") and not status.get("deployment_session"),
            "Service restart requires an idle, confirmed application.")
    instance = services[index].get("instance", "")
    require(isinstance(instance, str) and instance.isascii() and instance.isdecimal(),
            "The base did not return a service instance identity.")
    boot = status.get("service_boot", "")
    require(isinstance(boot, str) and boot.isascii() and boot.isdecimal(),
            "The base did not return a restart boot identity.")
    command = (f'SERVICE RESTART {index} {selection["sequence"]} '
               f'{selection["good_sha256"]} {instance} {boot}')
    # No deployment lease: this command neither stages nor activates a graph.
    # Never retry a dispatched restart after an uncertain transport outcome.
    result = remote.request("POST", "/v1/platform-command", command.encode("ascii"))
    require(result.get("service_index") == index and result.get("result") == 0,
            "Service restart was not acknowledged; inspect status and logs before retrying.")
    observed = remote.status()
    require(observed.get("service_boot") == boot and observed["activation"] == selection and len(observed["services"]) == len(services),
            "Application changed during restart; inspect status.")
    restarted = observed["services"][index]
    require(restarted["state"] == "Running" and restarted["result"] == 0
            and restarted.get("instance") != instance,
            "Service restart is not confirmed; inspect status and logs.")
    require(all(peer.get("instance") == observed["services"][i].get("instance")
                for i, peer in enumerate(services) if i != index),
            "A peer instance changed during restart; inspect status.")
    return dict(service_index=index, status=observed)
