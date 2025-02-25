# Getting started

### Compatibility

`python_thingset` currently only supports Ubuntu `>=22.0.4` and Python `>=3.10`.

### Installation

Simply include in `requirements.txt`:

```
python_thingset @ git+ssh://git@github.com/Brill-Power/python-thingset.git
```

If you wish to work from a specific branch, for example a branch called `fix-package-imports`, append `@fix-package-imports` to the above line in `requirements.txt`, as follows:

```
python_thingset @ git+ssh://git@github.com/Brill-Power/python-thingset.git@fix-package-imports
```

### Note

Consider creating a virtual environment so as to avoid breaking system package versions for other software packages on your machine.
