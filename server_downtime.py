"""
Example "downtime" server

This server kicks players with the MOTD when they try to connect. It can be
useful for when you want players to know that your usual server is down for
maintenance.
"""

from twisted.internet import reactor
from quarry.net.server import ServerFactory, ServerProtocol


class DowntimeProtocol(ServerProtocol):
    def packet_login_start(self, data):
        self.close(self.factory.motd)


class DowntimeFactory(ServerFactory):
    protocol = DowntimeProtocol
    online_mode = False


def main(argv):
    # Parse options
    #import argparse
    #parser = argparse.ArgumentParser()
    #parser.add_argument("-a", "--host", default="", help="address to listen on")
    #parser.add_argument("-p", "--port", default=25565, type=int, help="port to listen on")
    #parser.add_argument("-m", "--message", default="We're down for maintenance",
    #                    help="message to kick users with")
    #args = parser.parse_args(argv)

    # Create factory
    factory = DowntimeFactory()
    factory.motd = "s2igma server"

    # Listen
    factory.listen("127.0.0.1", 25566)
    reactor.run()


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])