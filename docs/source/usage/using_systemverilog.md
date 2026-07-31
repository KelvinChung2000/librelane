# Using SystemVerilog

Yosys' built-in Verilog frontend understands a useful subset of SystemVerilog,
but not all of it. For designs it cannot read, LibreLane ships
[yosys-slang](https://github.com/povik/yosys-slang), a frontend built on
[slang](https://sv-lang.com) with much fuller SystemVerilog support.

It is not enabled by default, because it is not as battle-tested as the
built-in frontend. Turn it on with {var}`Yosys.Synthesis::USE_SLANG`:

::::{tab-set}

:::{tab-item} JSON
```json
{
    "USE_SLANG": true
}
```
:::

:::{tab-item} YAML
```yaml
USE_SLANG: true
```
:::

::::

Your files still go in `VERILOG_FILES`, and the flow is still `Classic`. Only
the frontend changes.

## Passing options to slang

{var}`Yosys.Synthesis::SLANG_ARGUMENTS` forwards arguments verbatim to the
frontend, for the many slang options that have no variable of their own. The
[slang command-line reference](https://sv-lang.com/command-line-ref.html) lists
them.

::::{tab-set}

:::{tab-item} JSON
```json
{
    "USE_SLANG": true,
    "SLANG_ARGUMENTS": ["--allow-use-before-declare"]
}
```
:::

:::{tab-item} YAML
```yaml
USE_SLANG: true
SLANG_ARGUMENTS:
  - --allow-use-before-declare
```
:::

::::

These arguments are passed at your own risk. LibreLane does not check them, and
an option that changes how the frontend elaborates the design can change the
netlist in ways the rest of the flow does not expect.

## A note on Synlig and Surelog

Earlier versions of LibreLane, and OpenLane 2 before it, used
[Synlig](https://github.com/chipsalliance/synlig) and
[Surelog](https://github.com/chipsalliance/surelog) for SystemVerilog. Both have
been removed and replaced by yosys-slang. There is no `read_systemverilog`
command and no Synlig plugin in current LibreLane.

The old `USE_SYNLIG` variable is still accepted as a deprecated name for
`USE_SLANG`, so an existing configuration keeps working, but it selects
yosys-slang rather than Synlig.
