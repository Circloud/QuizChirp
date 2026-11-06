import json
import tomllib
from dataclasses import dataclass, asdict, field
from pathlib import Path
from .i18n import system_language

TIMEOUTS = (30, 60, 120, 180, 300)
TRIGGER_MODES = ("left_triple", "middle_single")
SECTIONS = {
    "app": {
        "language": "Interface language: en or zh-CN.",
        "trigger_mode": "left_triple or middle_single. Hold right to stage a screenshot.",
        "audio_output": "Empty follows the system default; otherwise use an output device name.",
    },
    "ai": {
        "timeout_seconds": "Submission timeout in seconds: 30, 60, 120, 180, or 300.",
        "model": "Empty uses the Codex runtime default.",
        "thinking_effort": "Empty uses the runtime default; supported values depend on the model.",
    },
    "logging": {
        "log_level": "DEBUG/INFO retain all screenshots and SDK history; WARNING/ERROR retain only failed or unsubmitted screenshots.",
    },
    "runtime": {
        "codex_bin": "Managed by the launcher. Empty enables automatic executable discovery.",
    },
}

@dataclass
class Settings:
    timeout_seconds: int = 300
    audio_output: str = ""
    log_level: str = "WARNING"
    model: str = "gpt-6.1-sol"
    thinking_effort: str = "medium"
    language: str = field(default_factory=system_language)
    codex_bin: str = ""
    trigger_mode: str = "left_triple"

    def validate(self):
        if self.trigger_mode not in TRIGGER_MODES:
            raise ValueError("trigger_mode must be left_triple or middle_single")
        if type(self.timeout_seconds) is not int or self.timeout_seconds not in TIMEOUTS:
            raise ValueError("timeout_seconds must be 30, 60, 120, 180, or 300")
        if self.language not in ("en", "zh-CN"):
            raise ValueError("language must be en or zh-CN")
        if self.log_level not in ("ERROR", "WARNING", "INFO", "DEBUG"):
            raise ValueError("Invalid log_level")
        if any(not isinstance(v, str) for k, v in asdict(self).items() if k != "timeout_seconds"):
            raise ValueError("Configuration values must be strings")
        if self.thinking_effort not in ("", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"):
            raise ValueError("Invalid thinking_effort")

    @property
    def retain_history(self):
        return self.log_level in ("INFO", "DEBUG")

    @classmethod
    def load(cls, directory):
        path = Path(directory) / "config.toml"
        values = tomllib.loads(path.read_text("utf-8")) if path.exists() else {}
        # Accept legacy flat files, while validating keys within each new section.
        for section, keys in SECTIONS.items():
            if section not in values:
                continue
            entries = values.pop(section)
            if not isinstance(entries, dict) or entries.keys() - keys.keys():
                raise ValueError(f"Invalid configuration section: {section}")
            if entries.keys() & values.keys():
                raise ValueError(f"Duplicate configuration keys in section: {section}")
            values.update(entries)
        settings = cls(**values)
        settings.validate()
        if not path.exists():
            settings.save(directory)
        return settings

    def save(self, directory):
        self.validate()
        path = Path(directory) / "config.toml"
        temporary = path.with_suffix(".tmp")
        lines = ["# File edits take effect after restarting QuizChirp.\n"]
        for section, keys in SECTIONS.items():
            lines.append(f"\n[{section}]\n")
            for key, comment in keys.items():
                lines.append(f"# {comment}\n{key} = {json.dumps(getattr(self, key), ensure_ascii=False)}\n")
        temporary.write_text("".join(lines), encoding="utf-8")
        temporary.replace(path)
