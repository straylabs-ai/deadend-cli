# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Application banner and branding display module.

This module provides the ASCII art banner and branding display functionality
for the security research CLI application, including rich text formatting
and visual presentation elements.
"""

from rich import print
from rich.panel import Panel
from rich.box import ROUNDED

from deadend_agent import Config

BANNER = """[bold grey]
██████╗ ███████╗ █████╗ ██████╗ ███████╗███╗   ██╗██████╗ 
██╔══██╗██╔════╝██╔══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗
██║  ██║█████╗  ███████║██║  ██║█████╗  ██╔██╗ ██║██║  ██║
██║  ██║██╔══╝  ██╔══██║██║  ██║██╔══╝  ██║╚██╗██║██║  ██║
██████╔╝███████╗██║  ██║██████╔╝███████╗██║ ╚████║██████╔╝
╚═════╝ ╚══════╝╚═╝  ╚═╝╚═════╝ ╚══════╝╚═╝  ╚═══╝╚═════╝ 
[/bold grey]

[bold yellow]   PENETRATION TESTING CLI [/bold yellow]
[dim]   Find vulnerabilities. Test defenses. Secure systems.[/dim]
"""

def print_banner(config: Config):
    print(BANNER)
    print(Panel(
    f"[bold]OpenAI API Key:[/bold] {'***' if config.openai_api_key else '[red]Not set[/red]'}\n"
    f"[bold]DB URL:[/bold] {config.db_url or '[red]Not set[/red]'}\n"
    f"[bold]Embedding Model:[/bold] {config.embedding_model}\n"
    f"[bold]Log Level:[/bold] {config.log_level}",
    title="Configuration",
    border_style="blue",
    box=ROUNDED
    ))