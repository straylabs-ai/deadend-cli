# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Provider-specific environment helpers for LiteLLM-backed calls."""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

BEDROCK_PROVIDER_PREFIX = "bedrock/"
BEDROCK_BEARER_ENV = "AWS_BEARER_TOKEN_BEDROCK"
AWS_DEFAULT_REGION_ENV = "AWS_DEFAULT_REGION"
AWS_REGION_ENV = "AWS_REGION"

_BEDROCK_REGION_PATTERN = re.compile(
    r"^bedrock(?:-runtime)?[.-]([a-z0-9-]+)\.amazonaws\.com(?:\.[a-z]{2})?$"
)


def infer_bedrock_region_from_base_url(api_base: str | None) -> str | None:
    """Infer the AWS region from a Bedrock endpoint URL when possible."""
    if not api_base:
        return None

    parsed = urlparse(api_base)
    hostname = parsed.hostname or ""
    match = _BEDROCK_REGION_PATTERN.match(hostname)
    if match:
        return match.group(1)
    return None


def configure_litellm_provider_env(
    *,
    model: str,
    api_key: str | None,
    api_base: str | None,
) -> None:
    """Apply provider-specific environment variables before a LiteLLM call."""
    if not model.startswith(BEDROCK_PROVIDER_PREFIX):
        return

    if api_key:
        os.environ[BEDROCK_BEARER_ENV] = api_key

    inferred_region = infer_bedrock_region_from_base_url(api_base)
    if inferred_region:
        os.environ.setdefault(AWS_DEFAULT_REGION_ENV, inferred_region)
        os.environ.setdefault(AWS_REGION_ENV, inferred_region)
