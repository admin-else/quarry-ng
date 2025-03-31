import functools
import re

@functools.total_ordering
class Message(object):
    """
    Represents a Minecraft chat message.
    """
    def __init__(self, value):
        self.value = value

    @classmethod
    def from_buff(cls, buff):
        return cls(buff.unpack_json())

    def to_bytes(self):
        from quarryng.types.buffer import Buffer

        return Buffer.pack_json(self.value)

    @classmethod
    def from_string(cls, string):
        return cls({'text': string})

    def to_string(self, strip_styles=True):
        """
        Minecraft uses a JSON format to represent chat messages; this method
        retrieves a plaintext representation, optionally including styles
        encoded using old-school chat codes (U+00A7 plus one character).
        """

        def parse(obj):
            if isinstance(obj, str):
                return obj
            if isinstance(obj, list):
                return "".join((parse(e) for e in obj))
            if isinstance(obj, dict):
                text = ""
                if "translate" in obj:
                    text += obj["translate"]
                    if "with" in obj:
                        args = ", ".join((parse(e) for e in obj["with"]))
                        text += "{%s}" % args
                if "text" in obj:
                    text += obj["text"]
                if "extra" in obj:
                    text += parse(obj["extra"])
                return text

        text = parse(self.value)
        if strip_styles:
            text = self.strip_chat_styles(text)
        return text

    @classmethod
    def strip_chat_styles(cls, text):
        return re.sub("\u00A7.", "", text)

    def __eq__(self, other):
        return self.value == other.value

    def __lt__(self, other):
        return self.value < other.value

    def __str__(self):
        return self.to_string()

    def __repr__(self):
        return "<Message %r>" % str(self)

