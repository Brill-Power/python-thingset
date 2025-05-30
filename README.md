# Python ThingSet

## To use from Python

### To install

`pip install python-thingset`

### To get a value

```python
from python_thingset import ThingSet

with ThingSet(backend="can", can_bus="vcan0") as ts:
    response = ts.get(0xF03, 0x01)

    print(response)                             # 0x85 (CONTENT): native_posix
    print(f"0x{response.status_code:02X}")      # 0x85
    print(response.status_string)               # CONTENT
    print(response.data)                        # native_posix

    for v in response.values:
        print(v)                                # Build/rBoard (0xF03): native_posix
        print(v.name, f"0x{v.id:02X}", v.value) # Build/rBoard 0xF03 native_posix
```

### To fetch multiple values

```python
from python_thingset import ThingSet

with ThingSet(backend="can", can_bus="vcan0") as ts:
    response = ts.fetch(0xF, [0xF03, 0xF01], 0x01)

    print(response)                             # 0x85 (CONTENT): ['native_posix', '947c30f8']
    print(f"0x{response.status_code:02X}")      # 0x85
    print(response.status_string)               # CONTENT
    print(response.data)                        # ['native_posix', '947c30f8']
```

### To fetch all child IDs of a parent

```python
from python_thingset import ThingSet

with ThingSet(backend="can", can_bus="vcan0") as ts:
    response = ts.fetch(0xF, [], 0x01)

    print(response)                             # 0x85 (CONTENT): [3841, 3842, 3843, 3845, 3849]
    print(f"0x{response.status_code:02X}")      # 0x85
    print(response.status_string)               # CONTENT
    print(response.data)                        # [3841, 3842, 3843, 3845, 3849]
```

### To execute a function

```python
from python_thingset import ThingSet

with ThingSet(backend="can", can_bus="vcan0") as ts:
    response = ts.exec(0x20, ["some-text"], 0x1)

    print(response)                             # 0x84 (CHANGED): 0
    print(f"0x{response.status_code:02X}")      # 0x84
    print(response.status_string)               # CHANGED
    print(response.data)                        # 0
```

### To update a value

```python
from python_thingset import ThingSet

with ThingSet(backend="can", can_bus="vcan0") as ts:
    response = ts.update(0x4F, 1, 0x1, 0x0)

    print(response)                             # 0x84 (CHANGED): 0
    print(f"0x{response.status_code:02X}")      # 0x84
    print(response.status_string)               # CHANGED
    print(response.data)                        # 0
```

## To use from terminal

### Serial examples

```
thingset get SomeGroup -p /dev/pts/5
thingset get SomeGroup/rOneValue -p /dev/pts/5

thingset fetch SomeGroup -p /dev/pts/5
thingset fetch SomeGroup rOneValue rAnotherValue -p /dev/pts/5

thingset update sSomePersistedValue 3 -p /dev/pts/5
thingset update AnotherGroup/sPersistedValue 3 -p /dev/pts/5

thingset exec xSomeFunction aFunctionArgument -p /dev/pts/5
thingset exec AnotherGroup/xAnotherFunction -p /dev/pts/5
thingset exec AnotherGroup/xYetAnotherFunction 1.2 3.4 5.6 -p /dev/pts/5

thingset schema -p /dev/pts/5
thingset schema SomeGroup -p /dev/pts/5
thingset schema "" -p /dev/pts/5
```

### CAN examples

```
thingset get f -c vcan0 -t 2f
thingset get f03 -c vcan0 -t 2f

thingset fetch f -c vcan0 -t 2f
thingset fetch f f01 f02 -c vcan0 -t 2f

thingset update 0 6f 3 -c vcan0 -t 2f

thingset exec 44 aFunctionArgument -c vcan0 -t 2f
thingset exec 55 -c vcan0 -t 2f
thingset exec 66 1.2 2.3 3.55 -c vcan0 -t 2f

thingset schema -c vcan0 -t 2f
thingset schema f -c vcan0 -t 2f
```

### Socket examples

```
thingset get f -i 127.0.0.1
thingset get f03 -i 127.0.0.1

thingset fetch f -i 127.0.0.1
thingset fetch f f01 f02 -i 127.0.0.1

thingset update 0 6f 3 -i 127.0.0.1

thingset exec 44 aFunctionArgument -i 127.0.0.1
thingset exec 55 -i 127.0.0.1
thingset exec 66 1.2 2.3 3.55 -i 127.0.0.1

thingset schema -i 127.0.0.1
thingset schema f -i 127.0.0.1
```

## To build
```
rm -rf dist/
python -m build
python -m twine upload --repository pypi dist/*
```