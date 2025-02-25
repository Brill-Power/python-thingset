# Python ThingSet

## To use from Python

#### To install:

Simply include in your `requirements.txt` (or equivalent file) as:

```
python_thingset @ git+ssh://git@github.com:Brill-Power/python-thingset.git
```

If you wish to work from a specific branch, for example a branch called `fix-package-imports`, append `@fix-package-imports` to the above line in `requirements.txt`, as follows:

```
python_thingset @ git+ssh://git@github.com:Brill-Power/python-thingset.git@fix-package-imports
```

#### To get a value:
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

#### To fetch multiple values:
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

#### To fetch all child IDs of a parent:
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

#### To execute a function:
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

#### To update a value:
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

## To use from terminal

#### To install:

```
1. git clone git@github.com:Brill-Power/python-thingset.git
2. cd python_thingset
3. pip install -r requirements.txt
3. chmod +x thingset
4. export PATH="$PATH:$(pwd)"
```

This will clone the latest version of the repository, make the file `thingset` executable and then add the directory containing the file `thingset` to your `PATH` such that it will be executable from any directory.

#### Serial examples:

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

#### CAN examples:

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