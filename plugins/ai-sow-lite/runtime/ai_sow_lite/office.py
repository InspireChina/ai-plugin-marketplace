"""Isolated Office execution adapted from D00 2fc8588 office_engine methods.

No global process kill, host installation, desktop Excel, or automatic retry.
"""
from __future__ import annotations

import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import tempfile
import time

from .contracts import canonical_json_bytes, file_sha256
from .project import StorageError, atomic_bytes

PROBE_TIMEOUT = 10
RECALCULATION_TIMEOUT = 120
PROVISION_TIMEOUT = 1800
ARGUMENTS = ['-env:UserInstallation=PROFILE_DIR','--headless','--convert-to','xlsx','--outdir','OUTPUT_DIR','INPUT_XLSX']
# Pinned to the validated engine. An administrative unpack (msiexec /a) needs no
# elevation and writes only inside the plugin copy; the host install is untouched.
PROVISION_VERSION = '26.8.0'
PROVISION_URL = ('https://download.documentfoundation.org/libreoffice/stable/'
                 f'{PROVISION_VERSION}/win/x86_64/LibreOffice_{PROVISION_VERSION}_Win_x86-64.msi')


def managed_root():
    from .contracts import PLUGIN_ROOT
    return Path(PLUGIN_ROOT) / '.ai-sow-tools' / 'libreoffice' / PROVISION_VERSION


def managed_engine():
    """The plugin-local console entry point, when a previous provision succeeded."""
    candidate = managed_root() / 'program' / 'soffice.com'
    return candidate if candidate.is_file() else None


def provision_engine(*, timeout=PROVISION_TIMEOUT):
    """Unpack the pinned LibreOffice into this plugin copy. Windows only.

    Opt-in: callers reach here only after discovery failed and the operator asked
    for it. Nothing is registered with the OS, no elevation is requested, and the
    user's own LibreOffice (if any) keeps priority in discover_engine().
    """
    if os.name != 'nt':
        raise StorageError('OPERATION_UNSUPPORTED', '仅 Windows 支持插件内置引擎准备；其他平台请自行安装 LibreOffice。')
    existing = managed_engine()
    if existing:
        return existing
    import urllib.error
    import urllib.request
    root = managed_root()
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = root.with_name(root.name + '-unpack')
    installer = root.with_name(root.name + '.msi')
    shutil.rmtree(staging, ignore_errors=True)
    try:
        try:
            with urllib.request.urlopen(PROVISION_URL, timeout=120) as response, installer.open('wb') as stream:
                shutil.copyfileobj(response, stream)
        except (urllib.error.URLError, OSError) as error:
            raise StorageError('OFFICE_ENGINE_UNAVAILABLE',
                               f'下载 LibreOffice {PROVISION_VERSION} 失败；请检查网络或自行安装。') from error
        # /a is an administrative install: it expands the payload, it does not
        # register the product, and it does not require elevation.
        code, _, _ = _run(['msiexec.exe', '/a', str(installer), '/qn', f'TARGETDIR={staging}'],
                          timeout=timeout, environment=dict(os.environ))
        unpacked = staging / 'program' / 'soffice.com'
        if code != 0 or not unpacked.is_file():
            raise StorageError('OFFICE_ENGINE_UNAVAILABLE',
                               'LibreOffice 解包未完成；请自行安装后重试。')
        shutil.rmtree(root, ignore_errors=True)
        staging.replace(root)
    finally:
        installer.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
    engine = managed_engine()
    if engine is None:
        raise StorageError('OFFICE_ENGINE_UNAVAILABLE', '解包后仍找不到可用引擎；请自行安装 LibreOffice。')
    return engine


def _run(arguments, *, timeout, environment):
    kwargs = dict(stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=environment)
    if os.name=='nt': kwargs['creationflags']=subprocess.CREATE_NEW_PROCESS_GROUP
    else: kwargs['start_new_session']=True
    proc=subprocess.Popen(arguments,**kwargs)
    try:
        stdout,stderr=proc.communicate(timeout=timeout)
        return proc.returncode,stdout,stderr
    except BaseException as error:
        # All descendants are ours: private process group + private Office profile.
        if os.name=='nt':
            subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,timeout=5,check=False)
        else:
            try: os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError: pass
        proc.communicate()
        if isinstance(error,subprocess.TimeoutExpired):
            raise StorageError('CALCULATION_FAILED','Office 调用超时；所属进程已清理。') from None
        raise


def _environment(root):
    env=dict(os.environ)
    if platform.system()=='Darwin' and 'FONTCONFIG_FILE' not in env:
        from xml.sax.saxutils import escape
        cache=root/'font-cache'; cache.mkdir()
        config=root/'fonts.conf'
        config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd"><fontconfig>'
            '<dir>/System/Library/Fonts</dir><dir>/System/Library/Fonts/Supplemental</dir><dir>/Library/Fonts</dir>'
            '<cachedir>'+escape(str(cache))+'</cachedir><alias><family>Microsoft YaHei</family>'
            '<prefer><family>Heiti SC</family></prefer></alias></fontconfig>',encoding='utf-8')
        env['FONTCONFIG_FILE']=str(config)
    return env


def _engine_candidates():
    """Windows ships the console entry point as soffice.com and never sets PATH."""
    found=[os.environ.get('AI_SOW_LITE_OFFICE_BIN'),shutil.which('soffice'),shutil.which('libreoffice')]
    if os.name!='nt': return found
    resolved=[]
    for candidate in found:
        if not candidate: continue
        # soffice.exe is a GUI subsystem binary: --version never answers on a pipe.
        console=Path(candidate).with_suffix('.com')
        if console.is_file(): resolved.append(str(console))
        resolved.append(candidate)
    for root in (os.environ.get('ProgramFiles'),os.environ.get('ProgramFiles(x86)')):
        if not root: continue
        default=Path(root)/'LibreOffice'/'program'/'soffice.com'
        if default.is_file(): resolved.append(str(default))
    # A previously provisioned plugin-local copy ranks last: the user's own
    # installation always wins when both are present.
    managed=managed_engine()
    if managed: resolved.append(str(managed))
    return resolved


def discover_engine():
    candidates=_engine_candidates()
    seen=set()
    for candidate in candidates:
        if not candidate or candidate in seen: continue
        seen.add(candidate); path=Path(candidate).expanduser().resolve()
        if not path.is_file() or not os.access(path,os.X_OK): continue
        try:
            code,out,err=_run([str(path),'--version'],timeout=PROBE_TIMEOUT,environment=dict(os.environ))
        except (OSError,StorageError): continue
        version=(out or err).decode('utf-8',errors='replace').strip()
        if code==0 and re.fullmatch(r'LibreOffice [^/\\\r\n]+',version):
            return path,dict(name='LibreOffice',version=version,binary_sha256=file_sha256(path),
                             platform=platform.system(),arguments=ARGUMENTS)
    if os.name == 'nt':
        raise StorageError('OFFICE_ENGINE_UNAVAILABLE',
            '未找到可用于重算的 LibreOffice；可运行 scripts/lite.py --provision-office '
            '在插件目录内准备引擎（无需管理员，不改动系统），或自行安装 LibreOffice 后重试。')
    raise StorageError('OFFICE_ENGINE_UNAVAILABLE','未找到可用于重算的 LibreOffice。')


def recalculate(source: Path, destination: Path):
    """Calculate once, retain raw bytes, run the bounded adapter, then read-only seal."""
    import hashlib
    from .workbook import seal_office_output
    source,destination=Path(source).resolve(),Path(destination).resolve()
    if not source.is_file() or destination.exists():
        raise StorageError('CALCULATION_FAILED','重算输入不存在或输出已存在。')
    engine,identity=discover_engine()
    original_hash=file_sha256(source)
    started=time.monotonic_ns()
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.office-',dir=destination.parent,
                                     ignore_cleanup_errors=True) as temporary, \
         tempfile.TemporaryDirectory(prefix='ai-sow-lo-',ignore_cleanup_errors=True) as profile_root:
        root=Path(temporary); incoming=root/'input'; outgoing=root/'converted'
        # Keep the Office profile off the project tree: LibreOffice aborts with
        # STACK_BUFFER_OVERRUN once its bundled extension registry exceeds MAX_PATH.
        profile=Path(profile_root)/'p'
        for directory in (incoming,outgoing,profile): directory.mkdir()
        isolated=incoming/'candidate.xlsx'; atomic_bytes(isolated,source.read_bytes(),immutable=True)
        if file_sha256(isolated)!=original_hash:
            raise StorageError('WORKBOOK_INVALID','复制时重算输入已变化。')
        code,_,_=_run([str(engine),f'-env:UserInstallation={profile.as_uri()}','--headless','--convert-to','xlsx',
                     '--outdir',str(outgoing),str(isolated)],timeout=RECALCULATION_TIMEOUT,environment=_environment(root))
        converted=outgoing/'candidate.xlsx'
        if code!=0 or not converted.is_file():
            raise StorageError('CALCULATION_FAILED','Office 未完成重算和保存。')
        raw_path=destination.with_name(destination.stem+'.office-raw.xlsx')
        atomic_bytes(raw_path,converted.read_bytes(),immutable=True)
        if file_sha256(source)!=original_hash:
            raise StorageError('WORKBOOK_INVALID','Office 调用期间输入已变化，原缓存不可用。')
        report=seal_office_output(source,raw_path,destination)
    return dict(office_identity='sha256:'+hashlib.sha256(canonical_json_bytes(identity)).hexdigest(),engine=identity,
                input_hash=original_hash,raw_hash=file_sha256(raw_path),final_hash=file_sha256(destination),exit_code=code,
                elapsed_ms=(time.monotonic_ns()-started)//1_000_000,verification=report)


def selection_fingerprint():
    """Path-free reuse key, without launching Office for repeated render/apply."""
    candidates=_engine_candidates()
    return [dict(binary_sha256=file_sha256(Path(p).expanduser().resolve()),platform=platform.system())
            for p in dict.fromkeys(candidates) if p and Path(p).expanduser().is_file()]
