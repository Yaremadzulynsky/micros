# Nanopb 0.4.9.1

C runtime vendored from https://github.com/nanopb/nanopb/tree/0.4.9.1.
See LICENSE.txt. The generator is pinned in tools/requirements-dev.txt.

Local adaptation: pb.h includes micros_config.h to enforce identical buffer-only,
no-error-string stream layouts everywhere, validate protobuf UTF-8 strings, and reject malloc-enabled builds.
The other upstream source files are unmodified. Generated message descriptors
live in each service's generated/ directory; they are not maintained here.
