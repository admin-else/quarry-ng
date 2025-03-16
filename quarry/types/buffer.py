"""
Reasons why i hate protodef
1. they dont have mapper in native for some reason
2. they randomly switcht from hex to normal numbers in mapper type
3. doesnt use snake_case
4. uses strings for all key (ok this is kinda unfair but still annyoing)
5. UUID being UUID and not uuid

"""

import json
import struct
from mutf8.mutf8 import encode_modified_utf8, decode_modified_utf8
import re
from quarry.types.uuid import UUID


class BufferUnderrun(Exception):
    pass


MAX_VARNUM_LEN = 10
NBT_TYPE_MAP = {
    0: "end",
    1: "byte",
    2: "short",
    3: "int",
    4: "long",
    5: "float",
    6: "double",
    7: "byte_array",
    8: "string",
    9: "list",
    10: "compound",
    11: "int_array",
    12: "long_array",
}

UNPACK_SWITCH_SPECIAL_VALUES = {"True": "true", "False": "false"}

NUM_REGEX = re.compile(
    r"\b(0x[0-9a-fA-F]+|[0-9]+)\b"
)  # thx i am not gud at regex: https://stackoverflow.com/questions/38247948/regular-expression-for-valid-decimal-or-hexadecimal-with-prefix


def to_snake_case(s: str):
    out = ""
    for c in s:
        if c.isupper():
            out += "_" + c.lower()
        else:
            out += c
    return out


def reverse_lookup(d, target_value):
    return [key for key, value in d.items() if value == target_value][0]


class Buffer:
    pos = 0
    container_stack = []

    def __init__(self, data: bytes = b"", types={}) -> None:
        self.data = data
        self.types = types
        self.fix_names()

    def pack_bytes(self, data):
        self.data += data

    def peek(self, method, *args, **kwargs):
        saved_pos = self.pos
        data = method(*args, **kwargs)
        self.pos = saved_pos
        return data

    def reset(self):
        self.data = b""
        self.pos = 0

    def set_data(self, data):
        self.data = data
        self.pos = 0

    def save(self):
        self.data = self.data[self.pos :]
        self.pos = 0

    def restore(self):
        self.pos = 0

    def discard(self):
        self.pos = len(self.data)

    def __len__(self):
        return len(self.data) - self.pos

    def unpack_bytes(self, count=None):
        if count and len(self) < count:
            raise BufferUnderrun("buffer not big enough")

        data = self.data[self.pos : self.pos + count if count is not None else None]
        self.pos = self.pos + count if count is not None else len(self.data)
        return data

    def pack_c(self, fmt, *fields):
        self.pack_bytes(struct.pack(">" + fmt, *fields))

    def unpack_c(self, fmt):
        fmt = ">" + fmt
        data = self.unpack_bytes(struct.calcsize(fmt))
        data = struct.unpack(fmt, data)
        if len(data) == 1:
            return data[0]
        return data

    def unpack_u8(self):
        return self.unpack_c("B")

    def unpack_u16(self):
        return self.unpack_c("H")

    def unpack_u32(self):
        return self.unpack_c("I")

    def unpack_u64(self):
        return self.unpack_c("Q")

    def unpack_i8(self):
        return self.unpack_c("b")

    def unpack_i16(self):
        return self.unpack_c("h")

    def unpack_i32(self):
        return self.unpack_c("i")

    def unpack_i64(self):
        return self.unpack_c("q")

    def unpack_f32(self):
        return self.unpack_c("f")

    def unpack_f64(self):
        return self.unpack_c("d")

    def pack_u8(self, data):
        self.pack_c("B", data)

    def pack_u16(self, data):
        self.pack_c("H", data)

    def pack_u32(self, data):
        self.pack_c("I", data)

    def pack_u64(self, data):
        self.pack_c("Q", data)

    def pack_i8(self, data):
        self.pack_c("b", data)

    def pack_i16(self, data):
        self.pack_c("h", data)

    def pack_i32(self, data):
        self.pack_c("i", data)

    def pack_i64(self, data):
        self.pack_c("q", data)

    def pack_f32(self, data):
        self.pack_c("f", data)

    def pack_f64(self, data):
        self.pack_c("d", data)

    def unpack_bool(self):
        return self.unpack_c("?")

    def pack_bool(self, data):
        self.pack_c("?", data)

    def unpack_void(self):
        pass

    def pack_void(self):
        pass

    def unpack_uuid(self):
        return UUID(bytes=self.unpack_bytes(16)).hex

    def pack_uuid(self, data):
        if type(data) is str:
            self.pack_bytes(UUID(hex=data).bytes)
        elif type(data) is UUID:
            self.pack_bytes(data.bytes)

    def pack_varnum(self, number, max_bits):
        number_min = -1 << (max_bits - 1)
        number_max = +1 << (max_bits - 1)
        if not (number_min <= number < number_max):
            raise ValueError(
                f"varnum does not fit in range: {number_min:_} <= {number:_} < {number_max:_}"
            )

        if number < 0:
            number += 1 << 32

        for _ in range(10):
            b = number & 0x7F
            number >>= 7
            self.pack_u8(b | (0x80 if number > 0 else 0))
            if number == 0:
                break

    def unpack_varnum(self, max_bits):
        number = 0
        for i in range(10):
            b = self.unpack_u8()
            number |= (b & 0x7F) << 7 * i
            if not b & 0x80:
                break

        if number & (1 << 31):
            number -= 1 << 32

        number_min = -1 << (max_bits - 1)
        number_max = +1 << (max_bits - 1)
        if not (number_min <= number < number_max):
            raise ValueError(
                f"varnum does not fit in range: {number_min:_} <= {number:_} < {number_max:_}"
            )

        return number

    def unpack_varint(self):
        return self.unpack_varnum(32)

    def pack_varint(self, data):
        self.pack_varnum(data, 32)

    def unpack_varlong(self):
        return self.unpack_varnum(64)

    def pack_varlong(self, data):
        self.pack_varnum(data, 64)

    def unpack_rest_buffer(self):
        return self.unpack_bytes()

    def pack_rest_buffer(self, data):
        self.pack_bytes(data)

    # protodef stuff

    def get_var(self, path):
        container_stack_index = -1
        data = self.container_stack[container_stack_index]
        for part in path.split("/"):
            if part == "..":
                container_stack_index -= 1
                data = self.container_stack[container_stack_index]
            else:
                data = data[part]
        return data

    def unpack(self, protodef):
        data = None
        if type(protodef) is str:
            type_name = protodef
        else:
            type_name, data = protodef

        method = getattr(self, "unpack_" + type_name, None)
        if method:
            if data is not None:
                return method(data)
            return method()

        protodef = self.types.get(type_name)
        if protodef == "native":
            raise NotImplementedError(f"Please implement {type_name}")
        if not protodef:
            raise ValueError(f"i cannot find the protodef for {type_name}")
        return self.unpack(protodef)

    def pack(self, protodef, data):
        next_protodef = None
        if type(protodef) is str:
            type_name = protodef
        else:
            type_name, next_protodef = protodef

        method = getattr(self, "pack_" + type_name, None)
        if method:
            if next_protodef is not None:
                return method(next_protodef, data)
            return method(data)
        protodef = self.types.get(type_name)
        self.pack(protodef, data)

    def unpack_container(self, protodef):
        ret = {}
        self.container_stack.append(ret)
        for field in protodef:
            data = self.unpack(field["type"])
            if field.get("anon", False):
                if type(data) is dict:
                    ret.update(data)
            else:
                ret[field["name"]] = data
        self.container_stack.pop()

        return ret

    def pack_container(self, protodef, data):
        self.container_stack.append(data)
        for field in protodef:
            self.pack(field["type"], data[field["name"]])
        self.container_stack.pop()

    def unpack_switch(self, protodef):
        data = str(self.get_var(protodef["compareTo"]))
        data = UNPACK_SWITCH_SPECIAL_VALUES.get(
            data, data
        )  # returns fixed value if not present return normal value
        return self.unpack(protodef["fields"].get(data, protodef.get("default")))

    def pack_switch(self, protodef, data):
        val = str(self.get_var(protodef["compareTo"]))
        self.pack(protodef["fields"][val], data)

    def pack_pstring(self, protodef, data):
        self.pack(protodef["countType"], len(data))
        self.pack_bytes(data.encode("utf-8"))

    def unpack_pstring(self, protodef):
        lenght = self.unpack(protodef["countType"])
        return str(self.unpack_bytes(lenght), encoding="utf-8")

    def unpack_option(self, protodef):
        if self.unpack_bool():
            return self.unpack(protodef)

    def pack_option(self, protodef, data):
        self.pack_bool(False if data is None else True)
        if data is not None:
            self.pack(protodef, data)

    def unpack_bitfield(self, protodef):
        funcmap = {
            8: self.unpack_u8,
            16: self.unpack_u16,
            32: self.unpack_u32,
            64: self.unpack_u64,
        }
        ret = {}
        pos = 0
        total_size = sum([field["size"] for field in protodef])
        data = funcmap[total_size]()

        ret = {}
        for field in protodef:
            size = field["size"]
            res = (data >> (total_size - pos - size)) & 2**size - 1
            if field["signed"] and res >= 1 << (size - 1):
                res -= 1 << size
            ret[field["name"]] = res
            pos += size

        return ret

    def pack_bitfield(self, protodef, data):
        funcmap = {
            8: self.pack_u8,
            16: self.pack_u16,
            32: self.pack_u32,
            64: self.pack_u64,
        }

        ret = 0
        pos = 0
        total_size = sum([field["size"] for field in protodef])
        for field in protodef:
            size = field["size"]
            num = data[field["name"]]
            if num < 0:
                num += 1 << size
            ret |= num << (total_size - size - pos)
            pos += size

        funcmap[total_size](ret)

    def pack_array(self, protodef, data):
        self.pack(protodef["countType"], len(data))
        for element in data:
            self.pack(protodef["type"], element)

    def unpack_array(self, protodef):
        if "countType" in protodef:
            count = self.unpack(protodef["countType"])
        elif "count" in protodef:
            count = self.get_var(protodef["count"])
        ret = []
        for _ in range(count):
            ret.append(self.unpack(protodef["type"]))
        return ret

    def unpack_buffer(self, protodef):
        count = protodef.get("count", None)
        if count is None:
            count = self.unpack(protodef["countType"])
        return self.unpack_bytes(count)

    def pack_buffer(self, protodef, data):
        if "countType" in protodef:
            self.pack(protodef["countType"], len(data))
        self.pack_bytes(data)

    def pack_entity_metadata_loop(self, protodef, data):
        for index in data:
            self.pack_u8(index)
            self.pack(protodef["type"], data[index])
        self.pack_u8(protodef["endVal"])

    def unpack_entity_metadata_loop(self, protodef):
        ret = {}
        while True:
            index = self.unpack_u8()
            if index == protodef["endVal"]:
                break
            ret[index] = self.unpack(protodef["type"])
        return ret

    def unpack_top_bit_set_terminated_array(self, protodef):
        ret = []
        while True:
            saved_byte = self.data[self.pos]
            self.data[self.pos] &= 0x7F
            ret.append(self.unpack(protodef["type"]))
            if saved_byte & 0x80:
                break

        return ret

    def pack_top_bit_set_terminated_array(self, protodef, data):
        for i, element in enumerate(data):
            old_pos = len(self)
            self.pack(protodef["type"], element)
            if len(element) - 1 == i:
                self.data[old_pos] |= 0x80

    def unpack_mapper(self, protodef):
        data = str(self.unpack(protodef["type"]))
        for org_mapping in protodef["mappings"]:
            mapping = org_mapping
            if re.fullmatch(NUM_REGEX, mapping):
                mapping = str(int(mapping, base=0))
            if mapping == data:
                return protodef["mappings"][org_mapping]
        raise KeyError("Not found")

    def pack_mapper(self, protodef, data):
        for mapping in protodef["mappings"]:
            if protodef["mappings"][mapping] == data:
                if re.fullmatch(NUM_REGEX, mapping):
                    mapping = int(mapping, base=0)
                self.pack(protodef["type"], mapping)

    # NBT

    unpack_nbt_double = unpack_f64
    unpack_nbt_short = unpack_i16
    unpack_nbt_byte = unpack_i8
    unpack_nbt_int = unpack_i32
    unpack_nbt_long = unpack_i64
    unpack_nbt_float = unpack_f32
    pack_nbt_byte = pack_i8
    pack_nbt_short = pack_i16
    pack_nbt_int = pack_i32
    pack_nbt_long = pack_i64
    pack_nbt_float = pack_f32
    pack_nbt_double = pack_f64

    def pack_nbt_end(self, data):
        pass

    def unpack_nbt_end(self):
        pass

    def unpack_nbt_string(self):
        return decode_modified_utf8(self.unpack_bytes(self.unpack_nbt_short()))

    def pack_nbt_string(self, data):
        data = encode_modified_utf8(data)
        self.pack_nbt_short(len(data))
        self.pack_bytes(data)

    def unpack_nbt_num_array(self, nbt_type):
        unpack = getattr(self, f"unpack_nbt_{nbt_type}")
        amount = self.unpack_nbt_int()
        return [unpack() for _ in range(amount)]

    def pack_nbt_num_array(self, nbt_type, data):
        self.pack_nbt_int(len(data))
        pack = getattr(self, f"pack_nbt_{nbt_type}")
        [pack(num) for num in data]

    def unpack_nbt_byte_array(self):
        return self.unpack_nbt_num_array("byte")

    def unpack_nbt_int_array(self):
        return self.unpack_nbt_num_array("int")

    def unpack_nbt_long_array(self):
        return self.unpack_nbt_num_array("long")

    def pack_nbt_byte_array(self, data):
        self.pack_nbt_num_array("byte", data)

    def pack_nbt_int_array(self, data):
        self.pack_nbt_num_array("int", data)

    def pack_nbt_long_array(self, data):
        self.pack_nbt_num_array("long", data)

    def unpack_nbt_list(self):
        nbt_type = NBT_TYPE_MAP[self.unpack_i8()]
        amount = self.unpack_nbt_int()
        if nbt_type == "end" and amount > 0:
            raise ValueError("nbt list of type end is bigger than 0 elements.")
        unpack = getattr(self, f"unpack_nbt_{nbt_type}")
        return [unpack() for _ in range(amount)]

    def pack_nbt_list(self, data):
        self.pack_nbt_int(len(data["value"]))
        pack = getattr(self, f"pack_nbt_{data['type']}")
        [pack(data) for data in data["value"]]

    def pack_nbt_compound(self, data):
        for entry in data:
            self.pack_nbt(entry)
        self.pack_nbt_anon({"type": "end", "value": None})

    def unpack_nbt_compound(self):
        data = []
        while True:
            tag = self.unpack_nbt()
            if tag["type"] == "end":
                break
            data.append(tag)
        return data

    def pack_nbt(self, data):
        self.pack_nbt_byte(reverse_lookup(NBT_TYPE_MAP, data["type"]))
        self.pack_nbt_string(data["name"])
        self.pack("nbt_" + data["type"], data["value"])

    def unpack_nbt(self):
        nbt_type = NBT_TYPE_MAP[self.unpack_i8()]
        if nbt_type == "end":
            return {"type": "end", "name": None, "value": None}
        return {
            "type": nbt_type,
            "name": self.unpack_nbt_string(),
            "value": self.unpack("nbt_" + nbt_type),
        }

    def pack_nbt_anon(self, data):
        self.pack_nbt_byte(reverse_lookup(NBT_TYPE_MAP, data))
        self.pack("nbt_" + data["type"], data["value"])

    def unpack_nbt_anon(self):
        nbt_type = NBT_TYPE_MAP[self.unpack_nbt_byte()]
        return {"type": nbt_type, "value": self.unpack("nbt_" + nbt_type)}

    def unpack_anonymous_nbt(self):
        return self.unpack_nbt_anon()

    def pack_anonymous_nbt(self, data):
        self.pack_nbt_anon(data)

    def unpack_anon_optional_nbt(self):
        if not self.peek(self.unpack_nbt_byte):
            self.unpack_nbt_byte()
            return None
        return self.unpack_anonymous_nbt()

    def pack_anon_optional_nbt(self, data):
        if not data:
            self.pack_nbt_byte(0)
            return
        self.pack_anonymous_nbt(data)

    def unpack_json(self):
        return json.loads(self.unpack("string"))

    def pack_json(self, data):
        self.pack("string", json.dumps(data))

    def unpack_registry_entry_holder_set(self, protodef):
        n = self.unpack_varint()
        if n == 0:
            return {protodef["base"]["name"]: self.unpack(protodef["base"]["type"])}
        return {
            protodef["otherwise"]["name"]: self.unpack(protodef["otherwise"]["type"])
            for _ in range(n)
        }

    def pack_registry_entry_holder_set(self, protodef, data):
        if protodef["base"]["name"] in data:
            self.pack_varint(0)
            self.pack(protodef["base"]["type"], data[protodef["base"]["name"]])
        elif protodef["otherwise"]["name"] in data:
            self.pack_varint(len(data[protodef["otherise"]["name"]]))
            [
                self.pack(protodef["otherwise"]["type"], value)
                for value in data[protodef["otherwise"]["name"]]
            ]
        else:
            raise ValueError("data has to have a base or otherwise key")

    # i should implement support for what this is doing but iam lazy
    # https://github.com/PrismarineJS/node-minecraft-protocol/blob/e9eb551ba30ec2e742c49e6927be6402b413bb76/src/datatypes/compiler-minecraft.js#L195
    def unpack_bitflags(self, protodef):
        data = self.unpack(protodef["type"])
        ret = []
        for i, name in enumerate(protodef["flags"]):
            if data & 2 << i:
                ret.append(name)
        return ret

    def pack_bitflags(self, protodef, data):
        result = 0
        for i, name in enumerate(protodef["flags"]):
            if name in data:
                result |= 2 << i
        self.pack(protodef["type"], result)

    # fuck camel case
    def alias(self, new_name, old_name):
        setattr(self, new_name, getattr(self, old_name))

    def alias_pair(self, new_name, old_name):
        self.alias(f"unpack_{new_name}", f"unpack_{old_name}")
        self.alias(f"pack_{new_name}", f"pack_{old_name}")

    def fix_names(self):
        self.alias_pair("UUID", "uuid")
        self.alias_pair("entityMetadataLoop", "entity_metadata_loop")
        self.alias_pair("anonymousNbt", "anonymous_nbt")
        self.alias_pair("restBuffer", "rest_buffer")
        self.alias_pair("anonOptionalNbt", "anon_optional_nbt")
        self.alias_pair("registryEntryHolderSet", "registry_entry_holder_set")
        self.alias_pair("topBitSetTerminatedArray", "top_bit_set_terminated_array")
