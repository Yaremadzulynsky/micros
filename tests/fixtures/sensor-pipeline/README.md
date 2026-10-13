# Sensor pipeline

Three independent native images implement a 10 Hz synthetic publisher and fast/slow protobuf loggers. The depth-eight, 64-byte stream is configured by the host demo. The slow logger pauses for 1.2 seconds, explicitly reports lost samples, then resumes. Each subscriber owns its cursor; service data moves only through protobuf IPC.

Run `build/host/micros-pipeline build/host` after the standard build. The shared schema is in [src/sdk/protos/button/v1](../../../src/sdk/protos/button/v1/button_state.proto); the bounded scalar codec is under `src/sdk/c`. The application button and logger have dedicated implementations under `examples/services/`; this fixture retains the synthetic and slow-reader test roles.
