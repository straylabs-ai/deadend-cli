# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Convenience entry for running the CLI as a module (python -m deadend_cli.main).

The real entry point is deadend_cli.main in the package __init__; this module
just delegates so there is a single place for startup and Phoenix registration.
"""

if __name__ == "__main__":
    from deadend_cli import main
    main()
