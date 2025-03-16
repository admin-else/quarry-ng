from twisted.internet import reactor
from quarry.net.proxy import DownstreamFactory, Bridge
from twisted.logger import LogLevel


class QuietBridge(Bridge):
    pass

class QuietDownstreamFactory(DownstreamFactory):
    bridge_class = QuietBridge
    log_level = LogLevel.debug
    motd = "Proxy Server"


def main(argv):
    # Parse options
    # import argparse

    # parser = argparse.ArgumentParser()
    # parser.add_argument("-a", "--listen-host", default="", help="address to listen on")
    # parser.add_argument(
    #    "-p", "--listen-port", default=25565, type=int, help="port to listen on"
    # )
    # parser.add_argument(
    #    "-b", "--connect-host", default="127.0.0.1", help="address to connect to"
    # )
    # parser.add_argument(
    #    "-q", "--connect-port", default=25565, type=int, help="port to connect to"
    # )
    # args = parser.parse_args(argv)

    # Create factory
    factory = QuietDownstreamFactory()
    factory.connect_host = "127.0.0.1"
    factory.connect_port = 25565

    # Listen
    factory.listen("127.0.0.1", 25566)
    reactor.run()


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
