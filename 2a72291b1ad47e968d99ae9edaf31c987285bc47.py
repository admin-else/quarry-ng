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
    
buffer = Buffer(b']\x8d\x8f\x02\x01\x01\xd3\x1f\t\x03A \x00\x00\xff', types=types)
out = buffer.unpack("packet")
pprint(out)
