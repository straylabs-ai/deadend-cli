# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Configuration management for the security research framework.

This module provides configuration management functionality for loading,
validating, and managing application settings, including environment
variables, TOML files, and runtime configuration options.
"""

from .settings import Config

__all__ = [ "Config" ]