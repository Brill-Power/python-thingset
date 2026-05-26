# python-thingset

Python client library for [ThingSet](https://thingset.io), a protocol for IoT
devices over serial, CAN and IP transports. Supports both synchronous and
asynchronous I/O, structured schema discovery, broadcast report reception and
gateway forwarding.

Requires Python ≥ 3.10.

## Install

```sh
pip install python-thingset
```

## Transports

Each transport has its own constructor — there is no factory.

| Wire          | Sync class       | Async class                       |
|---------------|------------------|-----------------------------------|
| TCP/IP        | `ThingSetTCP`    | `AsyncThingSetTCP`                |
| CAN + ISO-TP  | `ThingSetCAN`    | _(not planned)_                   |
| CAN (listen)  | _(none)_         | `AsyncThingSetCANReportReceiver`  |
| Serial        | `ThingSetSerial` | _(not planned)_                   |
| UDP (listen)  | _(none)_         | `AsyncThingSetUDPReceiver`        |

All classes are context managers; `with` / `async with` handles connection
setup and tear-down.

## Sync

### Read a single value

```python
from python_thingset import ThingSetTCP

with ThingSetTCP("192.0.2.1") as client:
    r = client.get(0xF03)
    print(r.status_string, r.data)    # CONTENT native_sim
```

### Read a whole group

```python
with ThingSetTCP("192.0.2.1") as client:
    r = client.get(0x0F)
    print(r.data)
    # {0xF01: '05a736ef', 0xF02: 'AdamMitchell',
    #  0xF03: 'native_sim', 0xF05: [0, 48, 0, 1]}
```

### Enumerate a group's children

```python
with ThingSetTCP("192.0.2.1") as client:
    r = client.fetch(0x00, [])     # root
    print(r.data)                  # [0x0E, 0x0F, 0x67, ...]
```

### Update and execute

```python
with ThingSetTCP("192.0.2.1") as client:
    client.update(0x509, True, parent_id=0x05)   # HMCU/sDFUOverride = True
    client.exec(0x52, [])                         # HMCU/xSaveNVM()
```

`update` also accepts list values, which are sent as a CBOR array (binary
transports) or JSON array (text transport):

```python
with ThingSetTCP("192.0.2.1") as client:
    client.update(0x70A, [3.7, 3.7, 3.6], parent_id=0x07)   # array of floats
```

### CAN

```python
from python_thingset import ThingSetCAN

with ThingSetCAN("vcan0") as client:
    r = client.get(0xF03, node_id=0x10)   # target CAN node 0x10
    print(r.data)
```

### Schema discovery

Walks the object tree via the device's metadata overlay and returns a
structured `SchemaTree` with both `by_id` and `by_path` lookups.

```python
with ThingSetTCP("192.0.2.1") as client:
    tree = client.discover_schema()
    print(f"{len(tree)} nodes, {len(tree.root)} top-level")
    print(tree.by_path["Metadata/rBoard"])
    # 0x0F03  Metadata/rBoard  (string)
    print(tree.by_id[0xF03].type)    # 'string'
```

## Async

The async API is the primary target for asyncio applications that can't
afford to block the event loop on ThingSet I/O.

### RPCs

```python
import asyncio
from python_thingset import AsyncThingSetTCP

async def main():
    async with AsyncThingSetTCP("192.0.2.1") as client:
        r = await client.get(0xF03)
        tree = await client.discover_schema()
        await client.update(0x509, True, parent_id=0x05)

asyncio.run(main())
```

Concurrent callers on the same client are internally serialised via an
`asyncio.Lock` (ThingSet has no wire-level request correlation), so other
coroutines in the loop keep running during an in-flight RPC.

### UDP report receiver

Receives broadcast publish/subscribe messages from ThingSet devices on the
subnet. Handles the 2-byte fragmentation framing and both report types:

- `0x1F` standard reports (source IP identifies the publisher)
- `0x1E` enhanced reports (carry the originating module's EUI-64, used when
  a gateway republishes CAN-side telemetry)

```python
import asyncio
from python_thingset import AsyncThingSetUDPReceiver

async def main():
    async with AsyncThingSetUDPReceiver(port=9002) as receiver:
        async for addr, report in receiver:
            # report is ThingSetReport(subset_id, values, eui)
            print(addr, report.subset_id, report.values)

asyncio.run(main())
```

Reassembly buffers are keyed per `(ip, port)`, so interleaved multi-frame
reports from multiple publishers don't corrupt each other. The receive queue
is bounded; on overflow the newest report is dropped rather than
back-pressuring the event loop.

### CAN report receiver

Receives publish frames from ThingSet devices on a CAN bus. Both shapes are
surfaced as `ThingSetReport`:

- **Single-frame report** (`type=0x2`): the 16-bit data ID is embedded in the
  CAN-ID; the payload is a bare CBOR-encoded value. Synthesised into a
  `ThingSetReport` with `subset_id=None` and a one-entry `values` map.
- **Multi-frame report** (`type=0x1`): chunks reassemble per-sender via
  `msg#` and `seq#` in the CAN-ID. Carries `subset_id`, plus optional
  `eui` for `0x1E` enhanced reports.

```python
import asyncio
from python_thingset import AsyncThingSetCANReportReceiver

async def main():
    async with AsyncThingSetCANReportReceiver(bus="vcan0", fd=True) as receiver:
        async for (source_addr, bus_name), report in receiver:
            print(source_addr, report.subset_id, report.values)

asyncio.run(main())
```

Reassembly buffers are keyed per source node address. On a sequence
mismatch within an in-flight message the receiver skips the frame without
advancing state — this matches the firmware-side reassembly behaviour and
lets the receiver latch onto one stream even when a publisher interleaves
two concurrent multi-frame reports with a shared `msg#`. `ThingSetReport`'s
`subset_id` is therefore typed `int | None` (was `int` in 0.2.x) since
single-frame reports don't carry one.

## Gateway forwarding

A TCP client can address a CAN-side module behind an IP↔CAN gateway (e.g. an
HMCU) by specifying the module's EUI-64. Every outgoing request is wrapped
in a `0x1C`-prefixed forward envelope; responses come back unwrapped, so the
caller API is unchanged.

```python
async with AsyncThingSetTCP(
    "192.0.2.1",
    target_eui=0xbadb1b0000000001,
) as client:
    r = await client.get(0xF03)            # module's own rBoard
    tree = await client.discover_schema()  # module's schema through the gateway
```

The same kwarg exists on the sync `ThingSetTCP`.

## CLI

Installed as `thingset` on your PATH.

```sh
# TCP
thingset get    f03        -i 192.0.2.1
thingset get    0F         -i 192.0.2.1              # whole group
thingset fetch  0          -i 192.0.2.1              # root children
thingset update 5 509 true -i 192.0.2.1
thingset exec   52         -i 192.0.2.1
thingset schema            -i 192.0.2.1

# CAN (target node 0x10)
thingset get    f03        -c vcan0 -t 10
thingset schema            -c vcan0 -t 10

# Through a gateway to the CAN-side module
thingset get    f03        -i 192.0.2.1 -e badb1b0000000001
thingset schema            -i 192.0.2.1 -e badb1b0000000001

# Serial
thingset get    Metadata/rBoard -p /dev/ttyACM0
thingset schema                 -p /dev/ttyACM0
```

### List values

`update` accepts a list either as multiple value tokens (one per element) or
as a single JSON-array literal. The two forms are equivalent:

```sh
# Binary transports — parent_id value_id <values...>
thingset update 7 70A 3.7 3.7 3.6   -i 192.0.2.1
thingset update 7 70A '[3.7,3.7,3.6]' -i 192.0.2.1
thingset update 7 70A 3.7 3.7 3.6   -c vcan0 -t 10

# Serial (text) — path <values...>
thingset update Module/aCells 3.7 3.7 3.6   -p /dev/ttyACM0
thingset update Module/aCells '[3.7,3.7,3.6]' -p /dev/ttyACM0
```

On binary transports the list goes on the wire as a CBOR array; float
elements are coerced to 32-bit so an embedded target sees `float[]`
(not `double[]`). On serial it becomes a JSON array inside the text
update payload.

Output is decorated with names and types when the firmware exposes them via
the metadata overlay:

```
$ thingset get f03 -i 192.0.2.1
0x85 (CONTENT)
  0x0F03  rBoard  (string): 'native_sim'

$ thingset fetch 0 -i 192.0.2.1
0x85 (CONTENT)
  0x0000  (group): [0xE DSM, 0xF Metadata, 0x67 xRebootDFU, ...]
```

## Examples

The `examples/` directory ships a UDP report sniffer with schema-aware
decoration, EUI filtering, and per-device `(IP, EUI)` schema caching that
transparently fetches through a gateway when a report carries a module EUI:

```sh
python examples/async_udp_sniffer.py --decorate -v
python examples/async_udp_sniffer.py --decorate --filter-eui badb1b0000000001
python examples/async_udp_sniffer.py --decorate \
    --record-fields examples/record_fields.example.json
```

A matching CAN sniffer prints publish frames as they arrive on a CAN
interface. `--decorate` fetches each source node's schema over ISO-TP in
the background and annotates printed IDs with their schema path:

```sh
python examples/async_can_sniffer.py -i vcan0 --source 10
python examples/async_can_sniffer.py -i vcan0 --source 10 -v --decorate
python examples/async_can_sniffer.py -i vcan0 --decorate \
    --record-fields examples/record_fields.example.json
```

## Development

```sh
# Install with dev dependencies
pip install -e '.[dev]'

# Run tests
pytest

# Lint
ruff check python_thingset/ tests/ examples/

# Build and publish a release
rm -rf dist/
python -m build
python -m twine upload --repository pypi dist/*
```

## License

Apache-2.0. See [LICENSE](LICENSE).
