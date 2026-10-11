# Hardware capability catalog

This directory contains reusable hardware metadata:

- `chips/`: supported chip capabilities and runtime restrictions.
- `boards/`: board/module metadata, exposed pins, and onboard connections.

Physical board identity, selected services, actual wiring, settings, and channels
belong in the consuming application repository's `units/<hardware-id>.toml`.
The SDK has no default application or operator deployment in `config/`.

Demonstration wiring belongs with its example under `examples/`. Anonymous
composition inputs and expected units live under `tests/fixtures/composition/`.
Private enrollment and recovery material remain in the ignored `.micros/` archive.
