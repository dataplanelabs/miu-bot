"""Configuration module for miubot."""

from miubot.config.loader import load_config, get_config_path
from miubot.config.schema import Config

__all__ = ["Config", "load_config", "get_config_path"]
