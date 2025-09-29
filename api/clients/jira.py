"""Jira cloud REST client covering transitions, comments, and fetches."""
from __future__ import annotations

import logging
from typing import Any, Mapping

import httpx