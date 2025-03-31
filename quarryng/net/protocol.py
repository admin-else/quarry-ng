import sys
import zlib
from twisted.internet import protocol
from twisted import logger as log
import quarryng
import quarryng.types
from quarryng.data import LATEST_PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS
from quarryng.types.buffer import Buffer, BufferUnderrun
from quarryng.net.crypto import Cipher
from quarryng.net.ticker import Ticker


protocol_modes = {0: "init", 1: "status", 2: "login", 3: "play"}
protocol_modes_inv = dict(((v, k) for k, v in protocol_modes.items()))


class ProtocolError(Exception):
    pass


class PackingError(Exception):
    pass


class PacketDispatcher(object):
    def dispatch(self, lookup_args, buff):
        handler = getattr(self, f"packet_{'_'.join(lookup_args)}", None)
        if handler is not None:
            result = handler(buff)
            return (True, result)
        return (False, None)


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
    logger_namespace = __name__

    # For debugging failed packets
    should_save_failed_packet = True
    
    def __init__(self, factory, remote_addr):
        self.factory = factory
        self.remote_addr = remote_addr

        self.cipher = Cipher()

        self.logger = log.Logger(self.logger_namespace)

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
            quarryng.data.get_protocol(protocol_version)
        )
        self.protocol["types"]["mapper"] = "native"  # protodef braindamage
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
        self.logger.debug("Switched mode to {mode}", mode=mode)

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
        self.switch_mode(mode)

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
        for term in ["entity", "tick"]:
            if term in name:
                return
        self.logger.debug("Packet {prefix} {mode}/{name} {data}", prefix=prefix, mode=self.protocol_mode, name=name, data=data)

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
        buff = Buffer(
            self.recv_buff.unpack_bytes(self.recv_buff.unpack_varint()),
            types=self.recv_types,
        )
        if self.compression_threshold >= 0:
            uncompressed_length = buff.unpack_varint()
            if uncompressed_length > 0:
                buff = Buffer(
                    zlib.decompress(buff.unpack_bytes()),
                    types=self.recv_types,
                )
        buff.save()
        return buff

    def data_received(self, data):
        data = self.cipher.decrypt(data)
        self.recv_buff.pack_bytes(data)

        while not self.closed:
            self.recv_buff.save()
            try:
                buffer = self.unpack_data()
            except (BufferUnderrun, zlib.error): # large packets can trigger a zlib error
                self.recv_buff.restore()
                break

            try:
                unpacked = buffer.unpack("packet")
                if len(buffer):
                    raise BufferUnderrun("not all unpack")
            except Exception as e:
                if self.should_save_failed_packet:
                    self.save_failed_packet(e, buffer)
                self.unpack_failed(e, buffer)
                continue

            self.packet_received(unpacked["params"], unpacked["name"], buffer)
            self.connection_timer.restart()

    def save_failed_packet(self, error, buffer):
        import os 
        import json
        import hashlib
        data_hash = hashlib.sha1(buffer.data).hexdigest()
        path = f".failed_unpacks/{data_hash}.py"
        if os.path.exists(path):
            return
        types_hash = f"{self.protocol_version}-{self.protocol_mode}"
        types_path = f".failed_unpacks/types/{types_hash}.json"
        if not os.path.exists(types_path):
            with open(types_path, "w") as f:
                json.dump(buffer.types, f)
        
        py = f"""# Quarry NG Failed unpack
# Failed with error
# {error}
# recv dir send dir
# {self.recv_direction} {self.send_direction}
# protocol mode
# {self.protocol_mode}

import json
from pprint import pprint
from quarryng.types.buffer import Buffer

with open("{types_path}") as f:
    types = json.load(f)
    
buffer = Buffer({buffer.data}, types=types)
pprint(buffer.unpack("packet"))
"""
        with open(path, "w") as f:
            f.write(py)
        

    def unpack_failed(self, error, buffer):
        """
        Called when bytes unpacked but packet unpacked failed.
        """

        self.logger.debug("Failed to unpack {error} on a {buffer_len}B packet", error=error, buffer_len=len(buffer.data))

    def packet_received(self, data, name, buffer):
        """
        Called when a packet is received from the remote. Usually this method
        dispatches the packet to a method named ``packet_<packet name>``, or
        calls :meth:`packet_unhandled` if no such methods exists. You might
        want to override this to implement your own dispatch logic or logging.
        """

        self.log_packet("recv", name, data)

        dispatched, result = self.dispatch((name,), data)

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

        self.log_packet("send", name, data)

        try:
            b = Buffer(types=self.send_types)
            b.pack("packet", {"name": name, "params": data})
        except Exception as e:
            raise PackingError from e

        self.send_bytes(b.data)

    def send_bytes(self, bytes_to_send):
        self.transport.write(self.pack_bytes(bytes_to_send))


class Factory(protocol.Factory, object):
    protocol = Protocol
    ticker_type = Ticker
    log_level = log.LogLevel.info
    connection_timeout = 30
    force_protocol_version = None

    minecraft_versions = SUPPORTED_PROTOCOL_VERSIONS

    def buildProtocol(self, addr):
        return self.protocol(self, addr)
