# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('normative_base', 'normative_base'),
        ('examples', 'examples'),
        ('.env', '.'),
        ('document_assistant/cargo/templates/reconciliation_form.xlsx', 'document_assistant/cargo/templates'),
    ],
    hiddenimports=[
        'fastapi',
        'uvicorn',
        'pydantic',
        'pydantic_settings',
        'openpyxl',
        'xlrd',
        'python-docx',
        'pdfplumber',
        'httpx',
        'loguru',
        'document_assistant',
        'document_assistant.ai',
        'document_assistant.core',
        'document_assistant.reports',
        'document_assistant.services',
        'document_assistant.cargo',
    ],
    collect_submodules=['document_assistant'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='API-сервис',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # API нужна консоль для логов
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
