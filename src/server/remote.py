"""Registry-backed device transport using the shared device protocol and lease."""

from micros_tooling.communication.remote import Remote, accepted, decode_response

ROUTES = {('GET', '/v1/status'): 0, ('GET', '/v1/logs'): 1,
          ('PUT', '/v1/image'): 2, ('PUT', '/v1/graph'): 3,
          ('POST', '/v1/activate'): 4, ('POST', '/v1/stop'): 5,
          ('POST', '/v1/reboot'): 6, ('GET', '/v1/log-stream'): 7,
          ('POST', '/v1/session'): 8, ('DELETE', '/v1/session'): 9,
          ('POST', '/v1/pause'): 10, ('GET', '/v1/wifi'): 11, ('PUT', '/v1/wifi'): 12,
          ('POST', '/v1/base-begin'): 13, ('PUT', '/v1/base-chunk'): 14,
          ('POST', '/v1/base-finish'): 15, ('POST', '/v1/base-confirm'): 16,
          ('POST', '/v1/base-abort'): 17, ('POST', '/v1/platform-command'): 18}


class RegistryRemote(Remote):
    """Use the same validation and device-owned lease as the CLI transport."""
    def raw(self, method, path, body=b''):
        from server.artifacts import Artifacts
        from micros_tooling.storage.packages import require
        require(path.startswith('/v1/artifacts/'), 'Unsupported registry artifact route')
        code, reply = Artifacts(self.registry).handle(method, path, body)
        accepted(code, reply)
        return reply

    def __init__(self, registry, device):
        self.registry,self.device_id,self.session_id=registry,device,''
    def request(self,method,path,body=b'',token=None):
        from urllib.parse import urlsplit,parse_qs
        route=urlsplit(path); query=parse_qs(route.query) if route.query else {}
        code,response=self.registry.command(self.device_id,ROUTES[(method,route.path)],
            int(query.get('bank',['0'])[0]),int(query.get('slot',['0'])[0]),int(query.get('cursor',['0'])[0]),self.session_id,body)
        accepted(code,response)
        return response.decode(errors='replace') if route.path=='/v1/logs' else decode_response(response)
