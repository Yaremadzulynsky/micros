# Feather base OTA hardware validation — 2026-09-08

Device: ESP32-PICO-V3-02, MAC e8:9f:6d:30:e1:a8, 8 MiB flash.

Verified on hardware:
- Physical installation of the A/B partition layout and base A, with flash-write verification.
- Existing credentials and Wi-Fi retained; the board reconnected at 192.168.1.190.
- Network OTA A → B, explicit confirmation, and fresh status showing slot 1 confirmed.
- Base B ELF SHA-256: fd4273a34d0f0ed3b7ba20bc2b7a2e1a5b3e7ae5ade265376994998239b29ef2.
- Button, Colors and DHT rebuilt/deployed through the management server; all three Running with result 0.
- Offset, incomplete-upload and digest-mismatch rejections without changing the selected base.

A transient HTTP 503 controller-admission rejection interrupted the first transfer.
The host client now retries only explicit 503 rejection with bounded backoff; lost
responses and unknown outcomes remain non-replayable. Eight host client tests pass.
Direct HTTPS testing used a persistent Docker LAN bridge because macOS reported
no route to the device. Server-backed status, artifact publication and application
deployment worked. The running server did not yet include base-OTA relay routes;
base-image transfers were tested through direct HTTPS, not the relay.

The user stopped the full-flash backup; no full backup file was produced. The user
then needed to disconnect USB to charge the computer. The automatic rollback test
was interrupted during upload of the inactive slot, before requesting boot selection.
The installed, confirmed base B and its restored applications remain selected.
Automatic trial-timeout rollback and physical power-loss behavior are still unverified
on hardware and should be tested before unattended deployment.

Private evidence and build artifacts: `.micros/ota-validation/feather-20260908/`.
