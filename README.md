# synx

**A command-line syntax and reference tool for Linux and cybersecurity utilities.**

`synx` is a documentation tool. It keeps a local YAML database of tools — their
common commands, syntax and a one-line description each — and prints it in a
readable, colourised form. It never runs, launches or automates anything: it only
shows you what the syntax looks like, so you can copy it and run it yourself in an
authorised environment.

```console
$ synx nxc

nxc
────────────────────────────────────────

Network service enumeration and administration tool for Windows networks. NetExec is the
maintained successor of CrackMapExec: it speaks SMB, LDAP, WinRM, RDP, MSSQL, SSH and
other protocols with a single command line and reports what each account or host exposes.

Category: active-directory
Aliases: netexec, crackmapexec, cme
Homepage: https://github.com/Orange-Cyberdefense/NetExec

SMB
  Syntax:
    nxc smb <target> -d <domain> -u <username> -p <password>

  Description:
    Connects to an SMB service using the supplied credentials and reports the signing
    state, OS build and name of the target.

  Tags: smb, credentials

WinRM
  Syntax:
    nxc winrm <target> -d <domain> -u <username> -p <password>

  Description:
    Connects to a Windows host through WinRM using the supplied credentials and reports
    the remote user privileges.

  Tags: winrm, credentials
...
```

---

## Features

- **Instant syntax reference** — `synx <tool>` prints every documented command of a
  tool, `synx <tool> <command>` prints just one.
- **YAML-driven database** — the tool list is never hard-coded. Drop a new
  `tools/mytool.yaml` file in and `synx mytool` works immediately.
- **Full-text search** — `--search` looks through tool names, aliases, descriptions,
  categories, command names, syntax, tags and command descriptions.
- **Fuzzy suggestions** — `synx ceripy` answers with *"Did you mean: certipy"*.
- **Safe by design** — no shell, no `subprocess`, no exploitation. Placeholders only:
  `<target>`, `<username>`, `<password>`, `<domain>`, `<dc-ip>`, `<port>`, `<interface>`.
- **Graceful failure** — a malformed YAML file is skipped with a precise error message
  instead of crashing the tool.
- **Colourful, scriptable output** — `rich` for humans, `--json` for scripts.
- **Linux-native** — no third-party CLI framework; `argparse` + `rich` + `PyYAML`.

## Requirements

- Python 3.10 or newer
- Linux (also runs on macOS and WSL)

## Installation

From a checkout:

```bash
pip install .
```

For development, install in editable mode with the test and lint extras:

```bash
pip install -e ".[dev]"
```

The virtualenv route, if you prefer one:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

`pip install .` creates a `synx` console script, so the tool works from any directory:

```bash
cd /tmp && synx nxc smb
```

Manual install without packaging still works:

```bash
pip install -r requirements.txt
python3 -m synx nxc          # from the project directory
```

## Usage

```text
synx [-h] [-s [KEYWORD]] [-l] [-i] [--reload] [--db-path DIR] [--context N] [--json]
     [--no-color] [--width N] [-v] [-V]
     [tool] [command]
```

| Invocation | Result |
| --- | --- |
| `synx` | prints the help screen |
| `synx --help`, `synx -h` | prints the help screen |
| `synx --version`, `synx -V` | prints the version |
| `synx --list`, `synx -l` | lists every available tool |
| `synx --info`, `synx -i` | application and database information |
| `synx --reload` | re-reads the database from disk and reports what was loaded |
| `synx <tool>` | every documented command of a tool |
| `synx <tool> <command>` | a single command of a tool |
| `synx --search <keyword>` | searches the whole database |
| `synx <tool> --search <keyword>` | searches inside one tool |
| `synx --list --json` | machine-readable output |

### List the tools

```console
$ synx --list

   Tool                  Category              Commands     Description
 ──────────────────────────────────────────────────────────────────────────────────────
   ad-miner              active-directory            12     Audits a BloodHound graph by running a large set of Cypher
                                                             queries against the Neo4j database and turning the answers
                                                             into an HTML report...
   bloodhound-python     active-directory            12     Python data collector for BloodHound.
   bloodyad              active-directory            14     Active Directory privilege escalation swiss army knife that
                                                             issues targeted LDAP calls against a domain controller.
   certipy               active-directory            11     Tool and Python library for enumerating and analysing
                                                             Active Directory Certificate Services (AD CS)...
   coercer               active-directory            12     Makes a Windows server authenticate to an arbitrary machine by
                                                             calling its remote procedure calls.
   evil-winrm            remote-access                6     Windows Remote Management (WinRM) shell in the style of
                                                             Evil-PS1.
   impacket              post-exploitation           14     Collection of Python classes and scripts for working with
                                                             network protocols, most of them SMB, LDAP...
   kerbrute              credential-attacks          13     Enumerates valid Active Directory accounts and tests
                                                             credentials over the Kerberos pre-authentication exchange.
   ldapdomaindump        active-directory            13     Collects the users, groups, computers, policies and trusts of
                                                             a directory over LDAP and writes them as HTML, JSON and
                                                             greppable tables.
   nmap                  network                      9     Network exploration and port scanning utility.
   nxc                   active-directory            17     Network service enumeration and administration tool for
                                                             Windows networks.
   petitpotam            active-directory            11     Coerces NTLM authentication from a Windows host by calling a
                                                             printer service RPC function on it.
   plumhound             active-directory            11     Reporting engine for BloodHound.
   pypykatz              credential-dumping           11     Mimikatz implemented in pure Python, so it runs on any
                                                             platform that has Python 3.7 or newer rather than only on
                                                             Windows.
   responder             network                      5     Listener for LLMNR, NBT-NS and MDNS name resolution requests.
   rubeus                kerberos                    21     Kerberos abuse toolkit for Windows that requests, renews,
                                                             forges and exports tickets.
   sharphound            active-directory            11     C# data collector for BloodHound that runs on a Windows host.
   smbmap                smb                         16     Enumerates the SMB shares of a Windows or Samba host or of a
                                                             whole domain.

18 tool(s), 219 command(s) available.
```

### One tool, one command

```console
$ synx nxc smb

nxc
────────────────────────────────────────

SMB
  Syntax:
    nxc smb <target> -d <domain> -u <username> -p <password>

  Description:
    Connects to an SMB service using the supplied credentials and reports the signing
    state, OS build and name of the target.

  Example:
    nxc smb 10.0.0.5 -d CORP -u 'user' -p 'password'

  Tags: smb, credentials

Command SMB of 17 documented for nxc. Run 'synx nxc' for all commands.
```

Command names are matched case-insensitively, by the leading binary of the syntax
string, by tag and by partial name: `synx nxc SMB`, `synx nxc smb` and
`synx nxc nxc-smb.py` all work. Aliases resolve too — `synx netexec` shows `nxc`.

### Search

```console
$ synx --search relay

Search results for 'relay'
3 tool(s), 5 command(s) matched.

matches
├── coercer
│   └── Coerce
│       ├── coercer coerce -t <dc-ip> -u <username> -p <password> -l <listener-ip>
│       ├── Calls the vulnerable RPC functions one by one so the target authenticates to the 
│       │   listener, for example to feed ntlmrelayx or Responder.
│       └── matched: tags
├── impacket
│   └── impacket-ntlmrelayx
│       ├── impacket-ntlmrelayx -target <dc-ip> -smb2support
│       ├── Listens for incoming SMB traffic and relays the captured authentication to a chosen 
│       │   protocol, optionally with --remove-mic.
│       └── matched: tags
└── petitpotam
    ├── Coerces NTLM authentication from a Windows host by calling a printer service RPC function on
    │   it.
    │   └── matched: tool description
    ├── Coerce authentication
    │   ├── petitpotam.py -target <dc-ip> <path>
    │   ├── Triggers the target to authenticate to the UNC path, which must point at your listener.
    │   └── matched: tags
    ├── Named host
    │   ├── petitpotam.py -target <host> <path>
    │   ├── Uses a NetBIOS or fully qualified name instead of an address, which avoids a null 
    │   │   session.
    │   └── matched: tags
    └── Specific method
        ├── petitpotam.py -debug -method AddUsersToFile <dc-ip> <path>
        ├── Calls one named coercion method instead of a random one; the debug flag shows which 
        │   method was chosen.
        └── matched: tags
```

When a whole tool matches but none of its individual commands do, `synx` shows a few
of its commands for context. Use `--context N` to change how many (default 3, `0`
disables context) and `--search <keyword> --json` for scripting:

```console
$ synx --search certificate --json | jq '.results[0].command'
{
  "tool": "certipy",
  "command": "cacerts",
  "syntax": "certipy cacerts -u <username> -p <password> -dc-ip <dc-ip> -target <fqdn>"
}
```

### Fuzzy suggestions

```console
$ synx ceripy

Tool 'ceripy' was not found.

Did you mean:
  certipy
  certipy-ad
  certipy.py

Run 'synx --list' to see every tool, or 'synx --search ceripy' to search the database.
```

The same happens for a mistyped command:

```console
$ synx nxc sm

Command 'sm' was not found in tool 'nxc'.

Did you mean:
  SMB

Run 'synx nxc' to list the 17 documented command(s), or 'synx --search sm' to search the
database.
```

### Application and database information

```console
$ synx --info

   Application     synx 1.0.0
   Purpose         Command-line syntax and reference for Linux and cybersecurity tools.
   Mode            Read-only reference. synx never executes commands.
   Python          3.12.3
   Package         /home/user/.local/lib/python3.12/site-packages/synx
   Database        18 tool(s), 219 command(s)

Database locations (lowest precedence first)

     #     Kind       Path                                            Tools     Files
 ──────────────────────────────────────────────────────────────────────────────────────
   1 *     bundled    /home/user/.local/lib/python3.12/site-packages/synx/_bundled_tools  18      18
   2 *     user       /home/user/.local/share/synx/tools                                   0       0
```

Directories marked with `*` are in use. `--info --json` returns the same data as JSON.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | tool, command or search term not found |
| 2 | invalid usage (argparse) |
| 3 | the database could not be loaded |

### Options

| Option | Description |
| --- | --- |
| `-s`, `--search [KEYWORD]` | search the database; with a tool name, search only that tool |
| `-l`, `--list` | list every available tool |
| `-i`, `--info` | application and database information |
| `--reload` | re-read the YAML files and report what was loaded |
| `--db-path DIR` | load only these directories (repeatable) |
| `--context N` | commands shown under a matched tool in search results (default 3) |
| `--json` | machine-readable output instead of tables |
| `--no-color` | disable ANSI styling |
| `--width N` | force the output width in columns |
| `-v`, `--verbose` | report skipped, duplicate or incomplete database files |
| `-V`, `--version` | print the version |

## The YAML database

Each file in `tools/` describes exactly one tool.

```yaml
name: nxc                        # required, matches the file name
aliases:                         # optional, alternative names users may type
  - netexec
  - crackmapexec
category: active-directory       # optional, shown in --list
homepage: https://github.com/Orange-Cyberdefense/NetExec   # optional
description: >-                  # optional, one or two sentences
  Network service enumeration and administration tool for Windows networks.
notes: >-                        # optional, caveats about the tool as a whole
  Flags differ between releases; confirm them with 'nxc <protocol> --help'.
commands:                        # required, list of commands
  - name: SMB                    # required, how the user types the command
    syntax: nxc smb <target> -d <domain> -u <username> -p <password>   # required
    description: >-              # optional but recommended
      Connects to an SMB service using the supplied credentials.
    tags: [smb, credentials]     # optional, searchable keywords
    notes: Requires SMB 445.     # optional, per-command caveat
    version: nxc 0.3 and later   # optional, when the syntax applies
    example: nxc smb 10.0.0.5 -d CORP -u 'user' -p 'password'   # optional
```

### Field reference

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | string | yes | must match the file name and be unique |
| `description` | string | no | first sentence is used in `--list` |
| `aliases` | list of strings | no | alternative tool names |
| `category` | string | no | grouping shown in `--list` |
| `homepage` | string | no | project URL |
| `notes` | string | no | tool-wide caveat |
| `commands` | list | yes | may be empty, but a warning is reported |
| `commands[].name` | string | yes | unique within the tool |
| `commands[].syntax` | string | yes | use `<placeholders>`, never real hosts or credentials |
| `commands[].description` | string | no | one or two factual sentences |
| `commands[].tags` | list of strings | no | searchable keywords |
| `commands[].notes` | string | no | per-command caveat |
| `commands[].version` | string | no | marks version-specific syntax |
| `commands[].example` | string | no | a filled-in example using reserved addresses |

Use `python3 -c "import yaml, json, sys; print(json.dumps(yaml.safe_load(open(sys.argv[1])), indent=2))" tools/mytool.yaml`
to check a file parses before relying on it.

## Adding a new tool

1. Create `tools/mytool.yaml` (or `tools/mytool.yml`) with the format above.
2. Run `synx mytool`.

That is the whole process — no Python changes, no registration step. `synx` reads the
files on every run, so the new entry is available immediately.

`--db-path` and `SYNX_DB_PATH` make it easy to keep your own definitions separate from
the bundled ones:

```bash
mkdir -p ~/.local/share/synx/tools
cp mytool.yaml ~/.local/share/synx/tools/
synx --info            # the 'user' directory is picked up automatically
synx --list | grep mytool
```

Directories are merged with the lowest precedence first, and a tool defined in a later
directory overrides one with the same name in an earlier one:

1. `bundled` — `synx/_bundled_tools` inside the installed package
2. `user` — `${XDG_DATA_HOME:-~/.local/share}/synx/tools`
3. `source` — `tools/` next to a source checkout
4. `explicit` — only when you pass `--db-path DIR` or set `SYNX_DB_PATH`

If a file cannot be parsed, `synx` reports it and keeps going:

```console
$ synx --list -v

  Level   File                    Problem
 ───────────────────────────────────────────────────────────────────────────
  error   /home/user/tools/x.yaml  invalid YAML: while parsing a flow sequence...

1 file(s) produced warnings or were skipped (run with --verbose for details).
```

## Safety

`synx` is a documentation and reference tool:

- It **never** executes, spawns, schedules or automates the syntax it prints. The
  package does not import `subprocess`, `pty`, `socket` or `os.system` — the test
  suite asserts this, and it also asserts the YAML is read with `yaml.safe_load`.
- It never brute-forces, exploits, persists or touches a target. It has no network
  code at all.
- The shipped database uses placeholders (`<target>`, `<username>`, `<password>`,
  `<domain>`, `<dc-ip>`, `<port>`, `<interface>`) rather than real targets or
  credentials; the tests enforce that.
- Descriptions are factual and version-specific syntax is marked with a `Version:` or
  `Notes:` field, so nothing is presented as a guarantee for a release you may not be
  running.

Only use the documented syntax on systems you own or are explicitly authorised to
test.

## Project structure

```text
synx/
├── synx/
│   ├── __init__.py      # version and lazy public API
│   ├── __main__.py      # python -m synx
│   ├── cli.py           # argparse CLI, exit codes, orchestration
│   ├── database.py      # YAML discovery, loading, merging, lookups
│   ├── display.py       # all rich rendering
│   ├── models.py        # Tool/Command dataclasses and schema validation
│   ├── search.py        # scoring, full-text search, fuzzy suggestions
│   └── py.typed         # PEP 561 marker
├── tools/               # the YAML database (one file per tool)
├── tests/               # pytest suite
├── pyproject.toml
├── requirements.txt
└── README.md
```

The three layers are independent: `models`/`database` know nothing about output,
`display` knows nothing about the filesystem, and `cli` only wires them together.
That is what makes the CLI testable with a temporary database directory and a
`StringIO` console.

### Shipped tools

`nxc`, `certipy`, `impacket`, `evil-winrm`, `bloodhound-python`, `responder`, `nmap`.

## Development

```bash
git clone <your fork>
cd synx
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Useful commands:

```bash
python3 -m synx --info                     # run the working copy
python3 -m synx nxc --width 100           # check the layout at a fixed width
python3 -m pytest -q                      # run the tests
python3 -m pytest --cov=synx --cov-report=term-missing
python3 -m ruff check synx tests           # lint
python3 -m ruff format --check synx tests  # formatting check (optional)
python3 -m mypy synx                       # type check
python3 -m build                          # build sdist and wheel into dist/
```

The code follows PEP 8 with a 100-character line limit, is fully type hinted
(`py.typed` is shipped), and keeps public functions small and documented.

## Testing

The suite is pytest-based and needs no network access:

```bash
pip install -e ".[dev]"
python3 -m pytest            # 288 tests
python3 -m pytest -v         # per-test names
python3 -m pytest tests/test_database.py::TestMalformedInput
```

| File | Covers |
| --- | --- |
| `tests/test_models.py` | schema validation, command lookup, normalisation |
| `tests/test_database.py` | loading, merging, overrides, malformed YAML, path resolution |
| `tests/test_search.py` | scoring per field, ranking, multi-token search, fuzzy suggestions |
| `tests/test_display.py` | layout of every rendered element, syntax highlighting, JSON output |
| `tests/test_cli.py` | every documented invocation, exit codes, output text |
| `tests/test_shipped_database.py` | the shipped YAML stays valid, unique and placeholder-only |
| `tests/test_safety.py` | no execution primitives, `yaml.safe_load`, no side effects |
| `tests/test_packaging.py` | entry point, version, dependencies, bundled data |

Fixtures build a temporary database from `tests/data.py`, so tests never depend on the
contents of the shipped `tools/` directory (except where that is exactly what is being
tested).

## License

MIT — see [LICENSE](LICENSE).

## Disclaimer

`synx` documents the published syntax of third-party tools. It is not affiliated with
the projects it documents, and the accuracy of any entry depends on the version you
have installed. Always confirm a flag with the tool's own `--help` before use.
