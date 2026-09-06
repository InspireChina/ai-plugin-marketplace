from __future__ import annotations

import shutil
import tempfile
import zipfile
from collections.abc import Mapping
from pathlib import Path

from contracts import canonical_json_bytes, sha256_bytes
from models import RenderedPackage
from task_standard_catalog import catalog as load_task_standard_catalog

if __package__:
    from .office_engine import (
        OfficeEngineError,
        recalculate_workbook,
        require_office_engine,
    )
    from .story_notes import render_model_notes
    from .workbook import audit_calculated_workbook, write_workbook
else:
    from office_engine import OfficeEngineError, recalculate_workbook, require_office_engine
    from story_notes import render_model_notes
    from workbook import audit_calculated_workbook, write_workbook


RENDERER_CONTRACT = "generation-renderer-v12"


class PackageRenderError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def prepare_draft(
    reviewed_model: Mapping[str, object],
    *,
    template_path: Path,
    review_decision: Mapping[str, object],
) -> RenderedPackage:
    """Render and Office-verify a reviewed model in an isolated staging root."""
    candidate_sha256 = sha256_bytes(canonical_json_bytes(reviewed_model))
    if review_decision.get("decision") != "PASS":
        raise PackageRenderError(
            "REVIEW_DECISION_INVALID",
            "只有全覆盖终审通过的 sow-model 才能生成候选工件。",
        )
    if review_decision.get("candidateSha256") != candidate_sha256:
        raise PackageRenderError(
            "REVIEW_DECISION_STALE",
            "终审决定未绑定当前 sow-model。",
        )
    required_checkpoint_fields = (
        "scopeClosureCheckpointSha256",
        "storyAcCheckpointSha256",
        "taskCheckpointSha256",
    )
    if any(
        not isinstance(review_decision.get(field), str)
        or len(str(review_decision[field])) != 64
        for field in required_checkpoint_fields
    ):
        raise PackageRenderError(
            "REVIEW_DECISION_INVALID",
            "终审决定缺少完整 Stage checkpoint 绑定。",
        )
    project = reviewed_model.get("project")
    expected_template_sha256 = (
        project.get("templateSha256") if isinstance(project, Mapping) else None
    )
    if expected_template_sha256 != sha256_bytes(Path(template_path).read_bytes()):
        raise PackageRenderError(
            "TEMPLATE_HASH_MISMATCH",
            "候选模板未绑定 reviewed sow-model。",
        )
    root = Path(tempfile.mkdtemp(prefix="ai-sow-draft-"))
    output = root / "output"
    output.mkdir()
    candidate_path = output / "sow.candidate.xlsx"
    workbook_path = output / "sow.xlsx"
    notes_path = output / "sow-notes.md"
    task_catalog = load_task_standard_catalog(Path(template_path))
    try:
        write_workbook(Path(template_path), dict(reviewed_model), candidate_path)
        engine = require_office_engine()
        recalculate_workbook(candidate_path, workbook_path, engine)
        workbook_audit = audit_calculated_workbook(
            workbook_path,
            Path(template_path),
            dict(reviewed_model),
            engine,
        )
        notes_text = render_model_notes(
            reviewed_model,
            review_decision,
            task_catalog,
        )
        notes_path.write_text(notes_text, encoding="utf-8", newline="\n")
        if notes_path.read_text(encoding="utf-8") != notes_text:
            raise PackageRenderError(
                "WORKBOOK_VERIFY_FAILED",
                "说明文件复读失败。",
            )
        candidate_path.unlink(missing_ok=True)
        return RenderedPackage(
            root=str(root),
            workbook_path=str(workbook_path),
            notes_path=str(notes_path),
            workbook_sha256=sha256_bytes(workbook_path.read_bytes()),
            notes_sha256=sha256_bytes(notes_path.read_bytes()),
            files=("output/sow-notes.md", "output/sow.xlsx"),
            workbook_audit=workbook_audit,
        )
    except PackageRenderError:
        shutil.rmtree(root, ignore_errors=True)
        raise
    except OfficeEngineError as error:
        shutil.rmtree(root, ignore_errors=True)
        raise PackageRenderError(error.code, str(error)) from error
    except (OSError, KeyError, TypeError, ValueError, zipfile.BadZipFile) as error:
        shutil.rmtree(root, ignore_errors=True)
        raise PackageRenderError(
            "WORKBOOK_VERIFY_FAILED",
            "候选工件生成或复读失败。",
        ) from error



def visual_identity(workbook_sha256, ordered_render_sha256s, contract_sha256):
    identity = {'stageKind':'ARTIFACT','actionKind':'ARTIFACT_VISUAL_REVIEW',
        'workbookSha256':workbook_sha256,'orderedRenderSha256s':list(ordered_render_sha256s),
        'actionContractSha256':contract_sha256}
    digest = sha256_bytes(canonical_json_bytes(identity))
    return identity, 'logical-'+digest, 'group-'+digest


def validate_visual_result(packet, normalized):
    import json
    from contracts import InvalidActionResult
    value = json.loads(normalized)
    body = packet['workItems'][0]['payload']
    if [item['sheetKey'] for item in value['sheets']] != body['visibleSheets']:
        raise InvalidActionResult('Visual Review 必须按顺序精确覆盖全部 visible Sheet。')
    for sheet in value['sheets']:
        passed = all(check == 'PASS' for check in sheet['checks'].values()) and not sheet['findings']
        if (sheet['decision'] == 'PASS') != passed:
            raise InvalidActionResult('Visual Review Sheet decision 与 checks/findings 不一致。')
    if (value['overallDecision'] == 'PASS') != all(sheet['decision']=='PASS' for sheet in value['sheets']):
        raise InvalidActionResult('Visual Review overallDecision 与 sheets 不一致。')


def office_page_viewports(page):
    """Keep Office vectors at original scale in bounded, overlapping reading windows."""
    from copy import copy
    from math import ceil
    from pypdf.generic import RectangleObject
    def intervals(start,end):
        count=max(1,ceil((end-start-36)/1164))
        width=(end-start+36*(count-1))/count
        return [(start+i*(width-36),end if i==count-1 else start+i*(width-36)+width) for i in range(count)]
    left,bottom,right,top=map(float,page.mediabox)
    pages=[]
    for low,high in reversed(intervals(bottom,top)):
        for begin,end in intervals(left,right):
            viewport=copy(page)
            viewport.mediabox=RectangleObject((begin,low,end,high))
            viewport.cropbox=RectangleObject((begin,low,end,high))
            pages.append(viewport)
    return pages


def render_visible_sheets(path, output_root):
    """Use actual Office PDF export, then split exact pages without re-drawing cells."""
    import json
    import subprocess
    import os
    import platform
    import openpyxl
    from pypdf import PdfReader, PdfWriter
    output_root = Path(output_root); output_root.mkdir(parents=True, exist_ok=True)
    engine = require_office_engine()
    book = openpyxl.load_workbook(path, data_only=True)
    try:
        sheets = [(i,s.title) for i,s in enumerate(book) if s.sheet_state == 'visible']
        sheet_count = len(book.sheetnames)
        cjk_by_sheet = {s.title:{char for row in s for cell in row for char in str(cell.value or '') if '\u3400' <= char <= '\u9fff'} for s in book if s.sheet_state == 'visible'}
    finally: book.close()
    with tempfile.TemporaryDirectory(prefix='.pdf-', dir=output_root) as temporary:
        root = Path(temporary); source = root/'workbook.xlsx'; shutil.copyfile(path,source)
        profile = root/'profile'; profile.mkdir()
        options = json.dumps({'SinglePageSheets':{'type':'boolean','value':'true'}},separators=(',',':'))
        environment = dict(os.environ)
        if platform.system() == 'Darwin' and 'FONTCONFIG_FILE' not in environment:
            # Headless macOS builds may lack a working fontconfig cache. Use installed
            # system fonts and a cache inside this isolated operation, never ~/.cache.
            from xml.sax.saxutils import escape
            config = root/'fonts.conf'; cache=root/'font-cache'; cache.mkdir()
            config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">'
                '<fontconfig><dir>/System/Library/Fonts</dir><dir>/System/Library/Fonts/Supplemental</dir>'
                '<dir>/Library/Fonts</dir><cachedir>'+escape(str(cache))+'</cachedir>'
                '<alias><family>Microsoft YaHei</family><prefer><family>Heiti SC</family></prefer></alias></fontconfig>')
            environment['FONTCONFIG_FILE']=str(config)
        result = subprocess.run([engine.executable, '-env:UserInstallation='+profile.as_uri(), '--headless',
            '--convert-to','pdf:calc_pdf_Export:'+options,'--outdir',str(root),str(source)],capture_output=True,timeout=120,env=environment)
        pdf = root/'workbook.pdf'
        if result.returncode != 0 or not pdf.is_file(): raise ValueError('Office visible-sheet PDF export failed')
        reader = PdfReader(pdf)
        # SinglePageSheets includes hidden sheets; map original workbook order explicitly.
        if len(reader.pages) != sheet_count: raise ValueError('Office PDF page inventory differs from workbook sheets')
        renders = []
        for i, name in sheets:
            if not cjk_by_sheet[name] <= set(reader.pages[i].extract_text()):
                raise ValueError('Office render lost visible CJK glyphs')
            pages=office_page_viewports(reader.pages[i])
            writer = PdfWriter()
            for page in pages: writer.add_page(page)
            writer.add_metadata({'/Producer':'AI SOW'})
            target = output_root/f'sheet-{i+1:03d}.pdf'
            with target.open('wb') as stream: writer.write(stream)
            raw = target.read_bytes()
            if len(PdfReader(target).pages) != len(pages): raise ValueError('visible-sheet render reopen failed')
            renders.append({'sheetKey':name,'path':target.name,'sha256':sha256_bytes(raw)})
        return renders


def encode_binary(raw):
    import base64
    return base64.b64encode(raw).decode('ascii')


def decode_binary(value):
    import base64
    return base64.b64decode(value, validate=True)


def project_artifact(model, template_path, temporary_root, review_decision):
    with tempfile.TemporaryDirectory(prefix='.projection-', dir=temporary_root) as temporary:
        path = Path(temporary)/'candidate.xlsx'
        write_workbook(template_path, dict(model), path)
        return canonical_json_bytes({'workbook':encode_binary(path.read_bytes()),
            'notes':render_model_notes(model,review_decision,load_task_standard_catalog(template_path))})


def calculate_artifact(projection, temporary_root):
    with tempfile.TemporaryDirectory(prefix='.calculation-', dir=temporary_root) as temporary:
        source = Path(temporary)/'candidate.xlsx'; target = Path(temporary)/'sow.xlsx'
        source.write_bytes(decode_binary(projection['workbook']))
        receipt = recalculate_workbook(source,target,require_office_engine())
        return canonical_json_bytes({'workbook':encode_binary(target.read_bytes()),'office':receipt.engine})


def verify_artifact(model, template_path, projection, calculated, reference, temporary_root):
    from dataclasses import asdict
    from office_engine import OfficeEngine, validate_office_identity
    from prior_state import inventory_prior_workbook
    from workbook import dual_reopen, visible_identity_rows, safe_text
    with tempfile.TemporaryDirectory(prefix='.reopen-', dir=temporary_root) as temporary:
        root = Path(temporary)
        for name,value in [('projected',projection),('final',calculated),('reference',reference)]:
            (root/(name+'.xlsx')).write_bytes(decode_binary(value['workbook']))
        office = validate_office_identity(calculated['office'])
        if office != reference['office']: raise ValueError('independent Office identity changed')
        report = dual_reopen(root/'final.xlsx',root/'projected.xlsx')
        audit = audit_calculated_workbook(root/'final.xlsx', template_path, dict(model),
            OfficeEngine(office['executableBasename'],'LibreOffice',office['version']),
            expected_layout_path=root/'projected.xlsx',reference_path=root/'reference.xlsx')
        inventory = inventory_prior_workbook(root/'final.xlsx')
        actual_rows = [tuple(cell['value'] for cell in e['canonicalCellValues']) for e in inventory['evidence']
            if e['sheet']=='03-工作量汇总']
        expected_rows = [tuple(safe_text(value) for value in row) for row in visible_identity_rows(model)]
        for row in expected_rows:
            if actual_rows.count(row) != 1: raise ValueError('visible Prior identity/source reference round-trip mismatch')
        return canonical_json_bytes({'trustState':'VERIFIED','office':office,'structureFormula':report,
            'audit':asdict(audit),'visibleIdentitySha256':sha256_bytes(canonical_json_bytes(expected_rows)),
            'workbookSha256':sha256_bytes(decode_binary(calculated['workbook']))})


def render_artifact(calculated, temporary_root):
    with tempfile.TemporaryDirectory(prefix='.renders-',dir=temporary_root) as temporary:
        root = Path(temporary); path = root/'sow.xlsx'; path.write_bytes(decode_binary(calculated['workbook']))
        renders = render_visible_sheets(path,root/'renders')
        return canonical_json_bytes({'renders':[{**item,'bytes':encode_binary((root/'renders'/item['path']).read_bytes())} for item in renders]})
