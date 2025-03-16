import json
from twisted.internet import reactor, protocol, defer
from twisted.python import failure

from quarry.net.protocol import Factory, Protocol, ProtocolError, protocol_modes_inv
from quarry.net import auth, crypto


class ClientProtocol(Protocol):
    """This class represents a connection to a server"""

    recv_direction = "downstream"
    send_direction = "upstream"

    # Convenience functions ---------------------------------------------------

    def switch_protocol_mode(self, mode):
        self.check_protocol_mode_switch(mode)

        if mode in ("status", "login"):
            # Send handshake
            addr = self.transport.connector.getDestination()
            self.send_packet(
                "set_protocol",
                {
                    "protocolVersion": self.protocol_version,
                    "serverHost": addr.host,
                    "serverPort": addr.port,
                    "nextState": protocol_modes_inv[self.factory.protocol_mode_next],
                },
            )
            # Switch buff type

        self.switch_mode(mode)

        if mode == "status":
            # Send status request
            self.send_packet("ping_start")

        elif mode == "login":
            self.send_packet(
                "login_start",
                {
                    "username": self.factory.profile.display_name,
                    "playerUUID": self.factory.profile.uuid.to_hex(with_dashes=False),
                },
            )

    # Callbacks ---------------------------------------------------------------

    @defer.inlineCallbacks
    def connection_made(self):
        """Called when the connection is established"""
        super(ClientProtocol, self).connection_made()

        # Determine protocol version
        if self.factory.protocol_mode_next == "status":
            pass
        elif self.factory.force_protocol_version is not None:
            self.protocol_version = self.factory.force_protocol_version
        else:
            factory = PingClientFactory()
            factory.connect(self.remote_addr.host, self.remote_addr.port)
            self.protocol_version = yield factory.detected_protocol_version

        self.switch_protocol_mode(self.factory.protocol_mode_next)

    def auth_ok(self, data):
        """
        Called if the Mojang session server responds to our query. Note that
        this method does not indicate that the server accepted our session; in
        this case :meth:`player_joined` is called.
        """

        # Send encryption response
        p_shared_secret = crypto.encrypt_secret(self.public_key, self.shared_secret)
        p_verify_token = crypto.encrypt_secret(self.public_key, self.verify_token)

        self.send_packet("encryption_begin", {"sharedSecret": p_shared_secret, "verifyToken": p_verify_token})
        # Enable encryption
        self.cipher.enable(self.shared_secret)
        self.logger.debug("Encryption enabled")

    def player_joined(self):
        """
        Called when we join the game. If the server is in online mode, this
        means the server accepted our session.
        """
        Protocol.player_joined(self)
        self.logger.info("Joined the game.")

    def player_left(self):
        """Called when we leave the game."""
        Protocol.player_left(self)
        self.logger.info("Left the game.")

    def status_server_info(self, data):
        """
        If we're connecting in "status" mode, this is called when the server
        sends us information about itself.
        """
        self.close()

    # Packet handlers ---------------------------------------------------------

    def packet_server_info(self, data):
        self.status_server_info(json.loads(data["response"]))

    def packet_login_disconnect(self, data):
        self.logger.warn("Kicked: {reason}", reason=data["reason"])
        self.close()
    def packet_encryption_begin(self, data):
        if not self.factory.profile.online:
            raise ProtocolError(
                "Can't log into online-mode server while using offline profile"
            )

        self.shared_secret = crypto.make_shared_secret()
        self.public_key = crypto.import_public_key(data["publicKey"])
        self.verify_token = data["verifyToken"]

        # make digest
        digest = crypto.make_digest(
            data["serverId"].encode("ascii"), self.shared_secret, data["publicKey"]
        )

        # do auth
        deferred = self.factory.profile.join(digest)
        deferred.addCallbacks(self.auth_ok, self.auth_failed)

    def packet_success(self, data):
        self.send_packet("login_acknowledged")
        self.switch_protocol_mode("configuration")
        self.player_joined()

    def packet_compress(self, data):
        self.set_compression(data["threshold"])
    
    def packet_select_known_packs(self, data):
        self.send_packet("select_known_packs", data)
    
    def packet_finish_configuration(self, data):
        self.send_packet("finish_configuration")
        self.switch_protocol_mode("play")

    packet_disconnect = packet_login_disconnect


class SpawningClientProtocol(ClientProtocol):
    spawned = False

    def __init__(self, factory, remote_addr):
        # x, y, z, yaw, pitch
        self.pos_look = [0, 0, 0, 0, 0]

        super(SpawningClientProtocol, self).__init__(factory, remote_addr)

    def packet_keep_alive(self, data):
        self.send_packet("keep_alive", data)


class ClientFactory(Factory, protocol.ClientFactory):
    protocol = ClientProtocol
    protocol_mode_next = "login"

    def __init__(self, profile=None):
        if profile is None:
            profile = auth.OfflineProfile()
        self.profile = profile

    def connect(self, host, port=25565):
        reactor.connectTCP(host, port, self, self.connection_timeout)


class PingClientProtocol(ClientProtocol):
    def status_server_info(self, data):
        self.close()
        detected_version = int(data["version"]["protocol"])
        if detected_version in self.factory.minecraft_versions:
            self.factory.detected_protocol_version.callback(detected_version)
        else:
            message = "Unsupported protocol version (%d)" % detected_version
            if "description" in data:
                motd = data["description"]
                message = "%s: %s" % (message, motd)
            self.factory.detected_protocol_version.errback(
                failure.Failure(ProtocolError(message))
            )


class PingClientFactory(ClientFactory):
    protocol = PingClientProtocol
    protocol_mode_next = "status"

    def __init__(self, profile=None):
        super(PingClientFactory, self).__init__(profile)
        self.detected_protocol_version = defer.Deferred()
