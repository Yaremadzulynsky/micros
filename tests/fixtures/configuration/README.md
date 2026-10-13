# Configuration fixture

This four-service application and board map are test inputs, independent of the
root application's enabled services, tunables and local server URL. Keep changes
here intentional when changing the SDK contract. CMake uses it to generate every
service interface needed by host tests, including disabled application services.
