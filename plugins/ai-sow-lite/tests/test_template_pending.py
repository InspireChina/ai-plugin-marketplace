"""待确认校验的静态合同与模板保真检查；不执行 Office 或估算公式。

基线来自修改前模板（提交 76af1f9），SHA-256 为
6abc55d44bc66476a60c2251e18c0dfdb66709e07539c246dfdec3a0373f5332。
哈希只排除获准修改的校验公式及 A2 文本，独立插件副本无需 Git。
"""

import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile

import openpyxl
from openpyxl.formula import Tokenizer
from openpyxl.formula.translate import Translator
import pytest


TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "sow-template.xlsx"
CASES = [
    ("01-需求故事", "SOWStoryTable", "J", "E", 64),
    ("02-任务清单", "TaskTable", "L", "G", 204),
]
OLD_CHECKS = {
    "J": '=IF(COUNTA($A5:$C5,$D5:$E5)=0,"",'
         'IF(OR($A5="",$B5="",$C5="",$F5="",$G5="",$D5=""),"必填项缺失",'
         'IF(COUNTIF(SOWStoryTable[故事],$C5)>1,"故事名称重复",'
         'IF(OR(AND($F5<>"是",$F5<>"否"),AND($G5<>"是",$G5<>"否")),"SIT/UAT适用值非法",'
         'IF(COUNTIF(TaskTable[所属故事],$C5)=0,"故事缺少任务","通过")))))',
    "L": '=IF(COUNTA($A5:$G5)=0,"",'
         'IF(OR($A5="",$B5="",$C5="",$D5="",$E5=""),"必填项缺失",'
         'IF(SUMPRODUCT(--(TaskTable[任务名称]=$B5))>1,"任务名称重复",'
         'IF(SUMPRODUCT(--(SOWStoryTable[故事]=$A5))<>1,"所属故事未知",'
         'IF(NOT(OR($E5="S",$E5="M",$E5="L")),"复杂度非法",'
         'IF(NOT(OR($F5="",$F5="内部集成",$F5="外部集成")),"集成类型非法",'
         'IF(AND($F5<>"",NOT(IFERROR(INDEX(TaskStandardTable[分类],'
         'MATCH($C5,TaskStandardTable[工作类型],0)),"")="系统集成")),"非集成任务不应填写集成类型",'
         'IF(AND($F5="",IFERROR(INDEX(TaskStandardTable[分类],'
         'MATCH($C5,TaskStandardTable[工作类型],0)),"")="系统集成"),"集成类型缺失",'
         'IF(ISNUMBER($H5),"通过","工作类型与工作方式不适用")))))))))',
}

# 四个可变 XML member 的哈希排除指定文本；其余 member 使用原始字节。
BASELINE_PART_HASHES = {
    "docProps/app.xml": "209fca6b00afe72a5029754b94be5953d8f16d96f67130325566b9366ad4ccc5",
    "docProps/core.xml": "2cc07a028404b3e8f48b55a15f374d9193e6f5160c169777590a4f3a3a93586c",
    "xl/theme/theme1.xml": "d15e8ebf78ef7b9720839d7ae8fdc81a7df5bc24706d8e137df61a5683c358d9",
    "xl/worksheets/sheet1.xml": "458d2ad00e49c9cccce6ee962a57ffe092203d9fe616deae7f0c6617c8f3f912",
    "xl/tables/table1.xml": "bafa83a45c26bf93d518e6f2d58b1b7347f3ce9bd70b27bf5b6b003cecea1968",
    "xl/worksheets/_rels/sheet1.xml.rels": "681d47bfde53a64a4d120154996309825b3cea9948a67ddca790c561b2fe58f0",
    "xl/worksheets/sheet2.xml": "6a9dba3d6f18cedfe4f79045dc5daf26327575737fbb6b49d2c42faffe07b653",
    "xl/tables/table2.xml": "5042aa3bc7d6afffdd4d024040017e11ec5b3e1877e784f22e55263a505da13f",
    "xl/worksheets/_rels/sheet2.xml.rels": "68a90b8a0f300eda2f085604594237e2dad42becc9e3ad3523e8c1a043c5fb3b",
    "xl/worksheets/sheet3.xml": "efb849ef824cfb4a71c2a17c08f375377ef62987b25c9ac3983be7f33a60ee8a",
    "xl/tables/table3.xml": "20a6fe0a5da0aed3eb39ef37ddfc76d06dee1a0bd792f05a4403b525908f5595",
    "xl/worksheets/_rels/sheet3.xml.rels": "b5d2026d86f01194325ca818a79c46afa064f218f3186bc1e7fb0cbf34106c84",
    "xl/worksheets/sheet4.xml": "1b2119ed7a3e0f97e5cd2e0d6e2b9cace9ead0deac46fcf7e5760b222481f6de",
    "xl/tables/table4.xml": "5d019c315c75c438d188044c7e1c5d625bb8c3da66e0162f93f38f2851461859",
    "xl/tables/table5.xml": "34f1f06688c1ff5fe97b010bceded62d908d724c8b14b4fee05c2b0d776b7c7a",
    "xl/worksheets/_rels/sheet4.xml.rels": "ad1eb9c7249c192f9a26d9a007cf93028d4f70d63084634a6708ca49c11137c8",
    "xl/styles.xml": "2637e06233f3e01f15a76912cb5b15dc836826942a632f2e570653280dea62e9",
    "_rels/.rels": "ec869ae44fc833c25e58afa6ae766147aa72a99147522f6070e511475222827d",
    "xl/workbook.xml": "adb8eb4628ef60012c9f066c041567fc7a816756fdaf37cc2f4c310411bb34a3",
    "xl/_rels/workbook.xml.rels": "b3ea04c9752005fa1567bc19dfa9e8774191604cf38daeb9fc1eb945d68f15a0",
    "[Content_Types].xml": "a661bc124854a27a0e6e2a1bec4d60319f468360596aeca679fb5e7706f005f8",
}


@pytest.fixture(scope="module")
def book():
    workbook = openpyxl.load_workbook(TEMPLATE, data_only=False)
    yield workbook
    workbook.close()


def if_arguments(formula):
    """通过 openpyxl 词法分析提取 IF 的三个参数，不计算业务公式。"""
    tokens = Tokenizer("=" + formula.removeprefix("=")).items
    assert tokens[0].value == "IF("
    assert tokens[-1].value == ")"
    arguments = [""]
    depth = 0
    for token in tokens[1:-1]:
        if token.type == "SEP" and token.subtype == "ARG" and depth == 0:
            arguments.append("")
            continue
        arguments[-1] += token.value
        if token.subtype == "OPEN":
            depth += 1
        elif token.subtype == "CLOSE":
            depth -= 1
    assert depth == 0
    assert len(arguments) == 3
    return arguments


@pytest.mark.parametrize("sheet,table,column,note,last", CASES)
def test_empty_then_pending_then_original_validation_on_every_row(book, sheet, table, column, note, last):
    for row in range(5, last + 1):
        address = f"{column}{row}"
        old = Translator(OLD_CHECKS[column], origin=f"{column}5").translate_formula(address)
        old_args = if_arguments(old)
        actual_args = if_arguments(book[sheet][address].value)
        assert actual_args[:2] == old_args[:2], address
        # 待确认位于必填/分类/AC 等原校验之前；else 原样保留所有错误检查。
        assert if_arguments(actual_args[2]) == [
            f'LEFT(${note}{row},4)="待确认："', '"待确认"', old_args[2],
        ], address


@pytest.mark.parametrize("sheet,table,column,note,last", CASES)
@pytest.mark.parametrize("text,pending", [
    (None, False), ("", False), ("普通备注", False), ("无需待确认", False),
    ("说明：待确认：分类", False), (" 待确认：分类", False),
    ("待确认:分类", False), ("待确认", False),
    ("待确认：", True), ("待确认：分类与验收条件由用户确认", True),
])
def test_exact_prefix_does_not_match_ordinary_sentences(book, sheet, table, column, note, last, text, pending):
    condition = if_arguments(if_arguments(book[sheet][f"{column}5"].value)[2])[0]
    match = re.fullmatch(r'LEFT\((\$[EG]5),(\d+)\)="([^"]*)"', condition)
    assert match is not None
    assert match.group(1) == f"${note}5"
    # 仅解释已验证的 LEFT 谓词；空行和 else 优先级由完整结构测试覆盖。
    assert ((text or "")[:int(match.group(2))] == match.group(3)) is pending


@pytest.mark.parametrize("sheet,table,column,note,last", CASES)
def test_table_metadata_matches_native_row_formula(book, sheet, table, column, note, last):
    metadata = next(c for c in book[sheet].tables[table].tableColumns if c.name == "校验结果")
    formula = metadata.calculatedColumnFormula
    assert formula.text == book[sheet][f"{column}5"].value.removeprefix("=")
    assert if_arguments(if_arguments(formula.text)[2])[0] == f'LEFT(${note}5,4)="待确认："'
    assert "[@" not in formula.text


@pytest.mark.parametrize("sheet,table,column,note,last", CASES)
def test_normal_notes_are_blank_and_guidance_has_no_fixed_bullet(book, sheet, table, column, note, last):
    assert all(book[sheet][f"{note}{row}"].value is None for row in range(5, last + 1))
    guidance = book[sheet]["A2"].value
    assert "无待确认事项时备注留空" in guidance
    assert "待确认事项以‘待确认：’开头写备注" in guidance
    assert "校验结果" in guidance
    assert "通用事项留在说明" not in guidance
    assert "•" not in guidance


def test_all_other_formulas_keep_original_values_and_all_formulas_are_locked(book):
    untouched = []
    for sheet in book:
        for row in sheet:
            for cell in row:
                if cell.data_type != "f":
                    continue
                assert sheet.protection.sheet, sheet.title
                assert cell.protection.locked, (sheet.title, cell.coordinate)
                if any(sheet.title == sn and cell.column_letter == col and 5 <= cell.row <= last
                       for sn, _, col, _, last in CASES):
                    continue
                value = cell.value
                if not isinstance(value, str):
                    value = {"text": value.text, "ref": value.ref}
                untouched.append([sheet.title, cell.coordinate, value])
    data = json.dumps(untouched, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(untouched) == 1044
    assert hashlib.sha256(data).hexdigest() == "3bac55eb55417fda61d24806ab9fa3a56aa648e46073e25277f7a7fbbde8a815"


def exclude_authorized_text(name, data):
    """仅遮蔽获准文本，保留 XML 标签、属性及其他内容的原始字节。"""
    for number, (_, _, column, _, last) in enumerate(CASES, 1):
        if name == f"xl/worksheets/sheet{number}.xml":
            for row in range(5, last + 1):
                pattern = (rb'(<s:c\b[^>]*\br="' + f"{column}{row}".encode()
                           + rb'"[^>]*><s:f[^>]*>).*?(</s:f>)')
                data, count = re.subn(pattern, rb"\1FORMULA\2", data)
                assert count == 1, (name, row)
            data, count = re.subn(
                rb'(<s:c\b[^>]*\br="A2"[^>]*><s:v>).*?(</s:v>)', rb"\1GUIDANCE\2", data,
            )
            assert count == 1, name
        elif name == f"xl/tables/table{number}.xml":
            column_id = b"10" if number == 1 else b"12"
            pattern = (rb'(<tableColumn\b[^>]*\bid="' + column_id
                       + rb'"[^>]*><calculatedColumnFormula[^>]*>).*?(</calculatedColumnFormula>)')
            data, count = re.subn(pattern, rb"\1FORMULA\2", data)
            assert count == 1, name
    return data


def test_zip_preserves_all_other_data_styles_cf_dimensions_and_tables():
    with ZipFile(TEMPLATE) as archive:
        assert archive.testzip() is None
        assert archive.namelist() == list(BASELINE_PART_HASHES)
        for name, digest in BASELINE_PART_HASHES.items():
            data = exclude_authorized_text(name, archive.read(name))
            assert hashlib.sha256(data).hexdigest() == digest, name
