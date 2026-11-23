"""生成三份合成原始单证：Excel 发票 / PDF 报关单 / 扫描件装箱单。

用途：在没有真实业务文件的情况下，先验证「原始文件 → 抽取 → 五单 JSON → 审核」
这条链路。所有内容取自 examples/realistic 的合成数据，不含任何真实企业信息。

依赖：openpyxl、Pillow（合成渲染工具），以及本机 Edge（无头转 PDF / 截图）。
运行：
    python scripts/gen_synthetic_rawdocs.py
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "examples" / "realistic" / "REAL-002-amount-mismatch-FIX.json"
OUT = ROOT / "examples" / "raw"

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

FONT_CN = "Microsoft YaHei"


def find_edge() -> str:
    for p in EDGE_CANDIDATES:
        if os.path.exists(p):
            return p
    found = shutil.which("msedge")
    if found:
        return found
    raise SystemExit("未找到 Edge，无法生成 PDF/图片")


# ---------------- Excel 发票 ----------------
def build_invoice_xlsx(inv: dict, out: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "商业发票"

    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="DDEBF7")
    title_font = Font(name=FONT_CN, size=16, bold=True)
    label_font = Font(name=FONT_CN, size=10, bold=True)
    body_font = Font(name=FONT_CN, size=10)

    widths = [8, 22, 16, 24, 10, 8, 12, 14]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.merge_cells("A1:H1")
    ws["A1"] = "商业发票  COMMERCIAL INVOICE"
    ws["A1"].font = title_font
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    ws.merge_cells("A2:H2")
    ws["A2"] = "（合成数据，仅用于系统测试，不含真实企业信息）"
    ws["A2"].font = Font(name=FONT_CN, size=9, color="808080")
    ws["A2"].alignment = Alignment(horizontal="center")

    header = [
        ("发票号 Invoice No.", inv["invoice_no"], "日期 Date", inv["date"]),
        ("合同号 Contract No.", inv["contract_no"], "币制 Currency", inv["currency"]),
        ("卖方 Seller", inv["seller"], "成交方式 Incoterm", inv["incoterm"]),
        ("买方 Buyer", inv["buyer"], "付款方式 Payment", "T/T 30 days"),
    ]
    r = 4
    for k1, v1, k2, v2 in header:
        ws.cell(r, 1, k1).font = label_font
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        ws.cell(r, 3, v1).font = body_font
        ws.merge_cells(start_row=r, start_column=3, end_row=r, end_column=4)
        ws.cell(r, 5, k2).font = label_font
        ws.merge_cells(start_row=r, start_column=5, end_row=r, end_column=6)
        ws.cell(r, 7, v2).font = body_font
        ws.merge_cells(start_row=r, start_column=7, end_row=r, end_column=8)
        for c in range(1, 9):
            ws.cell(r, c).border = border
            ws.cell(r, c).alignment = Alignment(vertical="center")
        r += 1

    r += 1
    cols = ["序号", "品名 Description", "规格/型号", "HS 编码", "数量", "单位", "单价", "金额"]
    for i, name in enumerate(cols, 1):
        cell = ws.cell(r, i, name)
        cell.font = label_font
        cell.fill = head_fill
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center")
    r += 1

    for idx, it in enumerate(inv["items"], 1):
        vals = [idx, it["name"], it.get("elements", {}).get("spec", "通用"),
                it["hs_code"], it["qty"], it["unit"], it["unit_price"], it["amount"]]
        for i, v in enumerate(vals, 1):
            cell = ws.cell(r, i, v)
            cell.font = body_font
            cell.border = border
            if i in (5, 7, 8):
                cell.number_format = "0.00" if i != 5 else "0"
                cell.alignment = Alignment(horizontal="right")
        r += 1

    summary = [
        ("折扣 Discount", inv.get("discount", 0.0)),
        ("佣金 Commission", inv.get("commission", 0.0)),
        ("特许权使用费 Royalty", inv.get("royalty", 0.0)),
        ("发票总额 Total Amount", inv["total_amount"]),
    ]
    for label, value in summary:
        ws.cell(r, 6, label).font = label_font
        ws.merge_cells(start_row=r, start_column=6, end_row=r, end_column=7)
        ws.cell(r, 8, value).font = label_font if "总额" in label else body_font
        ws.cell(r, 8).number_format = "0.00"
        ws.cell(r, 8).alignment = Alignment(horizontal="right")
        for c in range(6, 9):
            ws.cell(r, c).border = border
        r += 1

    ws.cell(r + 1, 1, "条款 Terms：FOB SINGAPORE").font = body_font
    ws.cell(r + 2, 1, "备注 Remark：合成单证，供系统识别与审核演练使用。").font = body_font

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)


# ---------------- Excel 五单（一个工作簿五个 sheet） ----------------
def _xlsx_kv_sheet(wb, sheet_name: str, title: str, pairs: list[tuple[str, str]],
                   item_headers: list[str] | None = None,
                   item_rows: list[list] | None = None,
                   summary: list[tuple[str, object]] | None = None) -> None:
    """按「标签 | 值」两列一组铺单头，再按需铺明细表与汇总行。

    合并单元格是故意留的：Excel 适配器要先展开合并区域再取值。
    """
    ws = wb.create_sheet(sheet_name)

    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="DDEBF7")
    label_font = Font(name=FONT_CN, size=10, bold=True)
    body_font = Font(name=FONT_CN, size=10)

    for i, width in enumerate([10, 24, 16, 22, 10, 8, 12, 14, 30], 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    ws.merge_cells("A1:I1")
    ws["A1"] = title
    ws["A1"].font = Font(name=FONT_CN, size=15, bold=True)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    r = 3
    for i, (label, value) in enumerate(pairs):
        row = r + i // 2
        col = 1 if i % 2 == 0 else 5
        ws.cell(row, col, label).font = label_font
        ws.merge_cells(start_row=row, start_column=col,
                       end_row=row, end_column=col + 1)
        ws.cell(row, col + 2, value).font = body_font
        ws.merge_cells(start_row=row, start_column=col + 2,
                       end_row=row, end_column=col + 3)
        for c in range(col, col + 4):
            ws.cell(row, c).border = border
    r = r + (len(pairs) + 1) // 2

    if item_headers:
        r += 1
        for i, name in enumerate(item_headers, 1):
            cell = ws.cell(r, i, name)
            cell.font = label_font
            cell.fill = head_fill
            cell.border = border
            cell.alignment = Alignment(horizontal="center", vertical="center")
        r += 1
        for values in item_rows or []:
            for i, value in enumerate(values, 1):
                cell = ws.cell(r, i, value)
                cell.font = body_font
                cell.border = border
            r += 1

    for label, value in summary or []:
        ws.cell(r, 6, label).font = label_font
        ws.merge_cells(start_row=r, start_column=6, end_row=r, end_column=7)
        ws.cell(r, 8, value).font = label_font
        ws.cell(r, 8).number_format = "0.00"
        ws.cell(r, 8).alignment = Alignment(horizontal="right")
        for c in range(6, 9):
            ws.cell(r, c).border = border
        r += 1

    ws.cell(r + 1, 1, "备注 Remark：合成数据，仅用于系统测试，不含真实企业信息。").font = \
        Font(name=FONT_CN, size=9, color="808080")


def _doc_item_row(it: dict) -> list:
    elements = it.get("elements") or {}
    return [1, it["name"], it["hs_code"], it["qty"], it["unit"], it["unit_price"],
            it["amount"], f'{it.get("legal_unit1", "个")}/{it.get("legal_unit2", "千克")}',
            "|".join(f"{k}={v}" for k, v in elements.items())]


def build_five_xlsx(data: dict, out: Path) -> None:
    """一个工作簿五个 sheet：合同 / 发票 / 装箱单 / 提单 / 报关单。

    用于验证「多 sheet 逐张判类型」和「纯 Excel 端到端」；数据与五份 PDF 同源。
    """
    c, inv, p, b, d = (data["contract"], data["invoice"], data["packing_list"],
                       data["bl"], data["declaration"])
    it = inv["items"][0]

    wb = Workbook()
    wb.remove(wb.active)

    _xlsx_kv_sheet(wb, "合同", "合 同  CONTRACT", [
        ("合同号", c["contract_no"]), ("日期", c["date"]),
        ("卖方", c["seller"]), ("买方", c["buyer"]),
        ("币制", c["currency"]), ("成交方式", c["incoterm"]),
        ("合同总额", c["total_amount"]), ("条款", c["terms"]),
        ("付款方式", c["payment"]),
    ])

    _xlsx_kv_sheet(wb, "商业发票", "商 业 发 票  COMMERCIAL INVOICE", [
        ("发票号", inv["invoice_no"]), ("合同号", inv["contract_no"]),
        ("发票日期", inv["date"]), ("卖方", inv["seller"]),
        ("买方", inv["buyer"]), ("币制", inv["currency"]),
        ("成交方式", inv["incoterm"]), ("付款方式", "T/T 30 days"),
    ], item_headers=["序号", "品名", "规格/型号", "HS 编码", "数量", "单位", "单价", "金额"],
       item_rows=[[1, it["name"], it.get("elements", {}).get("spec", "通用"),
                   it["hs_code"], it["qty"], it["unit"],
                   it["unit_price"], it["amount"]]],
       summary=[("折扣 Discount", inv.get("discount", 0.0)),
                ("佣金 Commission", inv.get("commission", 0.0)),
                ("特许权使用费 Royalty", inv.get("royalty", 0.0)),
                ("发票总额 Total Amount", inv["total_amount"])])

    _xlsx_kv_sheet(wb, "装箱单", "装 箱 单  PACKING LIST", [
        ("装箱单号", p["pl_no"]), ("日期", p["date"]),
        ("件数", p["packages"]), ("包装种类", p["package_type"]),
        ("毛重", p["gross_weight"]), ("净重", p["net_weight"]),
        ("体积", p["volume"]), ("唛头", f'{p["marks"]["port"]} / {p["marks"]["text"]}'),
        ("木包装", "是" if p.get("wood_packaging") else "否"),
    ], item_headers=ITEM_COLS, item_rows=[_doc_item_row(p["items"][0])])

    _xlsx_kv_sheet(wb, "提单", "提 单  BILL OF LADING", [
        ("提单号", b["bl_no"]), ("日期", b["date"]),
        ("到港日", b["arrival_date"]), ("船名", b["vessel"]),
        ("航次", b["voyage"]), ("起运港", b["pol"]),
        ("目的港", b["pod"]), ("发货人", b["shipper"]),
        ("收货人", b["consignee"]), ("通知人", b["notify"]),
        ("件数", b["packages"]), ("毛重", b["gross_weight"]),
        ("体积", b.get("volume", 0)),
    ], item_headers=ITEM_COLS, item_rows=[_doc_item_row(b["items"][0])])

    _xlsx_kv_sheet(wb, "报关单", "中华人民共和国海关进口货物报关单", [
        ("报关单号", d["decl_no"]), ("申报日期", d["declare_date"]),
        ("收发货人", d["consignee"]), ("运输方式", d["transport_mode"]),
        ("贸易方式", d["trade_mode"]), ("征免性质", d["exemption_nature"]),
        ("启运国", d["origin_country"]), ("装货港", d["loading_port"]),
        ("境内目的地", d["destination"]), ("成交方式", d["incoterm"]),
        ("币制", d["currency"]), ("运费", d.get("freight", 0.0)),
        ("保费", d.get("insurance", 0.0)), ("合同号", d["contract_no"]),
        ("提单号", d["bl_no"]), ("件数", d.get("packages", "")),
        ("毛重", d.get("gross_weight", "")), ("净重", d.get("net_weight", "")),
        ("总价", d["total_amount"]), ("许可证号", d.get("license_no") or "无"),
        ("证书号", d.get("cert_no") or "无"),
    ], item_headers=ITEM_COLS, item_rows=[_doc_item_row(d["items"][0])])

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)


# ---------------- HTML 公共 ----------------
CSS = """
@page { size: A4; margin: 12mm; }
* { box-sizing: border-box; }
body { font-family: "%s", "SimSun", sans-serif; color:#111; font-size: 11px; margin:0; }
.doc { border: 2px solid #222; padding: 10px 12px; }
.title { text-align:center; font-size: 20px; font-weight:700; letter-spacing: 2px; margin: 2px 0 2px; }
.sub { text-align:center; font-size: 9px; color:#666; margin-bottom: 8px; }
.grid { display:grid; grid-template-columns: repeat(6, 1fr); border-top:1px solid #333; border-left:1px solid #333; }
.cell { border-right:1px solid #333; border-bottom:1px solid #333; padding:3px 5px; min-height:20px; }
.k { background:#eef3f9; font-weight:600; white-space:nowrap; }
.span2 { grid-column: span 2; }
.span3 { grid-column: span 3; }
table { width:100%%; border-collapse: collapse; margin-top:8px; }
th, td { border:1px solid #333; padding:3px 5px; font-size:10.5px; }
th { background:#eef3f9; }
.kv td.k { width: 18%%; background:#eef3f9; font-weight:600; white-space:nowrap; }
.items { table-layout: fixed; }
.items th, .items td { white-space: nowrap; font-size: 8px; padding: 2px 3px; }
.items th:nth-child(1), .items td:nth-child(1) { width: 4%%; }
.items th:nth-child(2), .items td:nth-child(2) { width: 12%%; }
.items th:nth-child(3), .items td:nth-child(3) { width: 11%%; }
.items th:nth-child(4), .items td:nth-child(4) { width: 5%%; }
.items th:nth-child(5), .items td:nth-child(5) { width: 5%%; }
.items th:nth-child(6), .items td:nth-child(6) { width: 6%%; }
.items th:nth-child(7), .items td:nth-child(7) { width: 8%%; }
.items th:nth-child(8), .items td:nth-child(8) { width: 8%%; }
.items th:nth-child(9), .items td:nth-child(9) { width: 41%%; }
.num { text-align:right; }
.foot { margin-top:8px; font-size:9px; color:#777; text-align:center; }
""" % FONT_CN


def declaration_html(d: dict) -> str:
    it = d["items"][0]
    rows = [
        ("报关单号", d["decl_no"], "申报日期", d["declare_date"]),
        ("收发货人", d["consignee"], "运输方式", d["transport_mode"]),
        ("贸易方式", d["trade_mode"], "征免性质", d["exemption_nature"]),
        ("启运国", d["origin_country"], "装货港", d["loading_port"]),
        ("境内目的地", d["destination"], "成交方式", d["incoterm"]),
        ("币制", d["currency"], "运费", f'{d.get("freight", 0):.2f}'),
        ("保费", f'{d.get("insurance", 0):.2f}', "合同号", d["contract_no"]),
        ("提单号", d["bl_no"], "许可证号", d.get("license_no") or "无"),
        ("证书号", d.get("cert_no") or "无", "海关", d.get("customs_office", "")),
    ]
    elements = it.get("elements") or {}
    element_text = "|".join(f"{k}={v}" for k, v in elements.items())
    cells = []
    for k1, v1, k2, v2 in rows:
        cells.append(f'<div class="cell k">{k1}</div><div class="cell span2">{v1}</div>'
                     f'<div class="cell k">{k2}</div><div class="cell span2">{v2}</div>')
    # 扫描件字号比文字层大一档：150 DPI 下 8–11px 小字 OCR 很容易误识别
    scan_css = ("body{font-size:13px}.cell{font-size:13px}"
                "table th,table td{font-size:12px}"
                ".items th,.items td{font-size:10px}")
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}{scan_css}</style></head><body>
<div class="doc">
  <div class="title">中华人民共和国海关进口货物报关单</div>
  <div class="sub">合成数据 · 仅用于系统测试</div>
  <div class="grid">{''.join(cells)}</div>
  <table>
    <tr><th>项号</th><th>商品编号</th><th>商品名称及规格型号</th><th>数量</th><th>单位</th>
        <th>单价</th><th>总价</th><th>法定单位</th><th>申报要素</th></tr>
    <tr><td class="num">1</td><td>{it['hs_code']}</td>
        <td>{it['name']}（{elements.get('spec', '通用')}）</td>
        <td class="num">{it['qty']}</td><td>{it['unit']}</td>
        <td class="num">{it['unit_price']:.2f}</td><td class="num">{it['amount']:.2f}</td>
        <td>{it['legal_unit1']} / {it['legal_unit2']}</td>
        <td>{element_text}</td></tr>
    <tr><td colspan="3">合计</td><td class="num">{d.get('qty_total') or it['qty']}</td><td></td>
        <td></td><td class="num">{d['total_amount']:.2f}</td><td colspan="2"></td></tr>
  </table>
  <table>
    <tr><th>件数</th><th>毛重(kg)</th><th>净重(kg)</th><th>海关</th><th>报关单类型</th></tr>
    <tr><td class="num">{d.get('packages','')}</td><td class="num">{d.get('gross_weight','')}</td>
        <td class="num">{d.get('net_weight','')}</td><td>{d.get('customs_office','')}</td>
        <td>{d.get('declaration_type','')}</td></tr>
  </table>
  <div class="foot">本单为合成数据，用于关务智能审核系统测试。</div>
</div></body></html>"""


def packing_html(p: dict, bl: dict) -> str:
    it = p["items"][0]
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<div class="doc">
  <div class="title">装 箱 单  PACKING LIST</div>
  <div class="sub">合成数据 · 仅用于系统测试</div>
  <div class="grid">
    <div class="cell k">装箱单号</div><div class="cell span2">{p['pl_no']}</div>
    <div class="cell k">日期</div><div class="cell span2">{p['date']}</div>
    <div class="cell k">收货人</div><div class="cell span2">{bl['consignee']}</div>
    <div class="cell k">唛头</div><div class="cell span2">{p['marks']['port']} / {p['marks']['text']}</div>
    <div class="cell k">件数</div><div class="cell span2">{p['packages']}</div>
    <div class="cell k">包装种类</div><div class="cell span2">{p['package_type']}</div>
    <div class="cell k">毛重(kg)</div><div class="cell span2">{p['gross_weight']}</div>
    <div class="cell k">净重(kg)</div><div class="cell span2">{p['net_weight']}</div>
    <div class="cell k">体积(m³)</div><div class="cell span2">{p['volume']}</div>
    <div class="cell k">木包装</div><div class="cell span2">{'是' if p.get('wood_packaging') else '否'}</div>
  </div>
  <table>
    <tr><th>序号</th><th>品名</th><th>HS 编码</th><th>数量</th><th>单位</th></tr>
    <tr><td class="num">1</td><td>{it['name']} / {it.get('name_en','')}</td><td>{it['hs_code']}</td>
        <td class="num">{it['qty']}</td><td>{it['unit']}</td></tr>
  </table>
  <div class="foot">本单为合成数据，用于关务智能审核系统测试。</div>
</div></body></html>"""


# ---------------- Edge 渲染 ----------------
def edge_pdf(edge: str, html: Path, out: Path, profile: Path) -> None:
    url = html.as_uri()
    cmd = [edge, "--headless=new", "--disable-gpu", "--no-first-run",
           f"--user-data-dir={profile}", "--no-pdf-header-footer",
           "--virtual-time-budget=3000", f"--print-to-pdf={out}", url]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0 or not out.exists():
        raise SystemExit(f"Edge 转 PDF 失败：{p.returncode}\n{p.stderr[:500]}")


def edge_png(edge: str, html: Path, out: Path, profile: Path,
             width: int = 1240, height: int = 1754) -> None:
    url = html.as_uri()
    cmd = [edge, "--headless=new", "--disable-gpu", "--no-first-run",
           f"--user-data-dir={profile}", "--hide-scrollbars",
           f"--window-size={width},{height}", "--virtual-time-budget=3000",
           f"--screenshot={out}", url]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0 or not out.exists():
        raise SystemExit(f"Edge 截图失败：{p.returncode}\n{p.stderr[:500]}")


def scan_effect(src: Path, out: Path) -> None:
    img = Image.open(src).convert("RGB")
    img = img.rotate(-0.7, expand=True, fillcolor=(236, 236, 236), resample=Image.BICUBIC)
    canvas = Image.new("RGB", (img.width + 70, img.height + 70), (231, 231, 231))
    canvas.paste(img, (35, 35))
    canvas = canvas.filter(ImageFilter.GaussianBlur(0.35))
    px = canvas.load()
    random.seed(20261112)
    for _ in range(22000):
        x = random.randrange(canvas.width)
        y = random.randrange(canvas.height)
        r, g, b = px[x, y]
        d = random.randint(-14, 14)
        px[x, y] = (max(0, min(255, r + d)),
                    max(0, min(255, g + d)),
                    max(0, min(255, b + d)))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "PNG", optimize=True)


def build_scanned_pdf(pages: list[Path], out: Path) -> None:
    """把多张页面图片打包成「图片型 PDF」——没有文字层，等价于纸质扫描件。"""
    imgs = [Image.open(p).convert("RGB") for p in pages]
    out.parent.mkdir(parents=True, exist_ok=True)
    imgs[0].save(out, "PDF", save_all=True, append_images=imgs[1:], resolution=150.0)


ITEM_COLS = ["序号", "品名", "HS编码", "数量", "单位", "单价", "金额",
             "法定单位", "申报要素"]


def item_row(it: dict, idx: int = 1) -> list[str]:
    els = it.get("elements") or {}
    el = "|".join(f"{k}={v}" for k, v in els.items())
    return [str(idx), it["name"], it["hs_code"], str(it["qty"]), it["unit"],
            f'{it["unit_price"]:.2f}', f'{it["amount"]:.2f}',
            f'{it.get("legal_unit1", "个")}/{it.get("legal_unit2", "千克")}', el]


def simple_doc_html(title: str, pairs: list[tuple[str, str]], items: list[list[str]] | None = None) -> str:
    kv = "".join(f'<tr><td class="k">{k}</td><td>{v}</td></tr>' for k, v in pairs)
    item_html = ""
    if items:
        head = "<tr>" + "".join(f"<th>{h}</th>" for h in ITEM_COLS) + "</tr>"
        body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in items)
        item_html = f'<table class="items">{head}{body}</table>'
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<div class="doc">
  <div class="title">{title}</div>
  <div class="sub">合成数据 · 仅用于系统测试</div>
  <table class="kv">{kv}</table>
  {item_html}
  <div class="foot">本单为合成数据，用于关务智能审核系统测试。</div>
</div></body></html>"""


def _five_doc_pages(data: dict) -> dict:
    """五单页面的统一内容（文字层 PDF 与扫描件共用）。"""
    c, inv, p, b, d = (data["contract"], data["invoice"], data["packing_list"],
                       data["bl"], data["declaration"])
    items = [item_row(inv["items"][0])]
    return {
        "合同-HT-2026-0901": ("合 同  CONTRACT", [
            ("合同号", c["contract_no"]), ("卖方", c["seller"]), ("买方", c["buyer"]),
            ("日期", c["date"]), ("币制", c["currency"]), ("成交方式", c["incoterm"]),
            ("合同总额", f'{c["total_amount"]:.2f}'), ("条款", c["terms"]),
            ("付款方式", c["payment"])], None),
        "发票-INV-2026-0901": ("商 业 发 票  COMMERCIAL INVOICE", [
            ("发票号", inv["invoice_no"]), ("合同号", inv["contract_no"]),
            ("发票日期", inv["date"]), ("卖方", inv["seller"]), ("买方", inv["buyer"]),
            ("币制", inv["currency"]), ("成交方式", inv["incoterm"]),
            ("折扣", f'{inv.get("discount", 0):.2f}'), ("佣金", f'{inv.get("commission", 0):.2f}'),
            ("特许权使用费", f'{inv.get("royalty", 0):.2f}'),
            ("发票总额", f'{inv["total_amount"]:.2f}')], items),
        "装箱单-PL-2026-0901": ("装 箱 单  PACKING LIST", [
            ("装箱单号", p["pl_no"]), ("日期", p["date"]), ("件数", str(p["packages"])),
            ("包装种类", p["package_type"]), ("毛重", str(p["gross_weight"])),
            ("净重", str(p["net_weight"])), ("体积", str(p["volume"])),
            ("唛头", f'{p["marks"]["port"]} / {p["marks"]["text"]}'),
            ("木包装", "是" if p.get("wood_packaging") else "否")], items),
        "提单-SYN-2026-0901": ("提 单  BILL OF LADING", [
            ("提单号", b["bl_no"]), ("日期", b["date"]), ("到港日", b["arrival_date"]),
            ("船名", b["vessel"]), ("航次", b["voyage"]), ("起运港", b["pol"]),
            ("目的港", b["pod"]), ("发货人", b["shipper"]), ("收货人", b["consignee"]),
            ("通知人", b["notify"]), ("件数", str(b["packages"])),
            ("毛重", str(b["gross_weight"])), ("体积", str(b.get("volume", 0)))], items),
        "报关单-DEC-2026-0901": ("中华人民共和国海关进口货物报关单", [
            ("报关单号", d["decl_no"]), ("申报日期", d["declare_date"]),
            ("收发货人", d["consignee"]), ("运输方式", d["transport_mode"]),
            ("贸易方式", d["trade_mode"]), ("征免性质", d["exemption_nature"]),
            ("启运国", d["origin_country"]), ("装货港", d["loading_port"]),
            ("境内目的地", d["destination"]), ("成交方式", d["incoterm"]),
            ("币制", d["currency"]), ("运费", f'{d.get("freight", 0):.2f}'),
            ("保费", f'{d.get("insurance", 0):.2f}'), ("合同号", d["contract_no"]),
            ("提单号", d["bl_no"]), ("件数", str(d.get("packages", ""))),
            ("毛重", str(d.get("gross_weight", ""))), ("净重", str(d.get("net_weight", ""))),
            ("总价", f'{d["total_amount"]:.2f}'), ("许可证号", d.get("license_no") or "无"),
            ("证书号", d.get("cert_no") or "无")],
            [item_row(d["items"][0])]),
    }


def build_five_pdfs(data: dict, edge: str, tmp: Path, profile: Path, out_dir: Path) -> list[Path]:
    """按统一版式生成五份 PDF，供文本抽取器消费。"""
    docs = _five_doc_pages(data)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, (title, pairs, rows) in docs.items():
        html = tmp / f"{name}.html"
        html.write_text(simple_doc_html(title, pairs, rows), encoding="utf-8")
        out = out_dir / f"{name}.pdf"
        edge_pdf(edge, html, out, profile)
        written.append(out)
    return written


def build_five_scan_pdf(data: dict, edge: str, tmp: Path, profile: Path, out: Path) -> Path:
    """五页扫描件：合同/发票/装箱单/提单/报关单各一页，无文字层。

    装箱单与报关单用专用版式（报关单字号更大、带申报要素），其余用通用版式。
    """
    docs = _five_doc_pages(data)
    names = ["合同-HT-2026-0901", "发票-INV-2026-0901", "装箱单-PL-2026-0901",
             "提单-SYN-2026-0901", "报关单-DEC-2026-0901"]
    pages = []
    for index, name in enumerate(names, 1):
        if name.startswith("装箱单"):
            html_text = packing_html(data["packing_list"], data["bl"])
        elif name.startswith("报关单"):
            html_text = declaration_html(data["declaration"])
        else:
            # 通用版式的字号偏小，扫描件单独放大一档，改进 150 DPI 下的 OCR
            html_text = simple_doc_html(*docs[name]).replace(
                "</head>",
                "<style>body{font-size:15px}table th,table td{font-size:14px}"
                ".items th,.items td{font-size:11px}</style></head>")
        html = tmp / f"scan_{index}.html"
        html.write_text(html_text, encoding="utf-8")
        shot = tmp / f"scan_{index}_shot.png"
        edge_png(edge, html, shot, profile)
        page = tmp / f"scan_{index}.png"
        scan_effect(shot, page)
        pages.append(page)
    out.parent.mkdir(parents=True, exist_ok=True)
    build_scanned_pdf(pages, out)
    return out


def main() -> int:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    edge = find_edge()
    tmp = Path(tempfile.mkdtemp(prefix="rawdocs_"))
    profile = tmp / "edge-profile"

    xlsx = OUT / "合成发票-INV-2026-0901.xlsx"
    five_xlsx = OUT / "合成五单-2026-0901.xlsx"
    pdf = OUT / "合成报关单-DEC-2026-0901.pdf"
    png = OUT / "合成装箱单-PL-2026-0901.png"
    scanned = OUT / "合成扫描件-多页.pdf"

    build_invoice_xlsx(data["invoice"], xlsx)
    build_five_xlsx(data, five_xlsx)

    decl_html = tmp / "declaration.html"
    decl_html.write_text(declaration_html(data["declaration"]), encoding="utf-8")
    edge_pdf(edge, decl_html, pdf, profile)

    pack_html = tmp / "packing.html"
    pack_html.write_text(packing_html(data["packing_list"], data["bl"]), encoding="utf-8")
    shot = tmp / "packing_shot.png"
    edge_png(edge, pack_html, shot, profile)
    scan_effect(shot, png)

    # 扫描件 PDF：两页图片打包，无文字层（模拟纸质件扫描）
    decl_shot = tmp / "decl_shot.png"
    edge_png(edge, decl_html, decl_shot, profile)
    decl_scan = tmp / "decl_scan.png"
    scan_effect(decl_shot, decl_scan)
    build_scanned_pdf([png, decl_scan], scanned)

    # 成套五份文字层 PDF（供文本抽取链路使用）
    five = build_five_pdfs(data, edge, tmp, profile, OUT / "pdf")

    # 五页扫描件（合同/发票/装箱单/提单/报关单各一页，无文字层）
    five_scan = build_five_scan_pdf(data, edge, tmp, profile,
                                    OUT / "合成扫描件-五单.pdf")

    for f in (xlsx, five_xlsx, pdf, png, scanned, five_scan):
        print(f"{f.name}\t{f.stat().st_size} bytes")
    for f in five:
        print(f"pdf/{f.name}\t{f.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
