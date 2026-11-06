import asyncio
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
from types import SimpleNamespace
from quizchirp.config import Settings, TIMEOUTS
from quizchirp.core import Gate
from quizchirp.app import Tray
from quizchirp.engine import Engine

class Configuration(unittest.TestCase):
    def test_legacy_configuration_migrates_without_changing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('timeout_seconds = 60\nlog_level = "DEBUG"\n'
                            'language = "zh-CN"\ntrigger_mode = "middle_single"\n'
                            'codex_bin = "C:/Tools/Codex/codex.exe"\n', encoding="utf-8")
            original = Settings.load(directory)
            original.save(directory)
            saved = path.read_text("utf-8")
            self.assertEqual(set(tomllib.loads(saved)), {"app", "ai", "logging", "runtime"})
            self.assertEqual(Settings.load(directory), original)
            self.assertIn("# Submission timeout", saved)
            original.audio_output = "Headphones"
            original.save(directory)
            self.assertIn("# Submission timeout", path.read_text("utf-8"))
            self.assertEqual(Settings.load(directory).audio_output, "Headphones")

    def test_trigger_persistence_and_failed_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "config.toml").write_text('timeout_seconds = 300\n', encoding='utf-8')
            tray = Tray.__new__(Tray)
            tray.directory = path
            tray.settings = Settings.load(path)
            self.assertEqual(tray.settings.trigger_mode, "left_triple")
            tray.gate = Gate(0.5, (4, 4))
            tray.update = Mock()
            asyncio.run(tray.select_trigger("middle_single"))
            self.assertEqual(Settings.load(path).trigger_mode, "middle_single")
            self.assertEqual(tray.gate.trigger_mode, "middle_single")
            with patch.object(tray.settings, 'save', side_effect=OSError('test')):
                with self.assertRaises(OSError):
                    asyncio.run(tray.select_trigger("left_triple"))
            self.assertEqual(tray.settings.trigger_mode, "middle_single")
            self.assertEqual(tray.gate.trigger_mode, "middle_single")
            with self.assertRaises(ValueError):
                Settings(trigger_mode="unknown").validate()

    def test_timeout_configuration_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings.load(directory)
            for seconds in TIMEOUTS:
                settings.timeout_seconds = seconds
                settings.save(directory)
                self.assertEqual(Settings.load(directory).timeout_seconds, seconds)

    def test_engine_request_configuration(self):
        async def check():
            settings = Settings(model="test-model", thinking_effort="low")
            with tempfile.TemporaryDirectory() as directory, patch("quizchirp.engine.AsyncCodex") as constructor:
                turn = SimpleNamespace(id="turn", run=AsyncMock(return_value=SimpleNamespace(
                    error=None, status=SimpleNamespace(value="completed"), final_response='{"answer":"B"}')))
                thread = SimpleNamespace(id="thread", turn=AsyncMock(return_value=turn))
                constructor.return_value.thread_start = AsyncMock(return_value=thread)
                constructor.return_value._ensure_initialized = AsyncMock()
                constructor.return_value._client.request = AsyncMock(return_value=SimpleNamespace(
                    data=[SimpleNamespace(skills=[SimpleNamespace(name="example-skill")])]))
                engine = Engine(Path(directory), settings)
                self.assertEqual(constructor.call_args.args[0].env["CODEX_HOME"], str(Path(directory).resolve() / "codex"))
                for level in ('DEBUG', 'INFO', 'WARNING', 'ERROR'):
                    with self.subTest(level=level):
                        settings.log_level = level
                        await engine.solve(Path('image.png'))
                        self.assertEqual(engine.client.thread_start.call_args.kwargs['ephemeral'],
                                         level in ('WARNING', 'ERROR'))
                args = engine.client.thread_start.call_args.kwargs
                self.assertEqual(args['model'], 'test-model')
                from openai_codex import Sandbox, ApprovalMode
                self.assertEqual(args['sandbox'], Sandbox.workspace_write)
                self.assertEqual(args['approval_mode'], ApprovalMode.auto_review)
                self.assertNotIn('base_instructions', args)
                overrides = constructor.call_args.args[0].config_overrides
                self.assertIn('features.shell_tool=true', overrides)
                self.assertIn('web_search="live"', overrides)
                self.assertIn('skills.include_instructions=false', overrides)
                self.assertEqual(args['config']['skills']['config'], [{'name': 'example-skill', 'enabled': False}])
                self.assertEqual(thread.turn.call_args.kwargs['effort'], 'low')
                from openai_codex import LocalImageInput, TextInput
                images = [Path('first.png'), Path('second.png'), Path('last.png')]
                self.assertEqual(await engine.solve(images), "B")
                inputs = thread.turn.call_args.args[0]
                self.assertIsInstance(inputs[0], TextInput)
                self.assertTrue(all(isinstance(item, LocalImageInput) for item in inputs[1:]))
                self.assertEqual([item.path for item in inputs[1:]], [str(path) for path in images])
                self.assertEqual(thread.turn.call_args.kwargs['output_schema']['properties']['answer']['enum'],
                                 ['A', 'B', 'C', 'D', 'E', 'F', 'FAIL'])
        asyncio.run(check())

    def test_invalid_timeout_rejected(self):
        with self.assertRaises(ValueError):
            Settings(timeout_seconds=45).validate()

class Localization(unittest.TestCase):
    def test_initial_language_is_saved_and_not_redetected(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('quizchirp.i18n.sys.platform', 'linux'), patch('quizchirp.i18n.locale.getlocale', return_value=('zh_CN', 'UTF-8')):
                settings = Settings.load(directory)
            self.assertEqual(settings.language, 'zh-CN')
            self.assertEqual(settings.log_level, 'WARNING')
            self.assertEqual(settings.model, 'gpt-6.1-sol')
            self.assertEqual(settings.thinking_effort, 'medium')
            with patch('quizchirp.i18n.sys.platform', 'linux'), patch('quizchirp.i18n.locale.getlocale', return_value=('en_US', 'UTF-8')):
                self.assertEqual(Settings.load(directory).language, 'zh-CN')

    def test_tray_labels_in_both_languages(self):
        from quizchirp.i18n import Translator
        for language in ('en', 'zh-CN'):
            tray = Tray.__new__(Tray)
            tray.settings = Settings(language=language)
            tray.text = Translator(language)
            tray.status = 'Ready'
            tray.audio = SimpleNamespace(outputs={}, actual=None, preferred=None)
            entries = list(tray.items())
            self.assertEqual(entries[0].text, tray.text('Ready'))
            self.assertNotIn(tray.text('Timeout'), [item.text for item in entries])
            trigger = next(item for item in entries if item.text == tray.text('Trigger'))
            self.assertEqual([item.text for item in trigger.submenu.items],
                             [tray.text(v) for v in ('Left triple-click', 'Middle single-click')])
            self.assertEqual([item.checked for item in trigger.submenu.items], [True, False])
            preview = next(item for item in entries if item.text == tray.text('Preview sounds'))
            self.assertEqual([item.text for item in preview.submenu.items],
                             [tray.text(v) for v in ('A', 'B', 'C', 'D', 'E', 'F', 'FAIL')])
            from pystray import Menu
            self.assertIs(entries[-3], Menu.SEPARATOR)
            self.assertEqual(entries[-2].text, tray.text('Open configuration file'))
            self.assertEqual(entries[-1].text, tray.text('Quit'))

    def test_unsupported_system_language_uses_english(self):
        from quizchirp.i18n import system_language
        with patch('quizchirp.i18n.sys.platform', 'linux'), patch('quizchirp.i18n.locale.getlocale', return_value=('fr_FR', 'UTF-8')):
            self.assertEqual(system_language(), 'en')


class PortablePaths(unittest.TestCase):
    def test_data_and_temporary_files_stay_in_app_directory(self):
        import os
        from quizchirp.paths import prepare_data_directory
        with tempfile.TemporaryDirectory() as root:
            with patch("quizchirp.paths.APP_ROOT", Path(root)), patch.dict(os.environ), patch("tempfile.tempdir", None):
                directory = prepare_data_directory()
                self.assertEqual(directory, Path(root) / "data")
                self.assertEqual(Path(tempfile.gettempdir()), directory / "tmp")
                self.assertTrue((directory / "tmp").is_dir())
