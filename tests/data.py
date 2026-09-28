"""Sample YAML documents used by the test suite."""

from __future__ import annotations

from pathlib import Path

NXC_YAML = """\
name: nxc
aliases: [netexec, crackmapexec]
category: active-directory
description: Network service enumeration and administration tool.
notes: Confirm flags with 'nxc --help' for your installed version.
commands:
  - name: SMB
    syntax: nxc smb <target> -d <domain> -u <username> -p <password>
    description: Connects to an SMB service using the supplied credentials.
    tags: [smb, credentials]
  - name: WinRM
    syntax: nxc winrm <target> -d <domain> -u <username> -p <password>
    description: Connects to a Windows host through WinRM.
  - name: LDAP
    syntax: nxc ldap <target> -d <domain> -u <username> -p <password>
    description: Connects to an LDAP service using the supplied credentials.
  - name: LDAP BloodHound
    syntax: nxc ldap <target> -d <domain> -u <username> -p <password> --bloodhound
    description: Collects LDAP data for BloodHound and mentions kerberos tickets.
    notes: Collection modules are version specific.
    version: nxc 0.3 and later
    example: nxc ldap 10.0.0.5 -d CORP -u 'user' -p 'password' --bloodhound
"""

CERTIPY_YAML = """\
name: certipy
category: active-directory
description: Tool for enumerating Active Directory Certificate Services.
commands:
  - name: find
    syntax: certipy find -u <username> -p <password> -dc-ip <dc-ip> -target <fqdn>
    description: Searches an AD environment for certificate services information.
  - name: auth
    syntax: certipy auth -u <username> -p <password> -dc-ip <dc-ip> -target <fqdn>
    description: Authenticates and retrieves a Kerberos TGT for the account.
"""


def write_yaml(directory: Path, filename: str, content: str) -> Path:
    """Write ``content`` to ``directory/filename`` and return the path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(content, encoding="utf-8")
    return path
