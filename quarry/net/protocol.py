import sys
import zlib
from twisted.internet import protocol
from twisted import logger as log
from twisted.internet import defer
import quarry
import quarry.types
from quarry.data import LATEST_PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS
from quarry.types.buffer import Buffer, BufferUnderrun
from quarry.net.crypto import Cipher
from quarry.net.ticker import Ticker


protocol_modes = {0: "init", 1: "status", 2: "login", 3: "play"}
protocol_modes_inv = dict(((v, k) for k, v in protocol_modes.items()))


class ProtocolError(Exception):
    pass


class PacketDispatcher(object):
    def dispatch(self, lookup_args, buff):
        handler = getattr(self, f"packet_{'_'.join(lookup_args)}", None)
        if handler is not None:
            handler(buff)
            return True
        return False


class Protocol(protocol.Protocol, PacketDispatcher, object):
    """Shared logic between the client and server"""

    #: Usually a reference to a :class:`~quarry.types.buffer.Buffer` class.
    #: This is useful when constructing a packet payload for use in
    #: :meth:`send_packet`

    #: The logger for this protocol.
    logger = None

    #: A reference to a :class:`~quarry.net.ticker.Ticker` instance.
    ticker = None

    #: A reference to the factory
    factory = None

    #: The IP address of the remote.
    remote_addr = None

    recv_direction = None
    recv_buff = Buffer()
    send_direction = None
    protocol_version = LATEST_PROTOCOL_VERSION
    protocol_mode = "handshaking"
    compression_threshold = -1
    in_game = False
    closed = False

    def __init__(self, factory, remote_addr):
        self.factory = factory
        self.remote_addr = remote_addr

        self.cipher = Cipher()

        self.logger = log.Logger()

        # this is just the code to set the log level
        log_level_predicate = log.LogLevelFilterPredicate(
            defaultLogLevel=self.factory.log_level
        )
        observer = log.FilteringLogObserver(
            log.textFileLogObserver(sys.stdout), [log_level_predicate]
        )
        log.globalLogPublisher.addObserver(observer)

        self.ticker = self.factory.ticker_type(self.logger)
        self.ticker.start()

        self.connection_timer = self.ticker.add_delay(
            delay=self.factory.connection_timeout / self.ticker.interval,
            callback=self.connection_timed_out,
        )

        self.load_protocol(self.protocol_version)

        self.setup()

    def load_protocol(self, protocol_version):
        self.protocol, self.protocol_version, self.version_name = (
            quarry.data.get_protocol(protocol_version)
        )
        self.protocol["types"]["mapper"] = "native" # protodef braindamage
        self.switch_mode(self.protocol_mode)

    def switch_mode(self, mode):
        TERMS_MAP = {"downstream": "toClient", "upstream": "toServer"}
        self.protocol_mode = mode
        self.send_types = self.protocol["types"].copy()
        self.recv_types = self.protocol["types"].copy()
        self.recv_types.update(
            self.protocol[mode][TERMS_MAP[self.recv_direction]]["types"]
        )
        self.send_types.update(
            self.protocol[mode][TERMS_MAP[self.send_direction]]["types"]
        )
        self.logger.debug(f"Switched mode to {mode}")

    # Fix ugly twisted methods ------------------------------------------------

    def dataReceived(self, data):
        return self.data_received(data)

    def connectionMade(self):
        return self.connection_made()

    def connectionLost(self, reason=None):
        return self.connection_lost(reason)

    # Convenience functions ---------------------------------------------------

    def check_protocol_mode_switch(self, mode):
        transitions = [
            ("handshaking", "status"),
            ("handshaking", "login"),
            ("login", "play"),
            ("login", "configuration"),
            ("configuration", "play"),
        ]

        if (self.protocol_mode, mode) not in transitions:
            raise ProtocolError(
                "Cannot switch protocol mode from %s to %s" % (self.protocol_mode, mode)
            )

    def switch_protocol_mode(self, mode):
        self.check_protocol_mode_switch(mode)
        self.protocol_mode = mode

    def set_compression(self, compression_threshold):
        self.compression_threshold = compression_threshold
        self.logger.debug(
            "Compression threshold set to %d bytes" % compression_threshold
        )

    def close(self, reason=None):
        """Closes the connection"""

        if not self.closed:
            if reason:
                reason = "Closing connection: %s" % reason
            else:
                reason = "Closing connection"

            if self.in_game:
                self.logger.info(reason)
            else:
                self.logger.debug(reason)

            self.transport.loseConnection()
            self.closed = True

    def log_packet(self, prefix, name, data):
        """Logs a packet at debug level"""

        self.logger.debug("Packet %s %s/%s" % (prefix, self.protocol_mode, name))

    # General callbacks -------------------------------------------------------

    def setup(self):
        """Called when the Protocol's initialiser is finished"""

        pass

    def protocol_error(self, err):
        """Called when a protocol error occurs"""

        self.logger.exception(err)
        self.close("Protocol error")

    # Connection callbacks ----------------------------------------------------

    def connection_made(self):
        """Called when the connection is established"""

        self.logger.debug("Connection made")

    def connection_lost(self, reason=None):
        """Called when the connection is lost"""

        self.closed = True
        if self.in_game:
            self.player_left()
        self.logger.debug("Connection lost")

        self.ticker.stop()

    def connection_timed_out(self):
        """Called when the connection has been idle too long"""
        self.close("Connection timed out")

    # Auth callbacks ----------------------------------------------------------

    def auth_ok(self, data):
        """Called when auth with mojang succeeded (online mode only)"""

        pass

    def auth_failed(self, err):
        """Called when auth with mojang failed (online mode only)"""

        self.logger.warning("Auth failed: %s" % err.value)
        self.close("Auth failed: %s" % err.value)

    # Player callbacks --------------------------------------------------------

    def player_joined(self):
        """Called when the player joins the game"""

        self.in_game = True

    def player_left(self):
        """Called when the player leaves the game"""

        pass

    # Packet handling ---------------------------------------------------------

    def unpack_data(self):
        buff = Buffer(self.recv_buff.unpack_bytes(self.recv_buff.unpack_varint()), types=self.recv_types)
        if self.compression_threshold >= 0:
            uncompressed_length = buff.unpack_varint()
            if uncompressed_length > 0:
                buff = Buffer(
                    zlib.decompress(buff.unpack_bytes()),
                    types=self.recv_types,
                )
        return buff

    def data_received(self, data):
        data = self.cipher.decrypt(data)
        self.recv_buff.pack_bytes(data)

        while not self.closed:
            self.recv_buff.save()

            try:
                buffer = self.unpack_data()
            except BufferUnderrun:
                self.recv_buff.restore()
                break
            
            try:
                unpacked = buffer.unpack("packet")
                if len(buffer):
                    raise BufferUnderrun("not all unpack")
            except Exception as e:
                self.unpack_failed(e, buffer)
                continue

            unpacked["params"]["buff"] = buffer # hack for inspection of raw bytes

            self.packet_received(unpacked["params"], unpacked["name"])
            self.connection_timer.restart()
        
    def unpack_failed(self, error, buffer):
        """Called when bytes unpacked but packet unpacked failed"""
        self.logger.debug(f"Failed to unpack {error} on a {len(buffer.data)}B packet")

    def packet_received(self, data, name):
        """
        Called when a packet is received from the remote. Usually this method
        dispatches the packet to a method named ``packet_<packet name>``, or
        calls :meth:`packet_unhandled` if no such methods exists. You might
        want to override this to implement your own dispatch logic or logging.
        """

        self.log_packet(". recv", name, data)

        dispatched = self.dispatch((name,), data)

        if not dispatched:
            self.packet_unhandled(data, name)

    def packet_unhandled(self, data, name):
        """
        Called when a packet is received that is not hooked. The default
        implementation silently discards the packet.
        """
        pass

    def pack_bytes(self, data):
        b2 = Buffer(types=self.send_types)
        if self.compression_threshold >= 0:
            if len(data) >= self.compression_threshold:
                b2.pack_varint(len(data))
                b2.pack_bytes(zlib.compress(data))
            else:
                b2.pack_varint(0)
                b2.pack_bytes(data)
        else:
            b2.pack_bytes(data)

        b3 = Buffer(types=self.send_types)
        b3.pack_varint(len(b2))
        b3.pack_bytes(b2.unpack_bytes())
        data = b3.unpack_bytes()
        data = self.cipher.encrypt(data)
        return data

    def send_packet(self, name, data={}):
        """Sends a packet to the remote."""

        if self.closed:
            return

        self.log_packet("# send", name, data)

        b = Buffer(types=self.send_types)
        b.pack("packet", {"name": name, "params": data})
        data = self.pack_bytes(b.data)
        self.transport.write(data)


class Factory(protocol.Factory, object):
    protocol = Protocol
    ticker_type = Ticker
    log_level = log.LogLevel.info
    connection_timeout = 30
    force_protocol_version = None

    minecraft_versions = SUPPORTED_PROTOCOL_VERSIONS

    def buildProtocol(self, addr):
        return self.protocol(self, addr)
