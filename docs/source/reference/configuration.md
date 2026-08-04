# Design Configuration Files

Unless the design uses the API directly, each LibreLane-compatible design must
come with a configuration file. These configuration files can be written in one
of three grammars: JSON, YAML or Tcl.

Tcl offers more flexibility at the detriment of security, while YAML/JSON are
more straightforward at the cost of flexibility. While Tcl allows you to do all
manner of computation on your variables, YAML/JSON have a limited expression
engine that will be detailed later in this document. Nevertheless, for security
(and future-proofing), we recommend you use either the YAML/JSON format or write
Python scripts using the API.

The folder containing your `config.{tcl/yml/yaml/json}` is known as the **Design
Directory** -- though the design directory can also be set explicitly over the
command-line using `--design-dir`. The design directory is special in that paths
in the JSON configuration files can be resolved relative to this directory and
that in TCL configuration files, it can be referenced via the environment
variable `DESIGN_DIR`. This will be explained in detail in later sections.

```{note}
When using the API, you can provide the inputs directly as a Python dictionary,
enabling you to do complex pre-processing far beyond the capacity of either
JSON or Tcl files. You can still use `ref::` and such like JSON files though.
```

## JSON/YAML

The JSON and YAML files are simple key-value pairs.

<a name="scalars"></a>

The values can be scalars (strings, numbers, Booleans, and `null`s), lists or
dictionaries, subject to validation.

All JSON files must be ECMA404-compliant, i.e., pure JSON with no extensions
such as comments or the new elements introduced in [JSON5](https://json5.org/).

An minimal demonstrative configuration file would look as follows:

```json
{
  "DESIGN_NAME": "spm",
  "VERILOG_FILES": "dir::src/*.v",
  "CLOCK_PORT": "clk",
  "CLOCK_PERIOD": 100,
  "pdk::sky130A": {
    "MAX_FANOUT_CONSTRAINT": 6,
    "FP_CORE_UTIL": 40,
    "PL_TARGET_DENSITY_PCT": "expr::($FP_CORE_UTIL + 10.0)",
    "scl::sky130_fd_sc_hd": {
      "CLOCK_PERIOD": 15.0
    }
  }
}
```

All YAML files must conform to the
[YAML 1.2 specification](https://yaml.org/spec/1.2.2/). Scalar types are deduced
according to the
[YAML 1.2 Core Schema](https://yaml.org/spec/1.2.2/#103-core-schema).

An minimal demonstrative configuration file would look as follows:

```yaml
DESIGN_NAME: spm
VERILOG_FILES: dir::src/*.v
CLOCK_PORT: clk
CLOCK_PERIOD: 100
pdk::sky130A:
  MAX_FANOUT_CONSTRAINT: 6
  FP_CORE_UTIL: 40
  PL_TARGET_DENSITY_PCT: expr::($FP_CORE_UTIL + 10.0)
  scl::sky130_fd_sc_hd:
    CLOCK_PERIOD: 15.0
```

### Pre-processing

JSON/YAML files are pre-processed at runtime. Features include conditional
execution, a way to reference the design directory, other variables, and a basic
numeric expression engine.

#### Conditional Execution

The configuration files support conditional execution based on PDK or standard
cell library (or, by nesting as shown above, a combination thereof.) You can do
this using the `pdk::` or `scl::` key prefixes.

The value for this key would be a `dict` that is only evaluated if the PDK or
SCL matches those in the key, i.e., for `pdk::sky130A` as shown above, this
particular `dict` will be evaluated and its values used if and only if the PDK
is set to `sky130A`, meanwhile with say, `asap7`, it will not be evaluated.

The match is evaluated using
[`fnmatch`](https://docs.python.org/3.6/library/fnmatch.html), giving it limited
wildcard support: meaning that `pdk::sky130*` would match both `sky130A` and
`sky130B`.

A matching section overrides the values written beside it in the same file
wherever the block appears, so both of the following resolve `A` to 40 under
`sky130A` and to 4 under any other PDK:

```json
{
    "pdk::sky130A": {
        "A": 40
    },
    "A": 4
}

{
    "A": 4,
    "pdk::sky130A": {
        "A": 40
    }
}
```

A section only outranks the file that carried it. A value from a configuration
file given later on the command line, or from a `--config-override`, beats a
matching section in an earlier file. Where two matching sections are written in
the same file, the later one wins, so a `pdk::sky130*` block written after a
`pdk::sky130A` block overrides it.

It is worth nothing that the final resolved configuration would have the symbol
in the parent object with no trace left of the conditionally-executed, dict
i.e., the second example with the sky130A PDK simply becomes:

```json
{
  "A": 40
}
```

#### Variable Reference

If a string's value starts with `ref::`, you can interpolate exactly one
**string** variable at the beginning of your string.

The order of declarations does not matter: references are resolved as a
dependency graph, so a variable may reference one declared later in the file.
The only ordering error is a cycle, which is rejected with the cycle's path.

```json
{
    "A": "ref::$B",
    "B": "vdd gnd"
}

{
    "B": "vdd gnd",
    "A": "ref::$B"
}
```

> These two configurations are equivalent: in both, A resolves to "vdd gnd".

Do note that unlike Tcl config files, environment variables are not exposed to
`config.{yml/yaml/json}` by default. You only have access to four specific
variables: `DESIGN_DIR`, `PDK`, `PDKPATH`, and `STD_CELL_LIBRARY`.

If the files you choose lie **inside** the design directory, a different prefix,
`refg::`, supports non-recursive globs, i.e., you can use an asterisk as a
wildcard to pick multiple files in a specific folder.

```{note}
`refg::` will always return an array, even if only one element was found, for
consistency. If no elements were found, the glob string is returned verbatim as
a single element in array.
```

As shown below, `refg::$DESIGN_DIR/src/*.v` would find all files ending with
`.v` in the `src` folder inside the design directory.

```json
{
  "VERILOG_FILES": "refg::$DESIGN_DIR/src/*.v"
}
```

There are some shorthands for the exposed default variables:

* `dir::` is equivalent to `refg::$DESIGN_DIR/`
* `pdk_dir::` is equivalent to `refg::$PDK_ROOT/$PDK`

#### Expression Engine

By adding `expr::` to the beginning of a string, you can write basic infix
mathematical expressions. Binary operators supported are `**`, `*`, `/`, `+`,
and `-`, while operands can be any floating-point value, and previously
evaluated numeric variables prefixed with a dollar sign. Unary operators are not
supported, though negative numbers with the - sign stuck to them are.
Parentheses (`()`) are also supported to prioritize certain operations.

Your expressions must return exactly one value: multiple expressions in the same
`expr::`-prefixed value are considered invalid and so are empty expressions.

As with variable referencing, the order of declarations does not matter:
operands are resolved as a dependency graph, and only a cycle is an error.

```json
{
    "A": "expr::$B * 2",
    "B": 4
}

{
    "B": 4,
    "A": "expr::$B * 2"
}
```

> These two configurations are equivalent: in both, A evaluates to 8.

You can also simply reference another number using this prefix:

```json
{
  "A": 10,
  "B": "expr::$A"
}
```

> In this example, B will simply hold the value of A.

#### F-lists

Industry IP blocks, academic IP and tools such as
[Bender](https://github.com/pulp-platform/bender) emit a `*.f` file, an ad-hoc
standard listing the files that make up a design along with its include
directories and preprocessor defines. These are written to be passed straight
to a command-line tool such as Verilator, so LibreLane has to unpack one before
it can use it.

Name your F-lists in `VERILOG_FLIST_FILES`, which takes a list. Every entry may
use any of the preprocessor directives above.

```yaml
DESIGN_NAME: cool_core
VERILOG_FLIST_FILES:
  - dir::rtl/ip/super_core_64/supercore.f
  - refg::$VENDOR_DIR/vendor/gigabyte_sram.f
```

Two directives are understood inside an F-list, and every other line is taken
to be the path of a source file.

`+incdir+DIRECTORY`
: Appended to `VERILOG_INCLUDE_DIRS`.

`+define+MACRO`
: Appended to `VERILOG_DEFINES`.

The preprocessor reads each F-list, appends its contents to
`VERILOG_INCLUDE_DIRS`, `VERILOG_DEFINES` and `VERILOG_FILES`, then drops
`VERILOG_FLIST_FILES` from the configuration. No step sees it.

Only (System)Verilog F-lists are supported. VHDL is not.

## Command-line overrides

`--config-override KEY=VALUE` (`-c`) sets one variable for one run. It is
layered after every configuration file, so it beats all of them, including a
matching `pdk::`/`scl::` section one of them wrote. It may be given more than
once.

The command line is one source, so it has one grammar: JSON, for values that
need structure. The variable's declared type decides only whether the text is
parsed as a JSON document or taken as written:

* A **scalar** variable -- a string, a number, a Boolean, a path, an
  enumeration -- takes the text exactly as written. Nothing needs quoting for
  LibreLane's sake, only for your shell's.

  ```console
  $ librelane -c CLOCK_PERIOD=15 -c 'DESIGN_NAME=my design' config.yaml
  ```

* A **list, tuple or dictionary** variable takes a JSON document, which is
  what `--config-override` has always documented itself to take.

  ```console
  $ librelane -c 'TOOLS={"lvs": "netgen"}' -c 'CELL_PAD_EXCLUDE=["*decap*"]' config.yaml
  ```

  A value that is not valid JSON is an error naming the variable and the
  grammar. There is no second grammar to fall back to: a space-separated Tcl
  list, which earlier versions accepted here, is now rejected.

* A variable that declares **both** -- `CLOCK_PORT` and `CLOCK_NET` are
  `None | str | list[str]`, taking one clock port or several -- is the one
  case the declared type does not settle, so the text decides. A value whose
  first non-blank character is `[` or `{` is a document; anything else is the
  string.

  ```console
  $ librelane -c 'CLOCK_PORT=clk' -c 'CLOCK_NET=["clk", "clk_i"]' config.yaml
  ```

  The bracket commits the value: `CLOCK_PORT=["clk"` is a JSON error naming
  the variable, and never a clock port whose name is the literal text
  `["clk"`.

The [pre-processing](#pre-processing) prefixes apply to an override as they do
to a value in a JSON or YAML file, and they run before the JSON above, so a
prefix that produces a list satisfies a list variable without any JSON at all:

```console
$ librelane -c 'VERILOG_FILES=dir::src/*.v' config.yaml
```

A prefix written **inside** a JSON array is not expanded: prefixes are
recognized only at the start of a whole value, and a value that begins with
`[` begins with JSON, not a prefix. Write the paths out, or use a prefix for
the whole value as above.

## How a value's syntax is decided

Which grammar a string is read in is a property of the source that wrote it and
never of the variable it was written for. A variable's declared type says what
the value has to end up as; the source says how it was written.

| Source | A string for a list or dictionary variable |
| --- | --- |
| PDK `config.tcl` | A Tcl word list: `a 1 b 2` is a two-entry dictionary, `p q r` a three-element list. |
| `--config-override` | A JSON document, as above. |
| `.json` or `.yaml` file, or an API mapping | An error. These grammars carry a list as a list, so a string was meant as a string. |

A variable that declares a string *and* a list has a row of its own, because
the string reading is always available and so nothing can be rejected:

| Source | A string for a `str`-or-list variable |
| --- | --- |
| PDK `config.tcl` | A string. Every Tcl value is a word list, so `clk_a clk_b` cannot be told from a one-word list, and the declared string wins. Tcl cannot set the list reading. |
| `--config-override` | A JSON array when the text starts with `[`, and the string otherwise. A `{` also begins a document, so `CLOCK_PORT={"a": 1}` is an error and not a clock port with a curly brace in its name: no member of the union takes a JSON object. |
| `.json` or `.yaml` file, or an API mapping | Whichever was written: a string is a string and an array is a list. |

The last source to write a key decides, so a `--config-override` on a key the
PDK also set is read as JSON, and a design file that overrides a PDK key is
held to its own grammar.

A PDK's `config.tcl` is the only Tcl source. Design configurations used to be
readable as Tcl too -- either as a `.tcl` file, or as any document declaring
`meta.version` 1, which was the default for a `.json` file with no `meta` key.
Both are gone: a design file means what it says, and `.json` and `.yaml` are
read by identical rules.
