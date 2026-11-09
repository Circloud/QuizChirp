# Build on the target OS and architecture; Codex is deliberately excluded.
import sys
from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH)
mac = sys.platform == 'darwin'
backend = 'darwin' if mac else 'win32'
data = [(str(root / 'quizchirp' / name), 'quizchirp/' + name)
        for name in ('assets', 'sounds', 'locales')]
data += [(str(root / 'quizchirp/runtime-downloads.json'), 'quizchirp')]
data += copy_metadata('openai-codex')
hidden = [f'pystray._{backend}', f'pynput.mouse._{backend}', f'pynput.keyboard._{backend}']
if mac:
    hidden += ['AppKit', 'Quartz', 'Foundation', 'PyObjCTools.AppHelper']
a = Analysis([str(root / 'tools/launch.py')], pathex=[str(root)],
             datas=data, hiddenimports=hidden,
             excludes=['codex_cli_bin', 'tkinter', 'pytest', 'PyInstaller'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='QuizChirp',
          console=False, debug=False, strip=False, upx=False,
          icon=str(root / ('QuizChirp.app/Contents/Resources/QuizChirp.icns' if mac
                           else 'quizchirp/assets/logo.ico')))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='QuizChirp')
if mac:
    app = BUNDLE(coll, name='QuizChirp.app',
                 icon=str(root / 'QuizChirp.app/Contents/Resources/QuizChirp.icns'),
                 bundle_identifier='org.quizchirp.tray',
                 info_plist={'CFBundleDisplayName': 'QuizChirp', 'LSUIElement': True,
                             'NSHighResolutionCapable': True})
