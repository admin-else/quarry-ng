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
from quarry.net.auth import OfflineProfile, Profile
from quarry.net.client import ClientFactory, SpawningClientProtocol
from quarry.types import uuid


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
    factory = MinecraftFactory(Profile(access_token="eyJraWQiOiJhYzg0YSIsImFsZyI6IkhTMjU2In0.eyJ4dWlkIjoiMjUzNTQwODczNjU4Mzg2NyIsImFnZyI6IkFkdWx0Iiwic3ViIjoiZmFjYWQ2NjYtNGFiYS00MDU3LTlmOWQtMzQ5NDI2NDQ2MzAzIiwiYXV0aCI6IlhCT1giLCJucyI6ImRlZmF1bHQiLCJyb2xlcyI6W10sImlzcyI6ImF1dGhlbnRpY2F0aW9uIiwiZmxhZ3MiOlsidHdvZmFjdG9yYXV0aCIsIm1pbmVjcmFmdF9uZXQiLCJtc2FtaWdyYXRpb25fc3RhZ2U0Iiwib3JkZXJzXzIwMjIiLCJtdWx0aXBsYXllciJdLCJwcm9maWxlcyI6eyJtYyI6IjM2MzIzMzBkLTM3MzctNDI3MC04ZThmLTI3MGU1ODFjNDVkYiJ9LCJwbGF0Zm9ybSI6IlVOS05PV04iLCJ5dWlkIjoiZGFiNGQ0ZDJmMDU3NDdhY2YxODlhMWU1MTUwMzlkY2QiLCJuYmYiOjE3NDAwODYzODYsImV4cCI6MTc0MDE3Mjc4NiwiaWF0IjoxNzQwMDg2Mzg2fQ.g1baVXOP7lMnp0bXpz0gOHQ37MEf88Gog4BoVq6CsuY", display_name="Admin_Else", uuid=uuid.UUID("3632330d-3737-4270-8e8f-270e581c45db"), client_token=""))

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
