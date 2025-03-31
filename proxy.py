from twisted.internet import reactor
from quarryng.net.proxy import DownstreamFactory, Bridge
from twisted.logger import LogLevel

COMMAND_PREFIX = "%"

class FlyingBridge(Bridge):
    def packet_upstream_chat_message(self, data):
        message = data["message"]
        if not message.startswith(COMMAND_PREFIX):
            return data
        
        command = message.removeprefix(COMMAND_PREFIX)
        command, *args = command.split(" ")
        cmd_func = getattr(self, f"command_{command}", None)
        if cmd_func:
            cmd_func(args)
        else:
            pass
            #self.send_message(f"Did not find Command {command}")
            
    def command_gamemode(self, args):
        self.downstream.send_packet("game_state_change", {'reason': 3, 'gameMode': int(args[0])})
        
    def send_message(self, message):
        self.upstream.send_packet("profileless_chat", 
{'message': {'type': 'string', 'value': message}, 'type': {'registryIndex': 5}, 'name': {'type': 'string', 'value': '%Q'}, 'target': None})

class QuietDownstreamFactory(DownstreamFactory):
    bridge_class = FlyingBridge
    log_level = LogLevel.warn
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
