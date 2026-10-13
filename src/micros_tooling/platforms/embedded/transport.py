"""Shared bounded command and durable deployment protocol."""

import json, time, secrets, re
from micros_tooling.storage.packages import PackageError, require
from micros_tooling.platforms.embedded.telemetry import expand


class SerialResponseError(PackageError):
    """A damaged reply is not evidence that a preceding write failed."""

    code = "invalid_serial_reply"
    outcome = "unknown"


def verify_selected_usb(remote, device_id):
    """Do not let an explicit port override the selected physical identity."""
    if device_id:
        try:
            require(remote.status().get('identity', {}).get('device_id') == device_id,
                    'This USB controller does not match the selected device. Check --device and --port; no write was sent.')
        except BaseException:
            remote.serial.close()
            raise
    return remote


class EmbeddedRemote:
    write_chunk = 192
    platform = ""
    target = 0
    bank_sizes = ()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.serial.close()

    def _exchange(self, command, allow_error=False):
        require(
            "\n" not in command and "\r" not in command and len(command) < 600,
            "Invalid serial command",
        )
        self.serial.write(command.encode("ascii") + b"\n")
        started = time.monotonic()
        deadline = started + (
            45 if command.startswith(("RPC 13 ", "RPC 15 ", "RPC 19 ", "RPC 22 ")) else 8
        )
        response = bytearray()
        while time.monotonic() < deadline:
            response += self.serial.read_until(b"\n", 8192 - len(response))
            require(len(response) < 8192, "Oversized device response")
            if response.endswith(b"\n"):
                response = bytearray(re.sub(rb"\x1b\[[0-9;]*m", b"", response))
                if not response.startswith(b"{"):
                    response.clear()
                    continue  # Boot-ROM diagnostics cannot be command replies.
                try:
                    decoded = json.loads(response)
                except (json.JSONDecodeError, UnicodeError):
                    # Never include raw bytes: replies can echo private settings.
                    raise SerialResponseError(
                        "The USB reply was incomplete or damaged. Inspect device status "
                        "before repeating a write; its outcome is not confirmed."
                    ) from None
                result = expand(decoded, serial=True)
                require(
                    isinstance(result, dict) and "result" in result, "Invalid device response"
                )
                if result.get("result") == -7 and result.get("error") == "management_reply_busy":
                    # The controller rejected this request before executing it.
                    # A relay may retain the reserved reply while TLS connects.
                    # Keep waiting bounded, without replaying an ambiguous write.
                    deadline = max(deadline, started + 45)
                    response.clear()
                    time.sleep(.05)
                    if time.monotonic() < deadline:
                        self.serial.write(command.encode("ascii") + b"\n")
                    continue
                require(allow_error or result["result"] == 0, f"{command.split()[0]}: {result}")
                return result
        raise TimeoutError(
            "Device did not respond; reconnect and inspect status before retrying a write"
        )

    def rpc(self, operation, *, bank=0, slot=0, cursor=0, body=b'', allow_error=False):
        require(len(body) <= 256, 'RPC fragment exceeds transport capacity')
        session = self.session if getattr(self, '_session_open', False) else '-'
        return self._exchange(f'RPC {operation} {bank} {slot} {cursor} {session} {body.hex() or "-"}', allow_error)

    def status(self):
        for attempt in range(3):
            try:
                value = self.rpc(0)
                break
            except SerialResponseError:
                if attempt == 2:
                    raise PackageError('Could not read a valid USB status reply after three attempts; inspect the connection before continuing.') from None
                self.serial.reset_input_buffer()
                time.sleep(.1)
        require(value.get('platform') == self.platform and value.get('target') == self.target,
                'Unexpected device platform')
        selection = value['activation']
        value.update(selection)
        value['base_sha256'] = value['identity']['base_sha256']
        value['active'] = value.get('active', selection['candidate'] if selection['pending'] else selection['good'])
        return value

    def begin_session(self):
        import struct
        if getattr(self, '_session_open', False):
            return
        status = self.status()
        self._session_open = True
        try:
            self.rpc(8, body=bytes.fromhex(status['good_sha256']) + struct.pack('<I', status['sequence']))
        except BaseException:
            self._session_open = False
            raise

    def end_session(self):
        if getattr(self, '_session_open', False):
            self.rpc(9)
            self._session_open = False

    def request(self, command, allow_error=False):
        """Convenience operations over the same controller RPC used by all targets."""
        import struct
        fields = command.split()
        require(fields, 'Empty command')
        operation = fields[0]
        if operation == 'STATUS': return self.status()
        if operation == 'LOGS': return self.rpc(1, allow_error=allow_error)
        if operation in ('WIFI', 'WIFI_GET'): return self.rpc(11, allow_error=allow_error)
        if operation in ('COORD', 'IPC', 'SERVICE'):
            return self.rpc(18, body=command.encode(), allow_error=allow_error)
        self.begin_session()
        if operation == 'STOP': result = self.rpc(10, allow_error=allow_error)
        elif operation == 'REBOOT': result = self.rpc(6, allow_error=allow_error)
        elif operation == 'ABORT':
            result = self.rpc(17, allow_error=allow_error)
        elif operation == 'BASE_BEGIN':
            require(len(fields) == 4, 'Invalid base update request')
            result = self.rpc(13, body=b'MBO1' + struct.pack('<I', int(fields[2])) + bytes.fromhex(fields[3]), allow_error=allow_error)
        elif operation == 'BASE_WRITE':
            result = self.rpc(14, cursor=int(fields[1]), body=bytes.fromhex(fields[2]), allow_error=allow_error)
        elif operation == 'BASE_ACTIVATE': result = self.rpc(15, allow_error=allow_error)
        elif operation == 'BASE_FETCH': result = self.rpc(25, body=bytes.fromhex(fields[1]), allow_error=allow_error)
        elif operation == 'BASE_ROLLBACK': result = self.rpc(27, allow_error=allow_error)
        elif operation == 'BOOTLOADER': result = self.rpc(28, allow_error=allow_error)
        elif operation == 'ROLLBACK': result = self.rpc(29, allow_error=allow_error)
        elif operation == 'RELAY_SET': result = self.rpc(26, body=' '.join(fields[1:]).encode('ascii'), allow_error=allow_error)
        elif operation in ('WIFI_SET', 'WIFI_PROFILES'):
            expected = 3 if operation == 'WIFI_SET' else 5
            require(len(fields) == expected, 'Invalid network settings')
            records = []
            for index in range(1, len(fields), 2):
                name = bytes.fromhex(fields[index]) if fields[index] != '-' else b''
                keep = fields[index + 1] == 'keep'
                password = bytes.fromhex(fields[index + 1]) if fields[index + 1] not in ('-', 'keep') else b''
                require(len(name) <= 32 and len(password) <= 64 and b'\0' not in name + password, 'Invalid network settings')
                mode = (1 if keep else 2) if name else 0
                records.append(struct.pack('4B', len(name), len(password), mode, 0) + name.ljust(32, b'\0') + password.ljust(64, b'\0'))
            result = self.rpc(12, body=b'MWF1' + b''.join(records).ljust(200, b'\0'), allow_error=allow_error)
        elif operation == 'RECOVER':
            selected = self.status()
            result = self.rpc(4, bank=selected['good'], body=bytes.fromhex(selected['good_sha256']), allow_error=allow_error)
        else:
            raise PackageError(f'Unsupported controller operation: {operation}')
        if operation in ('STOP', 'ABORT', 'RECOVER', 'ROLLBACK', 'WIFI_SET', 'WIFI_PROFILES', 'RELAY_SET'): self.end_session()
        return result

    def upload_record(self, bank, slot, data, graph=False):
        import struct
        operation = 22 if graph else 19
        self.rpc(operation, bank=bank, slot=slot, body=struct.pack('<I', len(data)))
        for offset in range(0, len(data), self.write_chunk):
            self.rpc(operation + 1, bank=bank, slot=slot, cursor=offset, body=data[offset:offset + self.write_chunk])
        self.rpc(operation + 2, bank=bank, slot=slot)

    def deploy(self, data, report):
        import struct
        from micros_tooling.storage.deployment import GRAPH_BYTES, GRAPH_MAGIC, GRAPH_VERSION
        require(len(data) == report['bank_bytes'] and report['bank'] in (0, 1), 'Invalid deployment image set')
        graph = data[:GRAPH_BYTES]
        magic, version, bank, count = struct.unpack_from('<4I', graph)
        require((magic, version, bank) == (GRAPH_MAGIC, GRAPH_VERSION, report['bank']) and 0 < count <= 4,
                'Unsupported deployment format; rebuild the application for this base')
        status = self.status()
        require(status['base_sha256'] == report['base_sha256'], 'Base changed; rebuild before deploying')
        require(bank != status['good'] and not status['pending'], 'Image set is no longer inactive; rebuild')
        self.begin_session()
        try:
            self.rpc(5)
            for index in range(count):
                slot = struct.unpack_from('<I', graph, 84 + index * 36)[0]
                require(slot < 4, 'Invalid image slot')
                start = 4096 + slot * report['slot_bytes']
                header = struct.unpack_from('<16I', data, start)
                size = 64 + header[7] + header[8]
                require(64 <= size <= report['slot_bytes'] and start + size <= len(data), 'Invalid native image length')
                self.upload_record(bank, slot, data[start:start + size])
            self.upload_record(bank, 0, graph, graph=True)
            self.rpc(4, bank=bank, body=bytes.fromhex(report['graph_sha256']))
        except BaseException:
            # Never retry writes after an uncertain response. The controller lease
            # restores the confirmed application if this client disappears.
            raise
        self.end_session()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = self.status()
            if not result['pending']:
                require(result['good'] == bank and result['good_sha256'] == report['graph_sha256'],
                        'Candidate failed; inspect the retained application')
                return result
            time.sleep(.1)
        raise TimeoutError('Activation has not confirmed; inspect status')


class NetworkRemote(EmbeddedRemote):
    """Use the same bounded platform protocol through the authenticated relay."""

    write_chunk = 192

    def __init__(self, relay):
        self.relay = relay
        self.session = secrets.token_hex(16)
        self.serial_number = None

    def __exit__(self, *_):
        pass

    def _exchange(self, command, allow_error=False):
        require(
            "\n" not in command and "\r" not in command and len(command) < 600,
            "Invalid command",
        )
        result = self.relay.request(
            "POST", "/v1/platform-command", command.encode("ascii")
        )
        result = expand(result)
        require(isinstance(result, dict) and "result" in result, "Invalid device response")
        require(allow_error or result["result"] == 0, f"{command.split()[0]}: {result}")
        return result
