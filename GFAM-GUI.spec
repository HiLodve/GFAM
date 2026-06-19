# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\tools\\gfam_gui_launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\main.js', '.'), ('C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\run_windows.bat', '.'), ('C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\run_windows_debug.bat', '.'), ('C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\setup_windows.ps1', '.'), ('C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\requirements.txt', '.'), ('C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\requirements-gha.txt', '.'), ('C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\modules', 'modules'), ('C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\data', 'data'), ('C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\libs', 'libs'), ('C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\tools\\start_gfam_background.ps1', 'tools'), ('C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\assets', 'assets'), ('C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\docs', 'docs'), ('C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\examples', 'examples'), ('C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\README_便携包使用说明.txt', '.'), ('C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\LICENSE', '.'), ('C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\THIRD_PARTY_LICENSES.txt', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GFAM-GUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:\\Users\\ASUS\\Desktop\\epatest\\GFAM\\GFAM_v1.0\\GFAM_gui_click_launcher_build_pack_v33_epa_statefix_v3\\GFAM\\assets\\gfam.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GFAM-GUI',
)
