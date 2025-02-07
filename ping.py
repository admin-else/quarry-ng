"""
Pinger example client

This example client connects to a server in "status" mode to retrieve some
information about the server. The information returned is what yo'd normally
see in the "Multiplayer" menu of the official client.
"""

from twisted.internet import reactor
from quarry.client import ClientFactory, ClientProtocol


class PingProtocol(ClientProtocol):
    def status_server_info(self, data):
        print(data)
        reactor.stop()


class PingFactory(ClientFactory):
    protocol = PingProtocol
    protocol_mode_next = "status"


def main():
    # parser = argparse.ArgumentParser()
    # parser.add_argument("host")
    # parser.add_argument("-p", "--port", default=25565, type=int)
    # args = parser.parse_args(argv)

    factory = PingFactory()
    factory.connect("127.0.0.1", 25565)
    reactor.run()


if __name__ == "__main__":
    import sys

    main()
