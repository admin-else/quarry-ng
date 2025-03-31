# Quarry NG Failed unpack
# Failed with error
# 'Not found'
# recv dir send dir
# downstream upstream
# protocol mode
# play

import json
from pprint import pprint
from quarryng.types.buffer import Buffer

with open(".failed_unpacks/types/769-play.json") as f:
    types = json.load(f)
    
buffer = Buffer(b'|\x8d\x8f\x02\x02\x15?\xf333@\x00\x00\x00\x00\x16\x00\x00\x00\x00\x00\x00\x00\x00\x00', types=types)
pprint(buffer.unpack("packet"))

b = buffer
b.unpack_varint() # packet id: 124 (0x7c)
b.unpack_varint() # entity id: 34701
b.unpack_varint() # array len: 2
