# Python usage

### To get a value:
```
from python_thingset.thingset import ThingSet

with ThingSet() as ts:
    """ node_id=0x36, value_id=0xF03 """
    response = ts.get(0x36, 0xF03)

    print(response)
    print(f"0x{response.status_code:02X}")
    print(response.status_string)
    print(response.data)

    for v in response.values:
        print(v)
        print(v.name, f"0x{v.id:02X}", v.value)
```

### To fetch multiple values:
```
from python_thingset.thingset import ThingSet

with ThingSet() as ts:
    """ node_id=0x36, parent_id=0xF, child_ids=0xF03, 0xF02, 0xF01 """
    response = ts.fetch(0x36, 0xF, [0xF03, 0xF02, 0xF01])

    print(response)
    print(f"0x{response.status_code:02X}")
    print(response.status_string)
    print(response.data)

    for v in response.values:
        print(v)
        print(v.name, f"0x{v.id:02X}", v.value)
```

### To fetch all child IDs of a parent:
```
from python_thingset.thingset import ThingSet

with ThingSet() as ts:
    """ node_id=0x36, parent_id=0xF, empty list invokes fetch of child IDs """
    response = ts.fetch(0x36, 0xF, [])

    print(response)
    print(f"0x{response.status_code:02X}")
    print(response.status_string)
    print(response.data)

    if response.values is not None:
        for v in response.values:
            print(v)
            print(v.name, f"0x{v.id:02X}", [f"0x{i:02X}" for i in v.value])
```

### To execute a function:
```
from python_thingset.thingset import ThingSet

with ThingSet() as ts:
    """ node_id=0x36, value_id=0x20, value_args="some-text" """
    response = ts.exec(0x36, 0x20, ["some-text"])

    print(response)
    print(f"0x{response.status_code:02X}")
    print(response.status_string)
    print(response.data)
```

### To update a value:
```
from python_thingset.thingset import ThingSet

with ThingSet() as ts:
    """ node_id=0x36, parent_id=0x00, value_id=0x6F, value=21 """
    response = ts.update(0x36, 0x00, 0x6F, 21)

    print(response)
    print(f"0x{response.status_code:02X}")
    print(response.status_string)
    print(response.data)
```
