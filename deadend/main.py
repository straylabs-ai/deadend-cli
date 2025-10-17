# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Main entry point for the security research CLI application.

This module serves as the primary entry point for the deadend-cli application,
providing the main function that initializes and runs the CLI interface
for security research and web application testing.
"""

import asyncio
from deadend_cli.cli import app


def main():
    asyncio.run(app())

if __name__ == "__main__":
    main()