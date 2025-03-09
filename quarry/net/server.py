import base64
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.hashes import SHA256
from twisted.internet import reactor, defer

from quarry.net.auth import PlayerPublicKey
from quarry.net.crypto import verify_mojang_v1_signature, verify_mojang_v2_signature
from quarry.net.protocol import Factory, Protocol, ProtocolError, protocol_modes
from quarry.net import auth, crypto
from quarry.types.uuid import UUID
from quarry.types.chat import Message


class ServerProtocol(Protocol):
    """This class represents a connection with a client"""

    recv_direction = "upstream"
    send_direction = "downstream"

    uuid = None
    display_name = None
    display_name_confirmed = False
    public_key_data: PlayerPublicKey = None

    # the hostname/port that the client claims it connected to. Useful for
    # implementing virtual hosting.
    connect_host = None
    connect_port = None

    # used to stop people breaking the login process
    # by sending packets out-of-order or duplicated
    login_expecting = 0

    # the mojang 1.7.x client has a race condition where kicking immediately
    # after switching to "play" mode will cause a cast error in the client.
    # the fix is to set a deferred up which will fire when it's safe again
    safe_kick = None

    def __init__(self, factory, remote_addr):
        Protocol.__init__(self, factory, remote_addr)
        self.server_id = crypto.make_server_id()
        self.verify_token = crypto.make_verify_token()

    # Convenience functions ---------------------------------------------------

    def switch_protocol_mode(self, mode):
        self.check_protocol_mode_switch(mode)
        self.protocol_mode = mode

    def close(self, reason=None):
        """Closes the connection"""
        if not self.closed and reason is not None:
            # Kick the player if possible.
            if self.protocol_mode == "play":

                def real_kick(*a):
                    self.send_packet("disconnect", {"reason": Message.from_string(reason).to_string()})
                    super(ServerProtocol, self).close(reason)

                if self.safe_kick:
                    self.safe_kick.addCallback(real_kick)
                else:
                    real_kick()
            else:
                if self.protocol_mode == "login":
                    self.send_packet(
                        "disconnect", {"reason": reason}
                    )
                Protocol.close(self, reason)
        else:
            Protocol.close(self, reason)

    # Callbacks ---------------------------------------------------------------

    def connection_lost(self, reason=None):
        """Called when the connection is lost"""
        if self.protocol_mode in ("login", "play"):
            self.factory.players.discard(self)
        Protocol.connection_lost(self, reason)

    def auth_ok(self, data):
        """Called when auth with mojang succeeded (online mode only)"""
        self.display_name_confirmed = True
        self.uuid = UUID.from_hex(data["id"])

        self.player_joined()

    def player_joined(self):
        """Called when the player joins the game"""
        Protocol.player_joined(self)

        self.logger.info("%s has joined." % self.display_name)

    def player_left(self):
        """Called when the player leaves the game"""
        Protocol.player_left(self)

        self.logger.info("%s has left." % self.display_name)

    # Packet handlers ---------------------------------------------------------

    def packet_set_protocol(self, data):
        mode = protocol_modes.get(data["nextState"])
        self.switch_protocol_mode(mode)

        if mode == "login":
            if self.factory.force_protocol_version is not None:
                if data["protocolVersion"] != self.factory.force_protocol_version:
                    self.close("Wrong protocol version")
            else:
                if data["protocolVersion"] not in self.factory.minecraft_versions:
                    self.close("Unknown protocol version")

            if len(self.factory.players) >= self.factory.max_players:
                self.close("Server is full")
            else:
                self.factory.players.add(self)

        self.load_protocol(self.protocol_version)
        self.connect_host = data["serverHost"]
        self.connect_port = data["serverPort"]

    def packet_login_start(self, data):
        if self.login_expecting != 0:
            raise ProtocolError("Out-of-order login")
        self.display_name = data["username"]

        # ill add online shit later i cant be bothered ngl
        self.login_expecting = None
        self.display_name_confirmed = True
        self.uuid = UUID.from_offline_player(self.display_name)
        self.send_packet("success", {"username": self.display_name, "uuid": self.uuid, "properties": []})


    def packet_login_acknowledged(self, data):
        self.switch_mode("configuration")
        self.player_joined()
    
    def packet_finish_configuration(self, data):
        self.send_packet("finish_configuration")
        self.switch_mode("play")

    def packet_login_encryption_response(self, buff):
        if self.login_expecting != 1:
            raise ProtocolError("Out-of-order login")

        # 1.7.x
        if self.protocol_version <= 5:
            unpack_array = lambda b: b.read(b.unpack("h"))
        # 1.8.x
        else:
            unpack_array = lambda b: b.read(b.unpack_varint(max_bits=16))

        p_shared_secret = unpack_array(buff)
        salt = None

        # 1.19 can now sign the verify token + a salt with the players public key, rather than encrypting the token
        if self.protocol_version >= 759:
            if buff.unpack("?") is False:
                salt = buff.unpack("Q").to_bytes(8, "big")

        p_verify_token = unpack_array(buff)

        shared_secret = crypto.decrypt_secret(self.factory.keypair, p_shared_secret)

        if salt is not None:
            try:
                self.public_key_data.key.verify(
                    p_verify_token, self.verify_token + salt, PKCS1v15(), SHA256()
                )
            except InvalidSignature:
                raise ProtocolError("Verify token incorrect")
        else:
            verify_token = crypto.decrypt_secret(self.factory.keypair, p_verify_token)

            if verify_token != self.verify_token:
                raise ProtocolError("Verify token incorrect")

        self.login_expecting = None

        # enable encryption
        self.cipher.enable(shared_secret)
        self.logger.debug("Encryption enabled")

        # make digest
        digest = crypto.make_digest(
            self.server_id.encode("ascii"), shared_secret, self.factory.public_key
        )

        # do auth
        remote_host = None
        if self.factory.prevent_proxy_connections:
            remote_host = self.remote_addr.host
        deferred = auth.has_joined(
            self.factory.auth_timeout, digest, self.display_name, remote_host
        )
        deferred.addCallbacks(self.auth_ok, self.auth_failed)

    def packet_ping_start(self, data):
        protocol_version = self.factory.force_protocol_version
        if protocol_version is None:
            protocol_version = self.protocol_version

        d = {
            "description": Message.from_string(self.factory.motd).value,
            "players": {
                "online": len(self.factory.players),
                "max": self.factory.max_players,
            },
            "version": {"name": self.version_name, "protocol": protocol_version},
        }
        if self.factory.icon is not None:
            d["favicon"] = self.factory.icon()

        # send status response
        self.send_packet("server_info", {"response": json.dumps(d)})

    def packet_ping(self, data):
        # send ping
        self.send_packet("ping", {"time": data["time"]})
        self.close()


class ServerFactory(Factory):
    protocol = ServerProtocol

    motd = "A Minecraft Server"
    max_players = 20
    icon_path = None
    online_mode = True
    enforce_secure_profile = False
    prevent_proxy_connections = True
    compression_threshold = 256
    auth_timeout = 30
    players = None

    def __init__(self):
        self.players = set()

        self.keypair = crypto.make_keypair()
        self.public_key = crypto.export_public_key(self.keypair)

    def listen(self, host, port=25565):
        reactor.listenTCP(port, self, interface=host)

    def icon(self):
        if self.icon_path is not None:
            with open(self.icon_path, "rb") as fd:
                return "data:image/png;base64," + base64.encodebytes(fd.read()).decode(
                    "ascii"
                ).replace("\n", "")
