# Command-line usage

### Compatibility

`python_thingset` currently only supports Ubuntu `>=22.0.4` and Python `>=3.10`.

### Installation

```
1. Clone this repo
2. cd python_thingset
3. pip install -r requirements.txt
3. chmod +x thingset
4. export PATH="$PATH:$(pwd)"
```

This will clone the latest version of the repository, make the file `thingset` executable and then add the directory containing the file `thingset` to your `PATH` such that it will be executable from any directory.

### Serial examples:

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

### CAN examples:

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
