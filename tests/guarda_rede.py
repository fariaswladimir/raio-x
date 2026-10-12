"""EAP 11.2: guarda de rede. Faz qualquer conexão para fora desta máquina falhar (e ser registrada).

Libera só endereços de loopback (127.0.0.0/8, ::1, localhost) e sockets locais (AF_UNIX). Usada pelos testes
(fixture ``sem_rede``) e por ``scripts/verificar_offline.py``. Bloqueia também a resolução de nomes (DNS) de hosts externos.
"""
import ipaddress
import socket

_LOCAIS = {"localhost", "localhost.localdomain", "ip6-localhost", ""}


class RedeBloqueada(OSError):
    """Tentativa de acesso à rede com a guarda ligada."""


def host_local(host) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    host = str(host).strip().strip("[]").lower()
    if host in _LOCAIS:
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _endereco_local(address) -> bool:
    if isinstance(address, (str, bytes)):  # AF_UNIX
        return True
    if isinstance(address, tuple) and address:
        return host_local(address[0])
    return False


class GuardaRede:
    """Liga/desliga o bloqueio. ``tentativas`` guarda cada acesso externo barrado."""

    def __init__(self):
        self.tentativas: list[str] = []
        self._originais: dict = {}

    def _barrar(self, destino) -> None:
        self.tentativas.append(str(destino))
        raise RedeBloqueada(f"Acesso à rede bloqueado pela guarda do modo offline: {destino}")

    def ligar(self) -> "GuardaRede":
        guarda = self
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        original_getaddrinfo = socket.getaddrinfo

        def connect(self_, address):
            if not _endereco_local(address):
                guarda._barrar(address)
            return original_connect(self_, address)

        def connect_ex(self_, address):
            if not _endereco_local(address):
                guarda._barrar(address)
            return original_connect_ex(self_, address)

        def getaddrinfo(host, *args, **kwargs):
            if not host_local(host):
                guarda._barrar(host)
            return original_getaddrinfo(host, *args, **kwargs)

        self._originais = {"connect": original_connect, "connect_ex": original_connect_ex, "getaddrinfo": original_getaddrinfo}
        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex
        socket.getaddrinfo = getaddrinfo
        return self

    def desligar(self) -> None:
        if self._originais:
            socket.socket.connect = self._originais["connect"]
            socket.socket.connect_ex = self._originais["connect_ex"]
            socket.getaddrinfo = self._originais["getaddrinfo"]
            self._originais = {}

    def __enter__(self):
        return self.ligar()

    def __exit__(self, *exc):
        self.desligar()
