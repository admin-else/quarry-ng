import json
import quarry
from os import path

PATH = path.join(quarry.__path__[0], "data/data/")
PATH_DATA = path.join(PATH, "dataPaths.json")
COMMON_DATA = path.join(PATH, "pc/common")
LATEST_PROTOCOL_VERSION = 769

with open(PATH_DATA) as f:
    PATHS = json.load(f)


def get(version, data):
    data_path = PATHS["pc"].get(version, {}).get(data)
    if not data_path:
        raise FileNotFoundError(f"no data for {version}/{data}")
    data_path = path.join(PATH, data_path, data) + ".json"
    with open(data_path) as f:
        return json.load(f)


def common(data):
    with open(path.join(COMMON_DATA, data) + ".json") as f:
        return json.load(f)


SUPPORTED_PROTOCOL_VERSIONS = [v["version"] for v in common("protocolVersions")]


def get_protocol(protocol_version: str | int | None = None):
    protocol_version_name = None
    protocol_version_num = None
    if protocol_version is None:
        protocol_version_num = LATEST_PROTOCOL_VERSION
    elif type(protocol_version) is int:
        protocol_version_num = protocol_version
    else:
        protocol_version_name = protocol_version

    protocol_versions = common("protocolVersions")
    if protocol_version_name is None:
        data = [
            version["minecraftVersion"]
            for version in protocol_versions
            if version["version"] == protocol_version_num
        ]
        if not data:
            raise ValueError(f"Did not find protocol version {protocol_version}.")
        protocol_version_name = data[0]
    if protocol_version_num is None:
        data = [
            version["version"]
            for version in protocol_versions
            if version["minecraftVersion"] == protocol_version_name
        ]
        if not data:
            raise ValueError(f"Did not find protocol version {protocol_version}")
        protocol_version_num = data[0]

    return (
        get(protocol_version_name, "protocol"),
        protocol_version_num,
        protocol_version_name,
    )
