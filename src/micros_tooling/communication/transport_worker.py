"""One stdlib HTTPS request for the optional Docker network transport.

Secrets arrive on stdin, never in process arguments or Docker environment variables.
"""

import base64
import http.client
import json
import ssl
import sys


def main():
    request = json.load(sys.stdin)
    context = ssl.create_default_context(cadata=request["certificate"])
    context.check_hostname = False
    connection = http.client.HTTPSConnection(
        request["host"], request["port"], context=context, timeout=20
    )
    try:
        connection.request(
            request["method"],
            request["path"],
            base64.b64decode(request["body"]),
            {
                "Authorization": "Bearer " + request["token"],
                "Content-Type": "application/octet-stream",
                **({"X-Micros-Session": request["session"]} if request.get("session") else {}),
            },
        )
        response = connection.getresponse()
        payload = response.read(
            16385
        )  # One byte beyond the management client's 16 KiB response limit.
        print(
            json.dumps(
                {"status": response.status, "body": base64.b64encode(payload).decode()}
            )
        )
    except (OSError, http.client.HTTPException) as error:
        print(json.dumps({"error": str(error)}))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
