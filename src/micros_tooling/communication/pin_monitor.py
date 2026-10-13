"""Print timestamped pin readings as CSV through a deployed network bridge."""
import argparse
import csv
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from micros_tooling.communication.channels import Channels, ChannelMissed, ROOT
from micros_tooling.fleet.server import configured_remote
from micros_tooling.storage.workspace import Workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--port", default="samples")
    args = parser.parse_args()
    remote = configured_remote(Workspace(Path(os.environ.get("MICROS_STATE_DIR", ROOT / ".micros"))), args.device)
    if remote is None:
        parser.error("No configured micros server")
    channels = Channels(remote, args.project)
    port = channels._port(args.port, "subscribe")
    schema = ROOT / "src/sdk/protos/pin/v1/pin_sample.proto"
    if Path(port["schema"]).read_bytes() != schema.read_bytes():
        parser.error("Selected port must use pin_sample.proto")
    # Generate the Python decoder from the same contract as the MCU bindings.
    with tempfile.TemporaryDirectory() as directory:
        subprocess.run([sys.executable, "-m", "grpc_tools.protoc", "-I" + str(schema.parent),
                        "--python_out=" + directory, str(schema)], check=True)
        spec = importlib.util.spec_from_file_location("micros_pin_sample", Path(directory) / "pin_sample_pb2.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        writer = csv.writer(sys.stdout)
        writer.writerow(["publisher_started_us", "sequence", "monotonic_us", "pin", "analog", "value", "error"])
        try:
            while True:
                try:
                    payload = channels.read(args.port)
                except ChannelMissed as error:
                    print(error, file=sys.stderr)
                    continue
                if payload is None:
                    time.sleep(0.1)
                    continue
                sample = module.PinSample.FromString(payload)
                writer.writerow([sample.publisher_started_us, sample.sequence, sample.monotonic_us,
                                 sample.pin, int(sample.analog), sample.value, sample.error])
                sys.stdout.flush()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
