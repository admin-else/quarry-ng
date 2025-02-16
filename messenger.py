"""
Messenger example client

Bridges minecraft chat (in/out) with stdout and stdin.

This client makes no attempt to verify received signed messages, or sign sent messages.
"""

import os
import sys
from time import time
from twisted import logger as log
from twisted.internet import reactor, stdio
from twisted.protocols import basic
from quarry.net.auth import OfflineProfile
from quarry.net.client import ClientFactory, SpawningClientProtocol


class StdioProtocol(basic.LineReceiver):
    delimiter = os.linesep.encode("ascii")
    in_encoding = getattr(sys.stdin, "encoding", "utf8")
    out_encoding = getattr(sys.stdout, "encoding", "utf8")

    def lineReceived(self, line):
        self.minecraft_protocol.send_chat(line.decode(self.in_encoding))

    def send_line(self, text):
        self.sendLine(text.encode(self.out_encoding))


class MinecraftProtocol(SpawningClientProtocol):
    spawned = False

    # 1.19+
    def packet_system_message(self, data):
        print(data)
        p_text = data.unpack_chat().to_string()
        p_display = False

        # Ignore game info (action bar) messages
        if self.protocol_version >= 760:
            p_display = not data.unpack("?")  # Boolean for whether message is game info
        else:
            p_display = (
                data.unpack_varint() != 2
            )  # Varint for position where 2 is game info

        data.discard()

        if p_display and p_text.strip():
            self.stdio_protocol.send_line(":: %s" % p_text)

    def packet_chat_message(self, data):
        print(data)

    def send_chat(self, text):
        self.send_packet(
            "chat_message",
            {
                "message": text,
                "timestamp": int(time() * 1000),
                "salt": 0,
                "offset": 0,
                "signature": b"",
                "acknowledged": b"",
            },
        )


class MinecraftFactory(ClientFactory):
    protocol = MinecraftProtocol
    log_level = log.LogLevel.debug

    def buildProtocol(self, addr):
        minecraft_protocol = super(MinecraftFactory, self).buildProtocol(addr)
        stdio_protocol = StdioProtocol()

        minecraft_protocol.stdio_protocol = stdio_protocol
        stdio_protocol.minecraft_protocol = minecraft_protocol

        stdio.StandardIO(stdio_protocol)
        return minecraft_protocol


def run():
    # Log in
    # Create factory
    factory = MinecraftFactory(OfflineProfile())

    # Connect!
    factory.connect("127.0.0.1")


def main(argv):
    # parser = ProfileCLI.make_parser()
    # parser.add_argument("host")
    # parser.add_argument("port", nargs='?', default=25565, type=int)
    # args = parser.parse_args(argv)
    run()
    reactor.run()


if __name__ == "__main__":
    main(sys.argv[1:])
