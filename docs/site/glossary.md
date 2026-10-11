---
hide:
- toc
---

<span class="docs-editorial"></span>

Reference · Glossary
{: .arch-eyebrow}

# Glossary

| Term | Meaning in Micros |
| --- | --- |
| Service | Native application code with a lifecycle and declared requirements. |
| Service instance | One admitted execution of a service, with its worker, state, and owned resources. |
| Application / graph | The selected services, settings, resource grants, and channel bindings managed together. |
| Kernel | Shared runtime code that manages service lifecycle, resources, channels, and supervision. |
| Supervisor | The runtime task that independently checks whether active service work has exceeded its deadline. |
| Resident base | The kernel, target integration, and enabled management facilities installed on a device. |
| ABI | The binary contract used by independently compiled service and kernel code. |
| Platform interface / HAL | Operations implemented by a target adapter beneath the shared kernel. |
| Arena | Per-instance memory retained between lifecycle hooks and callbacks. |
| Handle | A checked reference to an opened, owned resource such as a timer or channel endpoint. |
| Publication / subscription | A service's declared write/read access to a channel. |
| Channel | Bounded typed-message storage with a declared interface and retention policy. |
| Coordination | State, action, and event semantics with explicit endpoint routing and lifetime rules. |
| Composition | Offline resolution of deployment, board, application, and service definitions into reviewed inputs. |
| Unit recipe | Complete hardware and application input for one device; authored directly or emitted by composition. |
| Candidate | An application or base selection undergoing its relevant trial checks. |
| Good selection | A confirmed application recorded for activation and recovery. |
| Liveness | Evidence that services are running and making progress; application correctness needs its own checks. |
| Release | Retained application packages and metadata that can be reviewed and, when compatible, redeployed. |

See [Architecture](architecture.md) for the system overview.
