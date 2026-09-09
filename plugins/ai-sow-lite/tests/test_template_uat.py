"""Manual template layout and estimation; no plugin workflow is involved."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from zipfile import ZipFile
import xml.etree.ElementTree as ET


TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "sow-template.xlsx"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
TAG = "{" + NS["s"] + "}"


def xml_parts(path):
    with ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def read_cells(parts, sheet):
    strings = []
    if "xl/sharedStrings.xml" in parts:
        strings = ["".join(node.itertext()) for node in ET.fromstring(parts["xl/sharedStrings.xml"])]
    result = {}
    for cell in ET.fromstring(parts[f"xl/worksheets/sheet{sheet}.xml"]).findall("s:sheetData/s:row/s:c", NS):
        value = cell.find("s:v", NS)
        if cell.get("t") == "inlineStr":
            text = "".join(node.text or "" for node in cell.iter(TAG + "t"))
        elif cell.get("t") == "s" and value is not None:
            text = strings[int(value.text)]
        else:
            text = value.text if value is not None else None
        result[cell.get("r")] = (cell, text)
    return result


def set_text(sheet, address, value):
    data = sheet.find("s:sheetData", NS)
    row_number = int("".join(filter(str.isdigit, address)))
    row = next((row for row in data if int(row.get("r")) == row_number), None)
    if row is None:
        row = ET.SubElement(data, TAG + "row", r=str(row_number))
    cell = next((cell for cell in row if cell.get("r") == address), None)
    if cell is None:
        cell = ET.SubElement(row, TAG + "c", r=address)
    for child in list(cell):
        cell.remove(child)
    cell.set("t", "inlineStr")
    ET.SubElement(ET.SubElement(cell, TAG + "is"), TAG + "t").text = value


def discard_formula_caches(parts):
    # Fixtures change inputs outside Excel. Old cached totals are no longer valid;
    # LibreOffice's XLSX import may otherwise reuse them even with fullCalcOnLoad.
    for number in range(1, 5):
        name = f"xl/worksheets/sheet{number}.xml"
        sheet = ET.fromstring(parts[name])
        for cell in sheet.findall("s:sheetData/s:row/s:c", NS):
            if cell.find("s:f", NS) is not None:
                for value in cell.findall("s:v", NS):
                    cell.remove(value)
        parts[name] = ET.tostring(sheet)


class TemplateUatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parts = xml_parts(TEMPLATE)

    def test_catalog_has_explicit_flags_and_representative_boundaries(self):
        cells = read_cells(self.parts, 4)
        table = ET.fromstring(self.parts["xl/tables/table5.xml"])
        self.assertEqual(table.get("ref"), "A4:R92")
        self.assertEqual(cells["R4"][1], "UAT适用")
        flags = {cells[f"A{r}"][1]: cells[f"R{r}"][1] for r in range(5, 93)}
        self.assertEqual(len(flags), 88)
        self.assertEqual(set(flags.values()), {"是", "否"})
        for key in ["FE-VIEW", "FE-QUERY-API", "CO-TECH-COMPONENT", "IN-INTEGRATION", "AI-CAPABILITY"]:
            with self.subTest(key=key):
                self.assertEqual(flags[key], "是")
        for key in ["AN-DESIGN", "AN-POC", "AN-SPIKE", "ENG-RUNTIME", "REL-EXECUTION", "TEST-API", "ENG-PLATFORM", "AI-EVALUATION"]:
            with self.subTest(key=key):
                self.assertEqual(flags[key], "否")

    def test_sit_catalog_and_shifted_story_columns(self):
        catalog = read_cells(self.parts, 4)
        self.assertEqual(catalog["Q4"][1], "SIT适用")
        self.assertEqual(catalog["R4"][1], "UAT适用")
        actual = {catalog[f"A{r}"][1] for r in range(5, 93) if catalog[f"Q{r}"][1] == "是"}
        self.assertEqual(actual, {"IN-INTEGRATION", "IN-IDENTITY"})
        for r in range(5, 93):
            self.assertEqual(catalog[f"Q{r}"][1], "是" if catalog[f"B{r}"][1] == "系统集成" else "否")
        self.assertEqual(catalog["Q3"][0].get("s"), catalog["R3"][0].get("s"))
        story = read_cells(self.parts, 1)
        self.assertEqual([story[f"{col}4"][1] for col in "DEFGHIJ"],
                         ["验收条件", "备注", "SIT适用", "UAT适用", "任务列表", "故事人天", "校验结果"])
        self.assertIn("TaskStandardTable[SIT适用]", story["F5"][0].find("s:f", NS).text)
        self.assertIn("TaskStandardTable[UAT适用]", story["G5"][0].find("s:f", NS).text)
        self.assertEqual(story["H5"][0].find("s:f", NS).get("ref"), "H5")
        self.assertEqual(ET.fromstring(self.parts["xl/tables/table1.xml"]).get("ref"), "A4:J64")

    def test_story_column_is_formula_only_and_protected(self):
        sheet = ET.fromstring(self.parts["xl/worksheets/sheet1.xml"])
        styles = ET.fromstring(self.parts["xl/styles.xml"]).find("s:cellXfs", NS)
        cells = read_cells(self.parts, 1)
        self.assertEqual(sheet.find("s:sheetProtection", NS).get("sheet"), "1")
        for address in [f"{col}{r}" for col in "FG" for r in range(5, 65)]:
            cell = cells[address][0]
            self.assertIsNotNone(cell.find("s:f", NS))
            protection = styles[int(cell.get("s", "0"))].find("s:protection", NS)
            self.assertTrue(protection is None or protection.get("locked", "1") == "1")
        for r in [5, 35, 64]:
            for col in "ABCDE":
                cell = cells[f"{col}{r}"][0]
                self.assertIsNone(cell.find("s:f", NS))
                protection = styles[int(cell.get("s", "0"))].find("s:protection", NS)
                self.assertEqual(protection.get("locked"), "0")
        for validation in sheet.findall("s:dataValidations/s:dataValidation", NS):
            self.assertNotIn("F5:F1048576", validation.get("sqref", ""))
            self.assertNotIn("G5:G1048576", validation.get("sqref", ""))
        table = ET.fromstring(self.parts["xl/tables/table1.xml"])
        uat = next(c for c in table.find("s:tableColumns", NS) if c.get("name") == "UAT适用")
        self.assertIsNotNone(uat.find("s:calculatedColumnFormula", NS))

    def test_manual_template_has_no_hidden_rows_columns_or_sheets(self):
        workbook = ET.fromstring(self.parts["xl/workbook.xml"])
        self.assertTrue(all(s.get("state", "visible") == "visible" for s in workbook.find("s:sheets", NS)))
        for number in range(1, 5):
            sheet = ET.fromstring(self.parts[f"xl/worksheets/sheet{number}.xml"])
            for node in sheet.findall("s:cols/s:col", NS) + sheet.findall("s:sheetData/s:row", NS):
                self.assertNotEqual(node.get("hidden"), "1")
                self.assertEqual(node.get("outlineLevel", "0"), "0")
        table = ET.fromstring(self.parts["xl/tables/table2.xml"])
        self.assertEqual(table.get("ref"), "A4:L204")
        headers = {c.get("name") for c in table.find("s:tableColumns", NS)}
        self.assertNotIn("工作类型ID", headers)
        self.assertNotIn("UAT适用", headers)

    def test_manual_inputs_remain_editable_and_results_locked(self):
        cells = read_cells(self.parts, 2)
        styles = ET.fromstring(self.parts["xl/styles.xml"]).find("s:cellXfs", NS)
        for r in [5, 100, 204]:
            for col in "ABCDEFG":
                cell = cells[f"{col}{r}"][0]
                protection = styles[int(cell.get("s", "0"))].find("s:protection", NS)
                self.assertIsNotNone(protection)
                self.assertEqual(protection.get("locked"), "0")
            for col in "HIJKL":
                cell = cells[f"{col}{r}"][0]
                self.assertIsNotNone(cell.find("s:f", NS))
                protection = styles[int(cell.get("s", "0"))].find("s:protection", NS)
                self.assertTrue(protection is None or protection.get("locked", "1") == "1")

    def test_visible_standards_and_parameters_are_the_only_sources(self):
        standard = read_cells(self.parts, 4)
        for r in range(5, 93):
            for col in "ABCDEFGHIJKLMNOPQR":
                self.assertIsNone(standard[f"{col}{r}"][0].find("s:f", NS))
        self.assertEqual(standard["L4"][1], "S（简单）")
        self.assertEqual(standard["O4"][1], "X / 拆分条件")
        self.assertEqual(standard["Q3"][0].get("s"), standard["A3"][0].get("s"))
        parameter = ET.fromstring(self.parts["xl/tables/table4.xml"])
        self.assertEqual(parameter.get("ref"), "A12:C20")
        summary = read_cells(self.parts, 3)
        self.assertEqual(float(summary["B16"][1]), 0.05)
        for r in range(13, 21):
            self.assertIsNone(summary[f"B{r}"][0].find("s:f", NS))
        # Summary rows have different formulas, not one table-wide column formula.
        summary_table = ET.fromstring(self.parts["xl/tables/table3.xml"])
        self.assertFalse(summary_table.findall("s:tableColumns/s:tableColumn/s:calculatedColumnFormula", NS))

    def test_uat_table_metadata_uses_the_native_row_formula(self):
        # Excel repaired the workbook when these metadata formulas used [@...]
        # shorthand, although cell calculation and LibreOffice tests passed.
        # Keep the same A1 formula convention as the template's other columns.
        for table_number, sheet_number, address in [(1, 1, "F5"), (1, 1, "G5")]:
            with self.subTest(table=table_number):
                table = ET.fromstring(self.parts[f"xl/tables/table{table_number}.xml"])
                column = next(c for c in table.find("s:tableColumns", NS) if c.get("name") == ("SIT适用" if address == "F5" else "UAT适用"))
                metadata = column.find("s:calculatedColumnFormula", NS).text
                cell_formula = read_cells(self.parts, sheet_number)[address][0].find("s:f", NS).text
                self.assertEqual(metadata, cell_formula)
                self.assertNotIn("[@", metadata)

    def test_manual_estimation_and_summary_recalculate(self):
        office = os.environ.get("AI_SOW_LITE_SOFFICE") or shutil.which("soffice")
        if not office:
            mac = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
            office = str(mac) if mac.exists() else None
        if not office:
            self.skipTest("LibreOffice is required for native formula recalculation")
        parts = dict(self.parts)
        catalog = read_cells(parts, 4)
        names = {catalog[f"A{r}"][1]: catalog[f"C{r}"][1] for r in range(5, 93)}
        story = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
        task = ET.fromstring(parts["xl/worksheets/sheet2.xml"])
        for row, title in [(5, "功能切片"), (6, "设计切片")]:
            for col, value in {"A": "测试需求", "B": "估算", "C": title, "D": "测试验收条件"}.items():
                set_text(story, f"{col}{row}", value)
        rows = [
            ("功能切片", "页面调整", "FE-VIEW", "调整", "S", ""),
            ("功能切片", "内部集成", "IN-INTEGRATION", "新建", "S", "内部集成"),
            ("功能切片", "外部集成", "IN-INTEGRATION", "调整", "L", "外部集成"),
            ("设计切片", "设计工作", "AN-DESIGN", "新建", "M", ""),
            ("设计切片", "不适用工作方式", "AN-DESIGN", "接入复用", "M", ""),
        ]
        for row, values in enumerate(rows, 5):
            for col, value in zip("ABCDEF", values):
                set_text(task, f"{col}{row}", names[value] if col == "C" else value)
        parts["xl/worksheets/sheet1.xml"] = ET.tostring(story)
        parts["xl/worksheets/sheet2.xml"] = ET.tostring(task)
        discard_formula_caches(parts)
        with tempfile.TemporaryDirectory(prefix="ai-sow-lite-estimation-test-") as tmp:
            tmp = Path(tmp)
            fixture = tmp / "manual.xlsx"
            out = tmp / "calculated"
            out.mkdir()
            with ZipFile(fixture, "w") as archive:
                for name, value in parts.items():
                    archive.writestr(name, value)
            result = subprocess.run([office, "--headless", "-env:UserInstallation=" + (tmp / "profile").as_uri(), "--convert-to", "xlsx", "--outdir", str(out), str(fixture)], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((out / fixture.name).exists(), result.stdout + result.stderr)
            calculated = xml_parts(out / fixture.name)
        tasks = read_cells(calculated, 2)
        for address, value in {"J5": 0.6, "J6": 1.8, "J7": 3, "J8": 2, "K6": 0.3, "K7": 1.5}.items():
            self.assertAlmostEqual(float(tasks[address][1]), value)
        self.assertFalse(tasks["J9"][1], "Unsupported work mode must not produce an estimate")
        self.assertEqual(tasks["L9"][1], "工作类型与工作方式不适用")
        summary = read_cells(calculated, 3)
        for address, value in {"B5": 7.4, "B6": 2, "B7": 0.5, "B8": 9.9}.items():
            self.assertAlmostEqual(float(summary[address][1]), value)

    def test_formulas_recalculate_in_office_engine(self):
        office = os.environ.get("AI_SOW_LITE_SOFFICE") or shutil.which("soffice")
        if not office:
            mac = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
            office = str(mac) if mac.exists() else None
        if not office:
            self.skipTest("LibreOffice is required for native formula recalculation")
        parts = dict(self.parts)
        catalog = read_cells(parts, 4)
        names = {catalog[f"A{r}"][1]: catalog[f"C{r}"][1] for r in range(5, 93)}
        story = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
        task = ET.fromstring(parts["xl/worksheets/sheet2.xml"])
        cases = [
            ("设计与部署", ["AN-DESIGN", "AN-POC", "AN-SPIKE", "ENG-RUNTIME"], "否"),
            ("业务接口", ["FE-QUERY-API"], "是"),
            ("页面", ["FE-VIEW"], "是"),
            ("公共能力", ["CO-TECH-COMPONENT"], "是"),
            ("混合交付", ["AN-DESIGN", "FE-COMMAND-API", "ENG-RUNTIME"], "是"),
            ("只有未知类型", [None], None),
            ("非适用与未知", ["AN-POC", "MISSING-TYPE"], None),
            ("适用与未知", ["FE-VIEW", None], "是"),
            ("尚无任务", [], None),
            ("名称*?~", ["AN-DESIGN"], "否"),
            ("名称ABC", ["FE-VIEW"], "是"),
            ("集成与未知", ["IN-INTEGRATION", None], "是"),
            ("账号集成", ["IN-IDENTITY"], "是"),
        ]
        task_row = 5
        task_rows = {}
        for story_row, (title, types, expected) in enumerate(cases, 5):
            task_rows[title] = []
            for column, value in {"A": "测试需求", "B": "测试子需求", "C": title, "D": "仅用于公式验证"}.items():
                set_text(story, f"{column}{story_row}", value)
            for kind in types:
                task_rows[title].append(task_row)
                values = {"A": title, "B": f"任务-{task_row}", "D": "新建", "E": "M"}
                if kind is not None:
                    values["C"] = names.get(kind, "不在目录中的类型")
                for column, value in values.items():
                    set_text(task, f"{column}{task_row}", value)
                task_row += 1
        # A final populated row guards against formulas only working near the top.
        for column, value in {"A": "测试需求", "B": "末行", "C": "末行故事", "D": "末行验收"}.items():
            set_text(story, f"{column}64", value)
        for column, value in {"A": "末行故事", "B": "末行任务", "C": names["FE-VIEW"], "D": "调整", "E": "S"}.items():
            set_text(task, f"{column}204", value)
        parts["xl/worksheets/sheet1.xml"] = ET.tostring(story)
        parts["xl/worksheets/sheet2.xml"] = ET.tostring(task)
        with tempfile.TemporaryDirectory(prefix="ai-sow-lite-uat-test-") as tmp:
            tmp = Path(tmp)
            out = tmp / "calculated"
            out.mkdir()

            def recalculate(filename):
                fixture = tmp / filename
                discard_formula_caches(parts)
                with ZipFile(fixture, "w") as archive:
                    for name, value in parts.items():
                        archive.writestr(name, value)
                result = subprocess.run([office, "--headless", "-env:UserInstallation=" + (tmp / "profile").as_uri(), "--convert-to", "xlsx", "--outdir", str(out), str(fixture)], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                calculated = out / fixture.name
                self.assertTrue(calculated.exists(), result.stdout + result.stderr)
                data = xml_parts(calculated)
                computed_tasks = read_cells(data, 2)
                self.assertEqual(float(computed_tasks["J204"][1]), 0.6)
                return read_cells(data, 1)

            actual = recalculate("uat-cases.xlsx")
            for r, (title, _, expected) in enumerate(cases, 5):
                with self.subTest(title=title):
                    self.assertEqual(actual[f"G{r}"][1] or None, expected)
            expected_sit = ["否", "否", "否", "否", "否", None, None, None, None, "否", "否", "是", "是"]
            for r, expected in enumerate(expected_sit, 5):
                self.assertEqual(actual[f"F{r}"][1] or None, expected)
            self.assertEqual(actual["F64"][1], "否")
            self.assertFalse(actual["F63"][1])
            self.assertEqual(actual["G64"][1], "是")
            self.assertEqual(float(actual["I64"][1]), 1.0)
            self.assertFalse(actual["G63"][1])
            self.assertFalse(actual["J63"][1], "Empty rows must not become mandatory-field errors because F/G contain formulas")

            # Editing a type or moving a task must change only its related Stories.
            set_text(task, f"C{task_rows['设计与部署'][0]}", names["FE-VIEW"])
            set_text(task, f"C{task_rows['业务接口'][0]}", names["AN-DESIGN"])
            set_text(task, f"A{task_rows['页面'][0]}", "尚无任务")
            set_text(task, f"C{task_rows['账号集成'][0]}", names["AN-DESIGN"])
            set_text(task, f"A{task_rows['集成与未知'][0]}", "尚无任务")
            parts["xl/worksheets/sheet2.xml"] = ET.tostring(task)
            changed = recalculate("uat-edited.xlsx")
            self.assertEqual(changed["G5"][1], "是")
            self.assertEqual(changed["G6"][1], "否")
            self.assertFalse(changed["G7"][1])
            self.assertEqual(changed["G13"][1], "是")
            self.assertEqual(changed["G8"][1], actual["G8"][1])
            self.assertEqual(changed["F13"][1], "是")
            self.assertFalse(changed["F16"][1])
            self.assertEqual(changed["F17"][1], "否")
            # Removing the remaining unknown Task makes the original Story empty.
            for address in [f"{col}{task_rows['集成与未知'][1]}" for col in "ABCDEFG"]:
                set_text(task, address, "")
            parts["xl/worksheets/sheet2.xml"] = ET.tostring(task)
            removed = recalculate("applicability-deleted.xlsx")
            self.assertFalse(removed["F16"][1])
            self.assertFalse(removed["G16"][1])
            self.assertEqual(removed["F13"][1], "是")


if __name__ == "__main__":
    unittest.main()
