#!/usr/bin/env python3
"""小红书笔记GPM数据看板 - 生成器"""

from __future__ import annotations

import csv
import html
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SNAPSHOT_DIR = ROOT / "data" / "snapshots"
ECHARTS_JS = ROOT / "echarts.min.js"
DASHBOARD_RUNTIME_JS = ROOT / "dashboard_runtime.js"
DASHBOARD_HTML = ROOT / "index.html"
DASHBOARD_DATA = ROOT / "dashboard_data.json"

DASHBOARD_TITLE = "小红书笔记转化分析看板"
DASHBOARD_SUBTITLE = "曝光·点击·成交全链路 · 素材效率分析"
TIMEZONE_LABEL = "Asia/Shanghai"
DEFAULT_RANGE = "30D"


def fmt_num(value: float) -> str:
    return f"{value:,.0f}"


def fmt_money(value: float) -> str:
    return f"¥{value:,.2f}"


def pct(value: float) -> str:
    return f"{value * 100:+.1f}%"


def read_sources() -> list[dict]:
    """Read the GPM CSV data."""
    csv_path = ROOT / "data" / "notes_gpm.csv"
    if not csv_path.exists():
        return []
    rows = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            # Extract date from 发布时间
            raw_dt = str(row.get("发布时间") or "")[:10]
            row["date"] = raw_dt
            rows.append(row)
    return rows


def load_product_mapping() -> tuple[dict[str, dict], list[dict]]:
    """Load note-to-product mapping from product-note Excel files.
    
    Returns:
        (note_map, product_list)
        - note_map: {笔记ID: {"商品ID": ..., "商品名称": ...}}
        - product_list: [{"id": ..., "name": ..., "short_name": ..., "count": ..., "category": ...}]
    """
    upload_dir = Path("/workspace/.uploads")
    excel_files = sorted(upload_dir.glob("*商品笔记数据*.xlsx"))
    
    note_map: dict[str, dict] = {}
    product_counts: dict[str, int] = {}
    product_names: dict[str, str] = {}
    
    for f in excel_files:
        try:
            import pandas as pd
            df = pd.read_excel(f)
            df["关联商品ID"] = df["关联商品ID"].astype(str)
            df["笔记ID"] = df["笔记ID"].astype(str)
            
            for _, row in df.iterrows():
                pid = str(row["关联商品ID"])
                nid = str(row["笔记ID"])
                pname = str(row["关联商品名称"])
                
                if pid not in product_names:
                    product_names[pid] = pname
                
                if nid not in note_map:
                    note_map[nid] = {"商品ID": pid, "商品名称": pname}
                    product_counts[pid] = product_counts.get(pid, 0) + 1
        except Exception:
            continue
    
    # 生成短名称
    def short_name(full_name: str) -> str:
        name = full_name
        # 常见后缀截断
        for suffix in ["一人食", "顺丰包邮", "低脂餐", "宝宝辅食", "可生食", "免处理"]:
            name = name.replace(suffix, "")
        # 去重标点
        name = name.replace("·", " ").replace("  ", " ").strip()
        # 按关键词匹配短名
        if "手剥虾仁" in full_name:
            return "手剥虾仁"
        elif "三文鱼切块" in full_name:
            return "三文鱼切块"
        elif "基围虾" in full_name or "白虾" in full_name and "王牌" not in full_name and "盐冻" not in full_name:
            return "基围虾"
        elif "8斤" in full_name and "三文鱼" in full_name:
            return "8斤整条三文鱼"
        elif "生蚝" in full_name or "乳山" in full_name:
            return "生蚝"
        elif "北极甜虾" in full_name and "寿司" not in full_name:
            return "北极甜虾"
        elif "三文鱼刺身" in full_name or "冰鲜三文鱼" in full_name:
            return "挪威三文鱼刺身"
        elif "鲅鱼" in full_name:
            return "青岛大鲅鱼"
        elif "王牌大虾" in full_name:
            return "王牌大虾"
        elif "盐田虾" in full_name:
            return "盐田虾"
        elif "寿司甜虾" in full_name:
            return "寿司甜虾"
        elif "开背鲈鱼" in full_name:
            return "开背鲈鱼"
        elif "扇贝肉" in full_name:
            return "扇贝肉"
        elif "鱼籽酱" in full_name or "飞鱼籽" in full_name:
            return "鱼籽酱"
        elif "冷冻虾仁" in full_name or "虾仁冷冻" in full_name:
            return "冷冻虾仁"
        else:
            return name[:10]
    
    # 分类
    def categorize(name: str) -> str:
        if any(k in name for k in ["虾仁", "虾", "甜虾"]):
            return "虾类"
        elif any(k in name for k in ["三文鱼", "鱼", "鲅鱼", "鲈鱼"]):
            return "鱼类"
        elif any(k in name for k in ["生蚝", "扇贝", "蛎子", "鱼籽", "蛤"]):
            return "贝类"
        else:
            return "其他"
    
    # 构建商品列表（按笔记数降序）
    product_list = []
    for pid, count in sorted(product_counts.items(), key=lambda x: -x[1]):
        full_name = product_names.get(pid, pid)
        sname = short_name(full_name)
        product_list.append({
            "id": pid,
            "name": full_name,
            "short_name": sname,
            "count": count,
            "category": categorize(sname),
        })
    
    return note_map, product_list


def normalize_snapshots(rows: list[dict]) -> list[dict]:
    """Normalize and deduplicate rows by 笔记ID."""
    note_product_map, product_list = load_product_mapping()
    normalized = []
    for raw in rows:
        row = dict(raw)
        row["date"] = str(row.get("date") or "")[:10]
        row["GPM"] = float(row.get("GPM") or 0)
        row["支付金额"] = float(row.get("支付金额") or 0)
        row["支付订单数"] = int(float(row.get("支付订单数") or 0))
        row["支付人数"] = int(float(row.get("支付人数") or 0))
        row["曝光量"] = int(float(row.get("曝光量") or 0))
        row["阅读量"] = int(float(row.get("阅读量") or 0))
        row["互动量"] = int(float(row.get("互动量") or 0))
        row["商品点击次数"] = int(float(row.get("商品点击次数") or 0))
        row["商品点击人数"] = int(float(row.get("商品点击人数") or 0))
        row["加购件数"] = int(float(row.get("加购件数") or 0))
        row["退款金额"] = float(row.get("退款金额") or 0)
        row["退款订单数"] = int(float(row.get("退款订单数") or 0))
        row["GPM状态"] = str(row.get("GPM状态") or "无成交数据")
        note_id = str(row.get("笔记ID") or "")
        
        # 商品信息
        prod_info = note_product_map.get(note_id, {})
        row["商品ID"] = prod_info.get("商品ID", "")
        row["商品名称"] = prod_info.get("商品名称", "未关联商品")
        
        normalized.append(row)

    # Deduplicate by 笔记ID
    latest_by_key: dict[str, dict] = {}
    for row in normalized:
        key = row.get("笔记ID", "")
        if key and key not in latest_by_key:
            latest_by_key[key] = row
    return sorted(latest_by_key.values(), key=lambda item: item.get("date", ""))


def latest_date(rows: list[dict]) -> str:
    dates = sorted({row["date"] for row in rows if row.get("date") and row["date"] != "NaT"})
    return dates[-1] if dates else ""


def sum_between(rows: list[dict], start: str, end: str, field: str) -> float:
    return sum(float(row.get(field) or 0) for row in rows if start <= row["date"] <= end)


def make_dashboard_payload(rows: list[dict]) -> dict:
    _, product_list = load_product_mapping()
    dates = sorted({row["date"] for row in rows if row["date"] and row["date"] != "NaT"})
    latest = dates[-1] if dates else ""
    start_30 = dates[-30] if len(dates) >= 30 else (dates[0] if dates else "")
    start_7 = dates[-7] if len(dates) >= 7 else (dates[0] if dates else "")

    # Payment rows only
    paid_rows = [r for r in rows if r["支付金额"] > 0]

    # ===== 新增：曝光阶段分层 =====
    def exposure_stage(exp: float) -> str:
        if exp < 5000:
            return "种子期(0-5k)"
        elif exp < 20000:
            return "爬坡期(5k-2w)"
        else:
            return "爆款期(2w+)"

    # ===== 新增：计算中位数基准（用于潜力判断和问题诊断）=====
    if paid_rows:
        paid_expos = [r["曝光量"] for r in paid_rows]
        paid_interact_rates = sorted([(r["互动量"] or 0) / max(r["曝光量"], 1) for r in paid_rows])
        paid_click_rates = sorted([(r["商品点击次数"] or 0) / max(r["阅读量"], 1) for r in paid_rows])
        paid_ctrs = sorted([(r["阅读量"] or 0) / max(r["曝光量"], 1) for r in paid_rows])
        paid_cvrs = sorted([(r["支付订单数"] or 0) / max(r["商品点击次数"], 1) for r in paid_rows])
        med_interact_rate = paid_interact_rates[len(paid_interact_rates) // 2]
        med_click_rate = paid_click_rates[len(paid_click_rates) // 2]
        med_ctr = paid_ctrs[len(paid_ctrs) // 2]
        med_cvr = paid_cvrs[len(paid_cvrs) // 2]
    else:
        med_interact_rate = med_click_rate = med_ctr = med_cvr = 0

    # ===== 新增：潜力标签 + 问题诊断 =====
    def potential_tag(r: dict) -> str:
        exp = r["曝光量"]
        # 只在爬坡期(5k-2w)判断潜力
        if 5000 <= exp < 20000:
            interact_rate = (r["互动量"] or 0) / max(exp, 1)
            click_rate = (r["商品点击次数"] or 0) / max(r["阅读量"] or 1, 1)
            score = 0
            if interact_rate >= med_interact_rate:
                score += 1
            if click_rate >= med_click_rate:
                score += 1
            if r["GPM"] >= (sum(x["GPM"] for x in paid_rows) / max(len(paid_rows), 1)):
                score += 1
            if score >= 2:
                return "待放量"
            elif score == 1:
                return "观察中"
            else:
                return "建议优化"
        elif exp >= 20000:
            return "已放量"
        else:
            return "冷启动"

    def diagnosis_tag(r: dict) -> str:
        if r["曝光量"] <= 0 or r["商品点击次数"] <= 0:
            return "数据不足"
        ctr = (r["阅读量"] or 0) / max(r["曝光量"], 1)
        cvr = (r["支付订单数"] or 0) / max(r["商品点击次数"], 1)
        hi_ctr = ctr >= med_ctr
        hi_cvr = cvr >= med_cvr
        if hi_ctr and hi_cvr:
            return "优质素材"
        elif not hi_ctr and hi_cvr:
            return "缺流量"
        elif hi_ctr and not hi_cvr:
            return "内容需优化"
        else:
            return "双低待优化"

    # 给所有有成交笔记增加标签
    for r in paid_rows:
        r["曝光阶段"] = exposure_stage(r["曝光量"])
        r["潜力标签"] = potential_tag(r)
        r["问题诊断"] = diagnosis_tag(r)
    for r in rows:
        r["曝光阶段"] = exposure_stage(r["曝光量"])

    # ===== 新增：分层统计 =====
    stage_stats = {}
    for stage in ["种子期(0-5k)", "爬坡期(5k-2w)", "爆款期(2w+)"]:
        stage_rows = [r for r in rows if r["曝光阶段"] == stage]
        stage_paid = [r for r in stage_rows if r["支付金额"] > 0]
        total_exp = sum(r["曝光量"] for r in stage_rows)
        total_pay = sum(r["支付金额"] for r in stage_paid)
        gpm = round(total_pay / total_exp * 1000, 2) if total_exp > 0 else 0
        stage_stats[stage] = {
            "笔记数": len(stage_rows),
            "有成交": len(stage_paid),
            "成交率": f"{len(stage_paid)/len(stage_rows)*100:.1f}%" if stage_rows else "0%",
            "总曝光": int(total_exp),
            "总支付": round(total_pay, 2),
            "GPM": gpm,
            "支付占比": f"{total_pay / max(sum(r['支付金额'] for r in paid_rows), 1) * 100:.1f}%",
        }

    # ===== 新增：商品维度汇总 =====
    product_summary_map = defaultdict(lambda: {"笔记数": 0, "有成交": 0, "总曝光量": 0,
                                                 "总阅读量": 0, "总支付金额": 0, "总支付订单": 0,
                                                 "总商品点击": 0, "商品名称": ""})
    for r in rows:
        pid = r.get("商品ID", "未知")
        pname = r.get("商品名称", "")
        if pname and not product_summary_map[pid]["商品名称"]:
            product_summary_map[pid]["商品名称"] = pname
        product_summary_map[pid]["笔记数"] += 1
        product_summary_map[pid]["总曝光量"] += r["曝光量"]
        product_summary_map[pid]["总阅读量"] += r["阅读量"]
        product_summary_map[pid]["总商品点击"] += r.get("商品点击次数", 0) or 0
        if r["支付金额"] > 0:
            product_summary_map[pid]["有成交"] += 1
            product_summary_map[pid]["总支付金额"] += r["支付金额"]
            product_summary_map[pid]["总支付订单"] += r["支付订单数"]

    product_summary = []
    for pid, v in product_summary_map.items():
        gpm_val = round(v["总支付金额"] / v["总曝光量"] * 1000, 2) if v["总曝光量"] > 0 else 0
        ctr_val = round(v["总阅读量"] / v["总曝光量"] * 100, 2) if v["总曝光量"] > 0 else 0
        cvr_val = round(v["总支付订单"] / max(v["总商品点击"], 1) * 100, 2) if v["总商品点击"] > 0 else 0
        product_summary.append({
            "商品ID": pid,
            "商品名称": v.get("商品名称", pid),
            "笔记数": v["笔记数"],
            "有成交": v["有成交"],
            "总曝光量": v["总曝光量"],
            "总支付金额": round(v["总支付金额"], 2),
            "总支付订单": v["总支付订单"],
            "平均GPM": gpm_val,
            "平均CTR": ctr_val,
            "平均CVR": cvr_val,
        })
    product_summary.sort(key=lambda x: -x["总支付金额"])

    # Overall KPIs
    total_payment = sum(r["支付金额"] for r in paid_rows)
    total_orders = sum(r["支付订单数"] for r in paid_rows)
    total_exposure = sum(r["曝光量"] for r in rows)
    avg_gpm_all = (total_payment / total_exposure * 1000) if total_exposure > 0 else 0

    # 30 days
    paid_30 = [r for r in paid_rows if start_30 <= r["date"] <= latest] if start_30 else paid_rows
    total_payment_30 = sum(r["支付金额"] for r in paid_30)
    total_exposure_30 = sum(r["曝光量"] for r in paid_30)
    avg_gpm_30 = (total_payment_30 / total_exposure_30 * 1000) if total_exposure_30 > 0 else 0

    # 7 days
    paid_7 = [r for r in paid_rows if start_7 <= r["date"] <= latest] if start_7 else paid_rows
    total_payment_7 = sum(r["支付金额"] for r in paid_7)
    total_exposure_7 = sum(r["曝光量"] for r in paid_7)
    avg_gpm_7 = (total_payment_7 / total_exposure_7 * 1000) if total_exposure_7 > 0 else 0
    gpm_delta = (avg_gpm_30 - avg_gpm_7) / avg_gpm_7 if avg_gpm_7 > 0 else 0

    # GPM leaderboard (full sorted list; runtime applies filter + limit)
    paid_sorted = sorted(paid_rows, key=lambda r: r["GPM"], reverse=True)
    gpm_leaderboard = [
        {
            "笔记ID": r["笔记ID"],
            "笔记标题": r.get("笔记标题", "")[:30],
            "账号": r.get("账号", ""),
            "商品ID": r["商品ID"],
            "商品名称": r["商品名称"],
            "GPM": round(r["GPM"], 2),
            "支付金额": r["支付金额"],
            "支付订单数": r["支付订单数"],
            "曝光量": r["曝光量"],
            "阅读量": r["阅读量"],
            "互动量": r["互动量"],
            "商品点击次数": r["商品点击次数"],
            "曝光阶段": r.get("曝光阶段", ""),
            "潜力标签": r.get("潜力标签", ""),
            "问题诊断": r.get("问题诊断", ""),
        }
        for r in paid_sorted
    ]

    # Exposure leaderboard (full sorted list; runtime applies filter + limit)
    exposure_sorted = sorted(rows, key=lambda r: r["曝光量"], reverse=True)
    exposure_leaderboard = [
        {
            "笔记ID": r["笔记ID"],
            "笔记标题": r.get("笔记标题", "")[:30],
            "账号": r.get("账号", ""),
            "商品ID": r["商品ID"],
            "商品名称": r["商品名称"],
            "曝光量": r["曝光量"],
            "阅读量": r["阅读量"],
            "互动量": r["互动量"],
            "支付金额": r["支付金额"],
            "GPM": round(r["GPM"], 2),
            "GPM状态": r["GPM状态"],
            "曝光阶段": r.get("曝光阶段", ""),
        }
        for r in exposure_sorted
    ]

    # Account summary
    accounts = defaultdict(lambda: {"笔记数": 0, "有成交": 0, "总曝光量": 0, "总阅读量": 0,
                                     "总互动量": 0, "总支付金额": 0, "总支付订单": 0, "总GPM": 0})
    for r in rows:
        acct = r.get("账号", "未知")
        accounts[acct]["笔记数"] += 1
        accounts[acct]["总曝光量"] += r["曝光量"]
        accounts[acct]["总阅读量"] += r["阅读量"]
        accounts[acct]["总互动量"] += r["互动量"]
        if r["支付金额"] > 0:
            accounts[acct]["有成交"] += 1
            accounts[acct]["总支付金额"] += r["支付金额"]
            accounts[acct]["总支付订单"] += r["支付订单数"]
            accounts[acct]["总GPM"] += r["GPM"]

    account_summary = [
        {
            "账号": name,
            "笔记数": v["笔记数"],
            "有成交": v["有成交"],
            "总曝光量": v["总曝光量"],
            "总阅读量": v["总阅读量"],
            "总互动量": v["总互动量"],
            "总支付金额": round(v["总支付金额"], 2),
            "总支付订单": v["总支付订单"],
            "成交率": f"{v['有成交']/v['笔记数']*100:.1f}%" if v["笔记数"] > 0 else "0%",
            "平均GPM": round(v["总GPM"] / v["有成交"], 2) if v["有成交"] > 0 else 0,
        }
        for name, v in sorted(accounts.items(), key=lambda x: -x[1]["总支付金额"])
    ]

    # Daily payment trend
    daily_payment = defaultdict(lambda: {"支付金额": 0.0, "支付订单": 0, "曝光量": 0, "互动量": 0})
    for r in paid_rows:
        d = r["date"]
        daily_payment[d]["支付金额"] += r["支付金额"]
        daily_payment[d]["支付订单"] += r["支付订单数"]
        daily_payment[d]["曝光量"] += r["曝光量"]
        daily_payment[d]["互动量"] += r["互动量"]
    daily_trend = [
        {"date": d, "支付金额": round(v["支付金额"], 2), "支付订单": v["支付订单"],
         "曝光量": v["曝光量"], "GPM": round(v["支付金额"] / v["曝光量"] * 1000, 2) if v["曝光量"] > 0 else 0}
        for d, v in sorted(daily_payment.items())
    ]

    # Promo status comparison
    promo_compare = defaultdict(lambda: {"笔记数": 0, "总曝光量": 0, "总支付金额": 0, "总支付订单": 0, "有支付": 0, "总GPM": 0})
    for r in rows:
        p = r.get("推广状态", "未知")
        promo_compare[p]["笔记数"] += 1
        promo_compare[p]["总曝光量"] += r["曝光量"]
        if r["支付金额"] > 0:
            promo_compare[p]["总支付金额"] += r["支付金额"]
            promo_compare[p]["总支付订单"] += r["支付订单数"]
            promo_compare[p]["有支付"] += 1
            promo_compare[p]["总GPM"] += r["GPM"]
    promo_summary = [
        {
            "推广状态": name,
            "笔记数": v["笔记数"],
            "总曝光量": v["总曝光量"],
            "总支付金额": round(v["总支付金额"], 2),
            "总支付订单": v["总支付订单"],
            "有支付": v["有支付"],
            "平均GPM": round(v["总GPM"] / v["有支付"], 2) if v["有支付"] > 0 else 0,
        }
        for name, v in sorted(promo_compare.items(), key=lambda x: -x[1]["总支付金额"])
    ]

    # Note type comparison
    type_compare = defaultdict(lambda: {"笔记数": 0, "总曝光量": 0, "总支付金额": 0, "有支付": 0, "总GPM": 0})
    for r in rows:
        t = r.get("笔记类型", "未知")
        type_compare[t]["笔记数"] += 1
        type_compare[t]["总曝光量"] += r["曝光量"]
        if r["支付金额"] > 0:
            type_compare[t]["总支付金额"] += r["支付金额"]
            type_compare[t]["有支付"] += 1
            type_compare[t]["总GPM"] += r["GPM"]
    type_summary = [
        {
            "笔记类型": name,
            "笔记数": v["笔记数"],
            "总曝光量": v["总曝光量"],
            "总支付金额": round(v["总支付金额"], 2),
            "有支付": v["有支付"],
            "平均GPM": round(v["总GPM"] / v["有支付"], 2) if v["有支付"] > 0 else 0,
        }
        for name, v in sorted(type_compare.items(), key=lambda x: -x[1]["总支付金额"])
    ]

    source_snippets = {
        "gpmLeaderboard": """# GPM排行榜
paid_rows = [r for r in rows if r['支付金额'] > 0]
sorted_rows = sorted(paid_rows, key=lambda r: r['GPM'], reverse=True)
top30 = [{'笔记ID': r['笔记ID'], '笔记标题': r['笔记标题'],
          '账号': r['账号'], 'GPM': r['GPM'], '支付金额': r['支付金额']}
         for r in sorted_rows[:30]]""",
        "exposureLeaderboard": """# 曝光量排行榜
sorted_rows = sorted(rows, key=lambda r: r['曝光量'], reverse=True)
top30 = [{'笔记ID': r['笔记ID'], '笔记标题': r['笔记标题'],
          '账号': r['账号'], '曝光量': r['曝光量'], 'GPM': r['GPM']}
         for r in sorted_rows[:30]]""",
        "gpmVsExposure": """# GPM vs 曝光量散点图
paid_rows = [r for r in rows if r['支付金额'] > 0]
scatter = [{'曝光量': r['曝光量'], 'GPM': r['GPM'],
            '账号': r['账号'], '笔记标题': r['笔记标题'][:15]}
           for r in paid_rows]""",
        "accountComparison": """# 账号对比
group by 账号, sum 支付金额, 曝光量, 笔记数
avg_gpm = 总支付金额 / 总曝光量 * 1000""",
        "dailyTrend": """# 每日支付趋势
daily = group by date, sum 支付金额, 支付订单, 曝光量
daily_gpm = 支付金额 / 曝光量 * 1000""",
        "promoComparison": """# 推广状态对比
group by 推广状态, count 笔记数, sum 曝光量, 支付金额, 订单数
avg_gpm = 总支付金额 / 总曝光量 * 1000""",
        "quadrantMatrix": """# 四象限素材矩阵
X轴 = 曝光量, Y轴 = GPM
分割线 = 各筛选范围内的中位数
Q1 优质素材: 高曝光 · 高GPM
Q2 潜力素材: 低曝光 · 高GPM（可加大投放）
Q3 待优化: 低曝光 · 低GPM
Q4 需改进: 高曝光 · 低GPM（优化转化）
点大小 = GPM大小
悬浮可查看笔记标题、账号、支付金额等详情""",
        "conversionFunnel": """# 转化漏斗
全链路4层：曝光 → 阅读 → 商品点击 → 支付订单
每层显示从上一层到当前层的转化率
用于定位转化链路的薄弱环节""",
        "threeTierChart": """# 三层分级贡献
按支付金额将有成交笔记分为三层：
🔥 爆款层 TOP10：重点维护、加投、复制
⭐ 潜力层 11-50名：观察、测试、优化
📉 长尾层 50名以后：批量处理
验证帕累托法则：20%笔记贡献80%成交""",
        "zeroPayAnalysis": """# 零成交笔记诊断
对零成交笔记按CTR和商品点击率分四象限：
🟡 有潜力：高CTR+高商品点击→优化商品承接
🟢 缺流量：低CTR+高商品点击→优化标题封面/投流
🔴 无效流量：高CTR+低商品点击→标题党/内容不匹配
⚫ 双低：低CTR+低商品点击→全面优化或放弃
点大小 = 曝光量大小""",
        "lifecycleAnalysis": """# 笔记生命周期分析
按发布天数分为5个年龄段：
0-3天 / 3-7天 / 7-30天 / 30-90天 / 90天+
统计各阶段的笔记数、成交率、GPM、CTR、CVR
观察笔记效率随时间的变化规律
柱状图模式：多指标对比 | 饼图模式：笔记分布占比""",
        "benchmarkComparison": """# 大盘基准对比
基于商笔大盘参考区间进行三色分级：
🔴 低于大盘：低于参考区间下限
🟡 近似大盘：在参考区间范围内
🟢 优于大盘：高于参考区间上限
CTR参考区间：5.80% ~ 7.84%
CVR参考区间：6.54% ~ 8.84%
仪表盘直观展示当前水平在大盘中的位置""",
        "accountProductHeatmap": """# 账号×商品矩阵热力图
交叉维度分析：账号 × 商品
颜色深浅代表平均GPM高低
快速识别：
- 哪些账号擅长带哪些货
- 哪些商品在哪些账号上表现好
- 账号-商品组合的空白机会点""",
        "efficiencyScale": """# 效率-规模错位分析
商品维度四象限分析：
X轴 = 总曝光量（规模）
Y轴 = 平均GPM（效率）
按中位数分割四象限：
🟢 高效规模型：高曝光+高GPM → 核心主力
🔵 高效潜力型：低曝光+高GPM → 可加大投放
🟡 规模低效型：高曝光+低GPM → 优化转化效率
⚫ 低效待优化：低曝光+低GPM → 评估取舍
点大小 = 总支付金额""",
    }

    return {
        "title": DASHBOARD_TITLE,
        "subtitle": DASHBOARD_SUBTITLE,
        "timezone": TIMEZONE_LABEL,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "freshness": {
            "latestDataDate": latest,
            "latestCapturedAt": "商品笔记数据 2026-03-01~2026-08-16",
            "source": "小红书笔记分析 + 商品笔记数据（两段累加）",
        },
        "availableDates": dates,
        "defaultRange": DEFAULT_RANGE,
        "kpis": [
            {
                "id": "totalNotes",
                "label": "笔记总数",
                "value": f"{len(rows)}",
                "delta": f"有{len(paid_rows)}条产生成交",
                "detail": f"成交率 {len(paid_rows)/len(rows)*100:.1f}%",
            },
            {
                "id": "totalPayment",
                "label": "总支付金额",
                "value": fmt_money(total_payment),
                "delta": f"{total_orders} 笔订单",
                "detail": f"有支付笔记平均GPM {avg_gpm_all:.2f}",
            },
            {
                "id": "avgGpm30",
                "label": "当前范围平均GPM",
                "value": f"{avg_gpm_30:.2f}",
                "delta": f"{gpm_delta:+.1%} vs 近7天",
                "detail": "GPM = 支付金额 ÷ 曝光量 × 1000",
            },
        ],
        "stageStats": stage_stats,
        "datasets": {
            "gpmLeaderboard": gpm_leaderboard,
            "exposureLeaderboard": exposure_leaderboard,
            "paidRows": paid_rows,
            "allRows": rows,
            "accountSummary": account_summary,
            "promoSummary": promo_summary,
            "typeSummary": type_summary,
            "dailyTrend": daily_trend,
            "productSummary": product_summary,
        },
        "productFilter": {
            "field": "商品ID",
            "options": ["全部"] + [p["id"] for p in product_list],
            "default": "全部",
            "combine": {},
            "productNames": {p["id"]: p["short_name"] for p in product_list},
            "productList": product_list,
        },
        "sourceSnippets": source_snippets,
    }


def js_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def json_script(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def render_kpi_block(block: dict) -> str:
    return f"""
    <section class="kpi-tile" id="{html.escape(block["id"])}">
      <p>{html.escape(block["label"])}</p>
      <strong>{html.escape(block["value"])}</strong>
      <span>{html.escape(block["delta"])}</span>
      <small>{html.escape(block["detail"])}</small>
    </section>
    """


def render_panel_actions(block: dict) -> str:
    edit = ""
    edit_command = ""
    if len(block.get("allowed_types", [])) > 1:
        options = "\n".join(
            f'<option value="{html.escape(kind)}"{" selected" if kind == block.get("initial_type") else ""}>{html.escape(kind)}</option>'
            for kind in block["allowed_types"]
        )
        edit_command = f"""<button onclick="toggleEdit('{html.escape(block["chart_id"])}')">Edit</button>"""
        edit = f"""
        <div class="edit-panel" id="edit-{html.escape(block["chart_id"])}">
          <label for="select-{html.escape(block["chart_id"])}">Type</label>
          <select id="select-{html.escape(block["chart_id"])}" onchange="setChartType('{html.escape(block["chart_id"])}', this.value)">
            {options}
          </select>
        </div>
        """
    return f"""
    <div class="chart-actions">
      {edit}
      <div class="toolbox">
        <button class="tool-button" aria-label="Panel actions" onclick="toggleMenu('{html.escape(block["chart_id"])}')"><span class="dot"></span><span class="dot"></span><span class="dot"></span></button>
        <div class="menu" id="menu-{html.escape(block["chart_id"])}">
          {edit_command}
          <button onclick="viewSource('{html.escape(block["source_key"])}')">View Data Source</button>
        </div>
      </div>
    </div>
    """


def infer_panel_span(block: dict) -> int:
    if block.get("span") is not None:
        span = int(block["span"])
        return span if span in (4, 6, 12) else 6
    if block["kind"] == "table":
        columns = block.get("columns", [])
        has_long_text = any(col.get("long_text") for col in columns)
        return 12 if len(columns) >= 6 or has_long_text else 6
    if block["kind"] == "chart":
        chart_type = str(block.get("initial_type") or "")
        dense_chart = chart_type in {"heatmap", "scatter"} or block.get("dense")
        many_categories = int(block.get("category_count") or 0) > 8
        return 12 if dense_chart or many_categories else 6
    if block["kind"] == "note":
        return 4 if block.get("compact") else 6
    return 6


def panel_span_attr(block: dict) -> str:
    span = infer_panel_span(block)
    return f'data-span="{span}"'


def render_chart_block(block: dict) -> str:
    return f"""
    <section class="dashboard-panel chart-panel" {panel_span_attr(block)} id="{html.escape(block["id"])}">
      <header>
        <div>
          <h2>{html.escape(block["title"])}</h2>
          <p>{html.escape(block["subtitle"])}</p>
        </div>
        {render_panel_actions(block)}
      </header>
      <div class="chart" id="{html.escape(block["chart_id"])}" role="img" aria-label="{html.escape(block["title"])}"></div>
      <footer>{html.escape(block["unit"])} | {html.escape(block["source_context"])}</footer>
    </section>
    """


def render_table_block(block: dict) -> str:
    columns = block["columns"]
    head = "".join(f"<th>{html.escape(col['label'])}</th>" for col in columns)
    return f"""
    <section class="dashboard-panel table-panel" {panel_span_attr(block)} id="{html.escape(block["id"])}">
      <header>
        <div>
          <h2>{html.escape(block["title"])}</h2>
          <p>{html.escape(block["subtitle"])}</p>
        </div>
        <div class="toolbox">
          <button class="tool-button" aria-label="Panel actions" onclick="toggleMenu('{html.escape(block["source_key"])}')"><span class="dot"></span><span class="dot"></span><span class="dot"></span></button>
          <div class="menu" id="menu-{html.escape(block["source_key"])}">
            <button onclick="viewSource('{html.escape(block["source_key"])}')">View Data Source</button>
          </div>
        </div>
      </header>
      <div class="table-scroll">
        <table id="{html.escape(block["table_id"])}">
          <thead><tr>{head}</tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <footer>{html.escape(block["source_context"])}</footer>
    </section>
    """


def render_note_block(block: dict) -> str:
    return f"""
    <section class="dashboard-note" {panel_span_attr(block)} id="{html.escape(block["id"])}">
      <strong>{html.escape(block["title"])}</strong>
      <span>{html.escape(block["body"])}</span>
    </section>
    """


def build_dashboard_blocks(payload: dict) -> list[dict]:
    blocks = []
    blocks.extend({"kind": "kpi", **kpi} for kpi in payload["kpis"])

    # 曝光分层KPI
    blocks.extend([
        {
            "kind": "kpi",
            "id": "stageSeed",
            "label": "🌱 种子期 (0-5k曝光)",
            "value": "计算中",
            "delta": "",
            "detail": "",
            "stage_kpi": True,
        },
        {
            "kind": "kpi",
            "id": "stageClimb",
            "label": "📈 爬坡期 (5k-2w曝光)",
            "value": "计算中",
            "delta": "",
            "detail": "",
            "stage_kpi": True,
        },
        {
            "kind": "kpi",
            "id": "stageViral",
            "label": "🔥 爆款期 (2w+曝光)",
            "value": "计算中",
            "delta": "",
            "detail": "",
            "stage_kpi": True,
        },
    ])

    # Account name mapping for stable colors
    account_names = [a["账号"] for a in payload["datasets"]["accountSummary"]]
    account_color_map = {}
    color_keys = ["primary", "secondary", "tertiary", "quaternary", "chart-5", "chart-6"]
    for i, name in enumerate(account_names):
        account_color_map[name] = color_keys[i % len(color_keys)]

    blocks.extend([
        {
            "kind": "chart",
            "id": "panel-gpm-leaderboard",
            "chart_id": "gpmLeaderboard",
            "source_key": "gpmLeaderboard",
            "title": "GPM 排行榜 TOP30",
            "subtitle": "有成交笔记按GPM降序排列",
            "unit": "GPM",
            "source_context": "来源：商品笔记支付数据（两段累加）",
            "allowed_types": ["bar", "scatter"],
            "initial_type": "bar",
            "dense": False,
            "category_count": 30,
        },
        {
            "kind": "chart",
            "id": "panel-gpm-vs-exposure",
            "chart_id": "gpmVsExposure",
            "source_key": "gpmVsExposure",
            "title": "GPM vs 曝光量",
            "subtitle": "有成交笔记的GPM与曝光量关系",
            "unit": "GPM / 曝光量",
            "source_context": "来源：有成交笔记数据",
            "allowed_types": ["scatter"],
            "initial_type": "scatter",
            "dense": True,
        },
        {
            "kind": "chart",
            "id": "panel-quadrant-matrix",
            "chart_id": "quadrantMatrix",
            "source_key": "quadrantMatrix",
            "title": "四象限素材矩阵",
            "subtitle": "X=曝光量, Y=GPM · 按中位数分割四象限",
            "unit": "曝光量 / GPM",
            "source_context": "来源：有成交笔记 · 中位数动态分割",
            "allowed_types": ["scatter"],
            "initial_type": "scatter",
            "dense": False,
        },
        {
            "kind": "chart",
            "id": "panel-ctr-cvr-matrix",
            "chart_id": "ctrCvrMatrix",
            "source_key": "ctrCvrMatrix",
            "title": "CTR-CVR 转化矩阵",
            "subtitle": "X=点击率, Y=转化率 · 按中位数分割四象限",
            "unit": "CTR / CVR",
            "source_context": "来源：有成交笔记 · CTR=阅读量/曝光量, CVR=支付订单/商品点击",
            "allowed_types": ["scatter"],
            "initial_type": "scatter",
            "dense": False,
        },
        {
            "kind": "chart",
            "id": "panel-account-comparison",
            "chart_id": "accountComparison",
            "source_key": "accountComparison",
            "title": "账号对比",
            "subtitle": "各账号总支付金额与平均GPM",
            "unit": "金额（元）",
            "source_context": "来源：按账号汇总",
            "allowed_types": ["bar", "pie"],
            "initial_type": "bar",
            "account_color_map": account_color_map,
        },
        {
            "kind": "chart",
            "id": "panel-product-comparison",
            "chart_id": "productComparison",
            "source_key": "productComparison",
            "title": "商品效率对比",
            "subtitle": "各商品的GPM、CTR、CVR全链路表现",
            "unit": "金额（元）",
            "source_context": "来源：按商品ID汇总 · 组合视角分析",
            "allowed_types": ["bar"],
            "initial_type": "bar",
            "dense": False,
        },
        {
            "kind": "chart",
            "id": "panel-funnel",
            "chart_id": "conversionFunnel",
            "source_key": "conversionFunnel",
            "title": "转化漏斗",
            "subtitle": "曝光→阅读→商品点击→成交 · 全链路转化",
            "unit": "转化率 %",
            "source_context": "来源：全部笔记全链路漏斗分析",
            "allowed_types": ["funnel"],
            "initial_type": "funnel",
            "dense": True,
        },
        {
            "kind": "chart",
            "id": "panel-three-tier",
            "chart_id": "threeTierChart",
            "source_key": "threeTierChart",
            "title": "三层分级贡献",
            "subtitle": "爆款层/潜力层/长尾层的成交占比",
            "unit": "金额（元）",
            "source_context": "来源：有成交笔记按支付金额排名分层",
            "allowed_types": ["bar"],
            "initial_type": "bar",
            "dense": True,
        },
        {
            "kind": "chart",
            "id": "panel-zero-analysis",
            "chart_id": "zeroPayAnalysis",
            "source_key": "zeroPayAnalysis",
            "title": "零成交笔记诊断",
            "subtitle": "CTR × 商品点击率四象限 · 识别无效流量",
            "unit": "CTR / 商品点击率",
            "source_context": "来源：零成交笔记 · 按中位数分割四象限",
            "allowed_types": ["scatter"],
            "initial_type": "scatter",
        },
        {
            "kind": "chart",
            "id": "panel-daily-trend",
            "chart_id": "dailyTrend",
            "source_key": "dailyTrend",
            "title": "每日支付趋势",
            "subtitle": "有成交日期按天汇总支付金额与GPM",
            "unit": "金额（元）",
            "source_context": "来源：有成交笔记按日汇总",
            "allowed_types": ["line", "bar"],
            "initial_type": "line",
        },
        {
            "kind": "chart",
            "id": "panel-promo-comparison",
            "chart_id": "promoComparison",
            "source_key": "promoComparison",
            "title": "推广状态对比",
            "subtitle": "已推广 vs 未推广的成交表现",
            "unit": "金额（元）",
            "source_context": "来源：推广状态分组汇总",
            "allowed_types": ["bar", "pie"],
            "initial_type": "bar",
        },
        {
            "kind": "table",
            "id": "panel-gpm-table",
            "table_id": "gpmTable",
            "source_key": "gpmLeaderboard",
            "title": "GPM 排行榜（明细）",
            "subtitle": "有成交笔记TOP30 · 含曝光阶段、潜力标签、问题诊断",
            "source_context": "来源：商品笔记支付数据（两段累加）",
            "columns": [
                {"field": "笔记ID", "label": "笔记ID", "long_text": True},
                {"field": "笔记标题", "label": "笔记标题", "long_text": True},
                {"field": "账号", "label": "账号"},
                {"field": "曝光阶段", "label": "曝光阶段"},
                {"field": "潜力标签", "label": "潜力标签"},
                {"field": "问题诊断", "label": "问题诊断"},
                {"field": "GPM", "label": "GPM", "numeric": True},
                {"field": "支付金额", "label": "支付金额", "numeric": True},
                {"field": "曝光量", "label": "曝光量", "numeric": True},
            ],
        },
        {
            "kind": "table",
            "id": "panel-exposure-table",
            "table_id": "exposureTable",
            "source_key": "exposureLeaderboard",
            "title": "曝光量排行榜（TOP30）",
            "subtitle": "含GPM、阅读量、互动量",
            "source_context": "来源：全部笔记按曝光量降序",
            "columns": [
                {"field": "笔记ID", "label": "笔记ID", "long_text": True},
                {"field": "笔记标题", "label": "笔记标题", "long_text": True},
                {"field": "账号", "label": "账号"},
                {"field": "曝光量", "label": "曝光量", "numeric": True},
                {"field": "阅读量", "label": "阅读量", "numeric": True},
                {"field": "互动量", "label": "互动量", "numeric": True},
                {"field": "GPM", "label": "GPM", "numeric": True},
                {"field": "GPM状态", "label": "GPM状态"},
            ],
        },
        {
            "kind": "table",
            "id": "panel-quadrant-rank-table",
            "table_id": "quadrantRankTable",
            "source_key": "quadrantRank",
            "title": "四象限素材榜单",
            "subtitle": "有成交笔记按四象限分类 · 优质素材优先",
            "source_context": "来源：有成交笔记 · 按曝光量和GPM中位数动态划分四象限",
            "columns": [
                {"field": "象限", "label": "象限"},
                {"field": "笔记ID", "label": "笔记ID", "long_text": True},
                {"field": "笔记标题", "label": "笔记标题", "long_text": True},
                {"field": "账号", "label": "账号"},
                {"field": "曝光量", "label": "曝光量", "numeric": True},
                {"field": "GPM", "label": "GPM", "numeric": True},
                {"field": "支付金额", "label": "支付金额", "numeric": True},
            ],
        },
        {
            "kind": "table",
            "id": "panel-product-table",
            "table_id": "productTable",
            "source_key": "productTable",
            "title": "商品效率榜单",
            "subtitle": "组合视角：各商品的GPM、CTR、CVR全链路表现",
            "source_context": "来源：按商品ID汇总 · 组合视角分析",
            "columns": [
                {"field": "商品名称", "label": "商品名称", "long_text": True},
                {"field": "笔记数", "label": "笔记数", "numeric": True},
                {"field": "有成交", "label": "有成交", "numeric": True},
                {"field": "总曝光量", "label": "总曝光量", "numeric": True},
                {"field": "总支付金额", "label": "总支付金额", "numeric": True},
                {"field": "平均GPM", "label": "平均GPM", "numeric": True},
                {"field": "平均CTR", "label": "平均CTR(%)", "numeric": True},
                {"field": "平均CVR", "label": "平均CVR(%)", "numeric": True},
            ],
        },
        {
            "kind": "chart",
            "id": "panel-lifecycle-analysis",
            "chart_id": "lifecycleAnalysis",
            "source_key": "lifecycleAnalysis",
            "title": "笔记生命周期分析",
            "subtitle": "按发布天数分组 · 观察各阶段效率变化",
            "unit": "GPM / 转化率",
            "source_context": "来源：按发布时间距今天数分组 · 5个年龄段",
            "allowed_types": ["bar", "pie"],
            "initial_type": "bar",
            "dense": False,
        },
        {
            "kind": "chart",
            "id": "panel-benchmark-comparison",
            "chart_id": "benchmarkComparison",
            "source_key": "benchmarkComparison",
            "title": "大盘基准对比",
            "subtitle": "CTR与CVR对标商笔大盘 · 三色分级",
            "unit": "百分比 %",
            "source_context": "CTR参考: 5.80%~7.84% | CVR参考: 6.54%~8.84%",
            "allowed_types": ["gauge"],
            "initial_type": "gauge",
            "dense": False,
        },
        {
            "kind": "chart",
            "id": "panel-account-product-heatmap",
            "chart_id": "accountProductHeatmap",
            "source_key": "accountProductHeatmap",
            "title": "账号×商品矩阵",
            "subtitle": "各账号在不同商品上的GPM表现热力图",
            "unit": "GPM",
            "source_context": "来源：账号-商品交叉维度 · 平均GPM热力图",
            "allowed_types": ["heatmap"],
            "initial_type": "heatmap",
            "dense": False,
        },
        {
            "kind": "chart",
            "id": "panel-efficiency-scale",
            "chart_id": "efficiencyScale",
            "source_key": "efficiencyScale",
            "title": "效率-规模错位分析",
            "subtitle": "商品维度 · GPM效率 vs 曝光规模四象限",
            "unit": "GPM / 曝光量",
            "source_context": "来源：商品维度汇总 · 按中位数分割四象限",
            "allowed_types": ["scatter"],
            "initial_type": "scatter",
            "dense": False,
        },
        {
            "kind": "note",
            "id": "data-note",
            "title": "数据说明",
            "body": "支付数据来自两个时间段的商品笔记数据（2026-03-01~05-31 和 2026-06-01~08-16），按笔记ID累加后与新笔记数据匹配。曝光量来自2026-08-14导出的笔记分析数据。2309条笔记中770条有成交数据。GPM = 支付金额 ÷ 曝光量 × 1000。CTR = 阅读量 ÷ 曝光量，CVR = 支付订单数 ÷ 商品点击次数。顶栏「商品筛选」可按商品ID切换不同商品的数据，支持按分类（鱼类/虾类/贝类）筛选。\n\n【曝光分层说明】\n🌱 种子期(0-5k)：冷启动阶段，以粉丝和搜索流量为主\n📈 爬坡期(5k-2w)：平台开始推泛流量，效率洼地，是判断素材潜力的关键期\n🔥 爆款期(2w+)：通过赛马筛选的优质内容\n\n【潜力标签说明】\n待放量：爬坡期笔记，互动率/商品点击率/GPM 有2项以上高于中位数\n观察中：有1项高于中位数\n建议优化：全部低于中位数\n\n【问题诊断说明】\n优质素材：CTR和CVR双高\n缺流量：CVR高但CTR低，内容好但缺曝光\n内容需优化：CTR高但CVR低，吸引了点击但转化差\n双低待优化：CTR和CVR都低\n\n【三层分级说明】\n🔥 爆款层(TOP10)：贡献约35%成交，重点维护加投\n⭐ 潜力层(11-50名)：贡献约30%成交，观察优化\n📉 长尾层(50名以后)：贡献约35%成交，批量处理\n\n【零成交笔记四象限说明】\n有潜力(高CTR·高点击)：用户感兴趣也点了商品，但没下单，优化商品承接\n缺流量(低CTR·高点击)：内容好但没人看，优化标题封面或投流\n无效流量(高CTR·低点击)：标题党，吸引了点击但内容不匹配\n双低待优化(低CTR·低点击)：全面优化或直接放弃\n\n【笔记生命周期说明】\n按发布天数分为5个年龄段，观察笔记效率随时间变化：\n0-3天（新发布）/ 3-7天（冷启动）/ 7-30天（成长期）/ 30-90天（成熟期）/ 90天+（长尾期）\n可切换柱状图看多指标对比，或饼图看笔记分布占比\n\n【大盘基准对比说明】\n基于商笔大盘参考区间三色分级：\n🔴 低于大盘：CTR < 5.80% 或 CVR < 6.54%\n🟡 近似大盘：CTR 5.80%~7.84% 或 CVR 6.54%~8.84%\n🟢 优于大盘：CTR > 7.84% 或 CVR > 8.84%\n\n【账号×商品矩阵说明】\n热力图展示各账号在不同商品上的GPM表现\n颜色越深GPM越高，快速识别账号带货优势和机会点\n\n【效率-规模错位说明】\n商品维度四象限：X=曝光规模，Y=GPM效率\n高效规模型：核心主力商品，持续投入\n高效潜力型：效率高但流量不足，可加大投放\n规模低效型：流量大但转化差，优化承接效率\n低效待优化：评估是否继续投入",
            "compact": False,
        },
    ])
    return blocks


def render_dashboard_blocks(blocks: list[dict]) -> str:
    kpis = "\n".join(render_kpi_block(block) for block in blocks if block["kind"] == "kpi")
    panels = []
    for block in blocks:
        if block["kind"] == "chart":
            panels.append(render_chart_block(block))
        elif block["kind"] == "table":
            panels.append(render_table_block(block))
        elif block["kind"] == "note":
            panels.append(render_note_block(block))
    return f"""
    <section class="kpi-grid">{kpis}</section>
    <section class="panel-grid">{"".join(panels)}</section>
    """


ANALYSIS_LOGIC = """Analysis logic
- read_sources() loads the CSV file from data/notes_gpm.csv.
- normalize_snapshots() standardizes numeric fields and deduplicates by 笔记ID.
- make_dashboard_payload() computes KPIs, GPM leaderboard, exposure leaderboard,
  account summary, daily trend, promo comparison, and type comparison.
- GPM = 支付金额 / 曝光量 * 1000 (only for notes with payment > 0).
- dashboard_runtime.js applies client-side date filtering against the analytical date field."""


def build_html(payload: dict) -> str:
    echarts = ECHARTS_JS.read_text(encoding="utf-8")
    runtime = DASHBOARD_RUNTIME_JS.read_text(encoding="utf-8")
    blocks = build_dashboard_blocks(payload)
    content = render_dashboard_blocks(blocks)
    initial_charts = [
        {"id": block["chart_id"], "type": block["initial_type"]}
        for block in blocks
        if block["kind"] == "chart"
    ]
    table_config = {
        "gpmTable": {
            "dataset": "gpmLeaderboard",
            "sortField": "GPM",
            "sortDirection": "desc",
            "limit": 30,
            "columns": [
                {"field": "笔记ID"},
                {"field": "笔记标题"},
                {"field": "账号"},
                {"field": "曝光阶段"},
                {"field": "潜力标签"},
                {"field": "问题诊断"},
                {"field": "GPM", "numeric": True},
                {"field": "支付金额", "numeric": True},
                {"field": "曝光量", "numeric": True},
            ],
        },
        "exposureTable": {
            "dataset": "exposureLeaderboard",
            "sortField": "曝光量",
            "sortDirection": "desc",
            "limit": 30,
            "columns": [
                {"field": "笔记ID"},
                {"field": "笔记标题"},
                {"field": "账号"},
                {"field": "曝光阶段"},
                {"field": "曝光量", "numeric": True},
                {"field": "阅读量", "numeric": True},
                {"field": "互动量", "numeric": True},
                {"field": "GPM", "numeric": True},
                {"field": "GPM状态"},
            ],
        },
        "quadrantRankTable": {
            "dataset": "paidRows",
            "sortField": "支付金额",
            "sortDirection": "desc",
            "limit": 50,
            "columns": [
                {"field": "象限"},
                {"field": "潜力标签"},
                {"field": "问题诊断"},
                {"field": "笔记ID"},
                {"field": "笔记标题"},
                {"field": "账号"},
                {"field": "曝光量", "numeric": True},
                {"field": "GPM", "numeric": True},
                {"field": "支付金额", "numeric": True},
            ],
            "isQuadrantRank": True,
        },
        "productTable": {
            "dataset": "productSummary",
            "useAggregate": "productSummary",
            "sortField": "总支付金额",
            "sortDirection": "desc",
            "limit": 20,
            "columns": [
                {"field": "商品名称"},
                {"field": "笔记数", "numeric": True},
                {"field": "有成交", "numeric": True},
                {"field": "总曝光量", "numeric": True},
                {"field": "总支付金额", "numeric": True},
                {"field": "平均GPM", "numeric": True},
                {"field": "平均CTR", "numeric": True},
                {"field": "平均CVR", "numeric": True},
            ],
        },
    }
    source_map = payload["sourceSnippets"]

    # 生成商品筛选下拉选项（按分类分组）
    product_list = payload.get("productFilter", {}).get("productList", [])
    product_options_html = '<option value="全部">全部商品</option>'
    if product_list:
        categories = {}
        for p in product_list:
            cat = p.get("category", "其他")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(p)
        for cat, items in categories.items():
            product_options_html += f'<optgroup label="{html.escape(cat)}">'
            for p in items:
                label = f'{p["short_name"]} ({p["count"]}条)'
                product_options_html += f'<option value="{html.escape(p["id"])}">{html.escape(label)}</option>'
            product_options_html += '</optgroup>'

    # Build account color keys for chart JS
    account_color_map = {}
    for block in blocks:
        if block.get("kind") == "chart" and block.get("account_color_map"):
            account_color_map = block["account_color_map"]
    account_color_json = json_script(account_color_map)

    css = """
    :root {
      color-scheme: light;
      --ink: #2f3437;
      --muted: #68707a;
      --faint: #8b95a3;
      --line: #e1e5ea;
      --line-strong: #cbd3dc;
      --panel: #FAFAFA;
      --page: #ffffff;
      --surface: #FAFAFA;
      --soft: #f2f3f5;
      --soft-blue: #f3f6fb;
      --control-bg: rgba(255, 255, 255, 0.94);
      --topbar-bg: rgba(255, 255, 255, 0.96);
      --menu-bg: #ffffff;
      --modal-bg: #ffffff;
      --modal-backdrop: rgba(55, 53, 47, 0.34);
      --table-head: #FAFAFA;
      --table-hover: #f1f2ff;
      --chart-bg: #FAFAFA;
      --chart-text: #2f3437;
      --chart-muted: #68707a;
      --chart-line: #e1e5ea;
      --chart-primary: #2F6BFF;
      --chart-secondary: #00BFA6;
      --chart-tertiary: #FF7A3D;
      --chart-quaternary: #F45BB3;
      --chart-1: #F45BB3;
      --chart-2: #2F6BFF;
      --chart-3: #00BFA6;
      --chart-4: #FF7A3D;
      --chart-5: #9BD82E;
      --chart-6: #7C3AED;
      --chart-7: #FFD23F;
      --brand: #6979F8;
      --brand-hover: #9EA9FF;
      --brand-end: #CDD2FD;
      --brand-text: #ffffff;
      --accent: #2F6BFF;
      --accent-2: #00BFA6;
      --warn: #b7791f;
    }
    html[data-theme="trae-dark"] {
      color-scheme: dark;
      --ink: #f5f9fe;
      --muted: #9599a6;
      --faint: #666b75;
      --line: #2a2d31;
      --line-strong: #3a3f45;
      --panel: #1a1b1d;
      --page: #0c0c0d;
      --surface: #222427;
      --soft: #2a2d31;
      --soft-blue: #202123;
      --control-bg: #202123;
      --topbar-bg: rgba(12, 12, 13, 0.92);
      --menu-bg: #202123;
      --modal-bg: #1a1b1d;
      --modal-backdrop: rgba(0, 0, 0, 0.58);
      --table-head: #222427;
      --table-hover: #202123;
      --chart-bg: #222427;
      --chart-text: #d1d3db;
      --chart-muted: #9599a6;
      --chart-line: #2a2d31;
      --chart-primary: #28d9ff;
      --chart-secondary: #32f08c;
      --chart-tertiary: #f6c85f;
      --chart-quaternary: #ff6b9a;
      --chart-1: #32f08c;
      --chart-2: #28d9ff;
      --chart-3: #a78bfa;
      --chart-4: #f6c85f;
      --chart-5: #ff6b9a;
      --chart-6: #6ea8ff;
      --chart-7: #d1d3db;
      --brand: #32f08c;
      --brand-hover: #0fdc78;
      --brand-end: #32f08c;
      --brand-text: #0c0c0d;
      --accent: #32f08c;
      --accent-2: #0fdc78;
    }
    * { box-sizing: border-box; }
    html { background: var(--page); }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      background: var(--page);
      color: var(--ink);
      font-size: 1rem;
      line-height: 1.55;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }
    .topbar {
      position: sticky;
      top: 0;
      z-index: 20;
      border-bottom: 1px solid var(--line);
      background: var(--topbar-bg);
      backdrop-filter: blur(12px);
    }
    .topbar-inner {
      max-width: 1320px;
      margin: 0 auto;
      padding: 14px 22px;
      display: grid;
      grid-template-columns: minmax(260px, 1fr) auto;
      gap: 18px;
      align-items: center;
    }
    h1, h2, p { margin: 0; }
    h1 { font-size: 22px; font-weight: 500; letter-spacing: 0; }
    .subtitle, .freshness, .range-label, .dashboard-panel p, footer, small {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
      font-weight: 400;
    }
    .controls {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: flex-end;
      gap: 10px;
    }
    .range-label { display: none; }
    .product-select-wrap {
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }
    .product-select-label {
      font-size: 13px;
      color: var(--muted);
      white-space: nowrap;
    }
    .product-select {
      height: 34px;
      padding: 0 28px 0 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--control-bg);
      color: var(--ink);
      font-size: 13px;
      cursor: pointer;
      appearance: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23999' stroke-width='2'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 8px center;
    }
    .product-select:focus {
      outline: none;
      border-color: var(--brand);
    }
    .product-select optgroup {
      font-weight: 600;
      color: var(--muted);
    }
    .product-select option {
      color: var(--ink);
    }
    .segmented {
      display: inline-flex;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: var(--control-bg);
    }
    .segmented button, .menu button, .edit-panel button {
      border: 0;
      background: transparent;
      color: var(--ink);
      font: inherit;
      cursor: pointer;
    }
    .segmented button {
      min-width: 44px;
      height: 34px;
      padding: 0 10px;
      border-right: 1px solid var(--line);
      font-size: 13px;
      font-weight: 400;
    }
    .segmented button:last-child { border-right: 0; }
    .segmented button.active { background: var(--brand); color: var(--brand-text); font-weight: 500; }
    .theme-switch button.active { background: var(--brand); color: var(--brand-text); }
    .product-filter button.active { background: var(--accent); color: var(--brand-text); font-weight: 500; }
    .product-filter button { min-width: 52px; }
    .theme-switch button {
      width: 38px;
      min-width: 38px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0;
    }
    .theme-switch svg {
      width: 16px;
      height: 16px;
      stroke-width: 2;
    }
    .date-fields { display: inline-flex; align-items: center; gap: 6px; }
    input[type="date"] {
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 8px;
      background: var(--control-bg);
      color: var(--ink);
      font: inherit;
      font-size: 13px;
      font-weight: 400;
    }
    .dashboard-shell {
      max-width: 1320px;
      margin: 0 auto;
      padding: 18px 22px 44px;
    }
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }
    .kpi-tile {
      min-height: 126px;
      padding: 15px;
      display: grid;
      align-content: space-between;
      gap: 8px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 12px;
    }
    .kpi-tile:first-child {
      background: linear-gradient(135deg, var(--brand) 0%, var(--brand-hover) 58%, var(--brand-end) 100%);
      border-color: var(--brand);
    }
    .kpi-tile p { color: var(--muted); font-size: 13px; font-weight: 500; }
    .kpi-tile strong { font-size: 28px; font-weight: 500; letter-spacing: 0; }
    .kpi-tile span { color: var(--ink); font-size: 13px; font-weight: 500; line-height: 1.4; word-break: break-all; }
    .kpi-tile small { font-size: 12px; font-weight: 400; line-height: 1.4; }
    .kpi-tile:first-child p,
    .kpi-tile:first-child strong,
    .kpi-tile:first-child span,
    .kpi-tile:first-child small { color: var(--brand-text); }
    .panel-grid {
      display: grid;
      grid-template-columns: repeat(12, minmax(0, 1fr));
      gap: 20px 16px;
    }
    .dashboard-panel {
      min-height: 360px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      background: transparent;
      border: 0;
      border-radius: 0;
      padding: 0;
    }
    [data-span="4"] { grid-column: span 4; }
    [data-span="6"] { grid-column: span 6; }
    [data-span="12"] { grid-column: 1 / -1; }
    .dashboard-note {
      min-height: 180px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: transparent;
    }
    .dashboard-panel header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      min-height: 42px;
    }
    .dashboard-panel h2 { font-size: 17px; font-weight: 500; letter-spacing: 0; }
    .chart {
      width: 100%;
      height: 276px;
      min-height: 276px;
      padding: 8px 0 6px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--chart-bg);
    }
    .chart-actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
      flex: 0 0 auto;
      position: relative;
      z-index: 12;
    }
    .toolbox { position: relative; flex: 0 0 auto; }
    .tool-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 3px;
      width: 34px;
      height: 30px;
      border: 1px solid var(--line-strong);
      border-radius: 999px;
      background: var(--control-bg);
      color: var(--muted);
      cursor: pointer;
      font-size: 0;
      line-height: 0;
      padding: 0;
      opacity: 0;
      transition: opacity 140ms ease, background-color 140ms ease;
    }
    .tool-button .dot {
      display: block;
      width: 3px;
      height: 3px;
      border-radius: 50%;
      background: currentColor;
    }
    .dashboard-panel:hover .tool-button,
    .dashboard-panel:focus-within .tool-button,
    .dashboard-note:hover .tool-button,
    .dashboard-note:focus-within .tool-button { opacity: 1; }
    .menu {
      display: none;
      position: absolute;
      right: 0;
      top: 34px;
      z-index: 40;
      width: 188px;
      padding: 6px;
      border: 1px solid var(--line-strong);
      border-radius: 8px;
      background: var(--menu-bg);
      box-shadow: 0 8px 18px rgba(32, 33, 36, 0.12);
    }
    .menu.open { display: block; }
    .edit-panel {
      display: none;
      align-items: center;
      gap: 6px;
      height: 28px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--control-bg);
      color: var(--muted);
      font-size: 13px;
    }
    .edit-panel.open { display: flex; }
    .edit-panel label {
      padding-left: 8px;
      white-space: nowrap;
    }
    .edit-panel select {
      height: 26px;
      border: 0;
      border-left: 1px solid var(--line);
      border-radius: 0 5px 5px 0;
      padding: 0 24px 0 7px;
      background: transparent;
      color: var(--ink);
      font: inherit;
      font-size: 13px;
      outline: none;
      cursor: pointer;
    }
    .menu button {
      display: block;
      width: 100%;
      border: 0;
      background: transparent;
      padding: 8px 10px;
      border-radius: 6px;
      text-align: left;
      cursor: pointer;
      color: var(--ink);
      font: inherit;
      font-size: 13px;
    }
    .menu button:hover, .menu button:focus-visible {
      background: var(--soft-blue);
      outline: none;
    }
    .table-scroll {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--surface);
    }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 10px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
    th { color: var(--muted); font-weight: 500; background: var(--table-head); }
    td.num { text-align: center; font-variant-numeric: tabular-nums; }
    tbody tr:last-child td { border-bottom: 0; }
    tbody tr:hover td { background: var(--table-hover); }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 24px;
      background: var(--modal-backdrop);
      z-index: 50;
    }
    .modal-backdrop.open { display: flex; }
    .modal {
      width: min(860px, 100%);
      max-height: min(780px, 92vh);
      overflow: auto;
      border-radius: 16px;
      background: var(--modal-bg);
      border: 1px solid var(--line-strong);
      box-shadow: 0 18px 48px rgba(55, 53, 47, 0.18);
    }
    .modal-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      padding: 18px 20px 14px;
      border-bottom: 1px solid var(--line);
    }
    .modal-head h3 {
      margin: 0;
      font-size: 16px;
      line-height: 1.4;
      font-weight: 600;
    }
    .modal-subtitle {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
    }
    .modal-body { padding: 18px 20px 20px; }
    .source-section + .source-section { margin-top: 16px; }
    .source-section h4 {
      margin: 0 0 8px;
      color: var(--ink);
      font-size: 14px;
      line-height: 1.4;
      font-weight: 600;
    }
    .code-wrap { position: relative; }
    pre {
      margin: 0;
      padding: 14px;
      overflow: auto;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: var(--soft);
      color: var(--ink);
      font-size: 12px;
      line-height: 1.5;
    }
    .close {
      width: 32px;
      height: 32px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 0;
      border-radius: 999px;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      padding: 0;
    }
    .close svg { width: 18px; height: 18px; stroke-width: 2.1; }
    .close:hover, .close:focus-visible { background: var(--soft); outline: none; }
    .copy-button {
      position: absolute;
      right: 8px;
      top: 8px;
      width: 28px;
      height: 28px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--control-bg);
      color: var(--muted);
      cursor: pointer;
    }
    .copy-button svg { width: 15px; height: 15px; stroke-width: 2; }
    .copy-button:hover, .copy-button:focus-visible {
      background: var(--soft);
      color: var(--ink);
      outline: none;
    }
    @media (max-width: 900px) {
      .topbar-inner { grid-template-columns: 1fr; }
      .controls { justify-content: flex-start; }
      .kpi-grid { grid-template-columns: 1fr; }
      .dashboard-panel, .dashboard-note, [data-span] { grid-column: 1 / -1; }
    }
    @media (max-width: 620px) {
      .topbar-inner, .dashboard-shell { padding-left: 14px; padding-right: 14px; }
      .segmented { width: 100%; }
      .segmented button { flex: 1; min-width: 0; }
      .date-fields { width: 100%; }
      input[type="date"] { min-width: 0; width: 100%; }
      .chart { height: 240px; min-height: 240px; }
    }
    """

    chart_js = f"""
    const dashboardPayload = {json_script(payload)};
    function cssToken(name) {{
      return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }}
    function chartTheme() {{
      return {{
        text: cssToken("--chart-text"),
        muted: cssToken("--chart-muted"),
        line: cssToken("--chart-line"),
        primary: cssToken("--chart-primary"),
        secondary: cssToken("--chart-secondary"),
        tertiary: cssToken("--chart-tertiary"),
        quaternary: cssToken("--chart-quaternary"),
        palette: [1, 2, 3, 4, 5, 6, 7].map(index => cssToken("--chart-" + index))
      }};
    }}
    function axisStyle(extra) {{
      const theme = chartTheme();
      const base = {{
        axisLabel: {{ color: theme.muted }},
        axisLine: {{ lineStyle: {{ color: theme.line }} }},
        axisTick: {{ lineStyle: {{ color: theme.line }} }},
        splitLine: {{ lineStyle: {{ color: theme.line }} }}
      }};
      const merged = Object.assign({{}}, base, extra || {{}});
      merged.axisLabel = Object.assign({{}}, base.axisLabel, (extra || {{}}).axisLabel || {{}});
      return merged;
    }}
    function chartBase(...colorKeys) {{
      const theme = chartTheme();
      return {{
        textStyle: {{ color: theme.text }},
        color: colorKeys.map(key => theme[key] || key)
      }};
    }}
    const accountColorMap = {account_color_json};
    function categoricalColor(name, index) {{
      const key = String(name || "").trim();
      const theme = chartTheme();
      const token = accountColorMap[key] || "chart-" + ((index % 7) + 1);
      return theme[token] || token;
    }}
    function fmtMoney(v) {{
      return "¥" + Number(v).toLocaleString("zh-CN", {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
    }}
    function fmtNum(v) {{
      return Number(v).toLocaleString("zh-CN");
    }}
    const chartFactories = {{
      // GPM leaderboard - horizontal bar
      gpmLeaderboard: function(type, filteredRows) {{
        const rows = filteredRows("gpmLeaderboard");
        const top10 = rows.slice(0, 10);
        const names = top10.map(r => (r["笔记标题"] || "").slice(0, 18));
        if (type === "scatter") {{
          return {{
            ...chartBase("primary", "secondary"),
            tooltip: {{ trigger: "item", formatter: function(params) {{
              const row = top10[params.dataIndex];
              return row["笔记标题"] + "<br/>GPM: " + row["GPM"] + "<br/>支付金额: " + fmtMoney(row["支付金额"]) + "<br/>曝光量: " + fmtNum(row["曝光量"]);
            }} }},
            grid: {{ left: 60, right: 24, top: 28, bottom: 36 }},
            xAxis: axisStyle({{ type: "value", name: "GPM", nameLocation: "middle", nameGap: 28 }}),
            yAxis: axisStyle({{ type: "value", name: "支付金额", nameLocation: "middle", nameGap: 40 }}),
            series: [{{ type: "scatter", symbolSize: function(val) {{ return Math.max(6, Math.sqrt(val[0]) * 2.5); }}, data: top10.map(r => [r["GPM"], r["支付金额"]]) }}]
          }};
        }}
        return {{
          ...chartBase("primary"),
          tooltip: {{ trigger: "axis", axisPointer: {{ type: "shadow" }} }},
          grid: {{ left: 54, right: 60, top: 20, bottom: 8 }},
          xAxis: axisStyle({{ type: "value", axisLabel: {{ formatter: function(v) {{ return v.toFixed(0) }} }} }}),
          yAxis: axisStyle({{ type: "category", data: names.reverse(), axisLabel: {{ overflow: "truncate", width: 90 }} }}),
          series: [{{
            type: "bar",
            data: top10.map(r => r["GPM"]).reverse(),
            barMaxWidth: 24,
            label: {{ show: true, position: "right", formatter: function(p) {{ return p.value.toFixed(1) }}, color: cssToken("--chart-muted"), fontSize: 11 }}
          }}]
        }};
      }},
      // GPM vs Exposure scatter
      gpmVsExposure: function(type, filteredRows) {{
        const rows = filteredRows("paidRows");
        const theme = chartTheme();
        return {{
          ...chartBase("primary"),
          tooltip: {{ trigger: "item", formatter: function(params) {{
            const row = rows[params.dataIndex];
            return (row["笔记标题"] || "").slice(0, 20) + "<br/>GPM: " + row["GPM"].toFixed(2) + "<br/>曝光量: " + fmtNum(row["曝光量"]) + "<br/>支付金额: " + fmtMoney(row["支付金额"]);
          }} }},
          grid: {{ left: 52, right: 18, top: 28, bottom: 36 }},
          xAxis: axisStyle({{ type: "value", name: "曝光量", nameLocation: "middle", nameGap: 28, axisLabel: {{ formatter: function(v) {{ return fmtNum(v) }} }} }}),
          yAxis: axisStyle({{ type: "value", name: "GPM", nameLocation: "middle", nameGap: 36 }}),
          series: [{{
            type: "scatter",
            symbolSize: 8,
            data: rows.map(r => [r["曝光量"], r["GPM"]]),
            itemStyle: {{ opacity: 0.55 }}
          }}]
        }};
      }},
      // Quadrant matrix
      quadrantMatrix: function(type, filteredRows) {{
        const rows = filteredRows("paidRows");
        if (rows.length === 0) {{
          return {{ ...chartBase(), series: [] }};
        }}
        const theme = chartTheme();
        const exps = rows.map(r => r["曝光量"]).sort((a, b) => a - b);
        const gpms = rows.map(r => r["GPM"]).sort((a, b) => a - b);
        const medExp = exps[Math.floor(exps.length / 2)];
        const medGpm = gpms[Math.floor(gpms.length / 2)];

        const qColors = {{
          q1: theme["chart-1"] || "#22c55e", // 高曝光高GPM - 绿
          q2: theme["chart-2"] || "#3b82f6", // 低曝光高GPM - 蓝
          q3: theme["chart-5"] || "#9ca3af", // 低曝光低GPM - 灰
          q4: theme["chart-3"] || "#f59e0b", // 高曝光低GPM - 橙
        }};
        const qLabels = {{
          q1: "优质素材(高曝光·高GPM)",
          q2: "潜力素材(低曝光·高GPM)",
          q3: "待优化(低曝光·低GPM)",
          q4: "需改进(高曝光·低GPM)",
        }};

        const quadrants = {{ q1: [], q2: [], q3: [], q4: [] }};
        rows.forEach((r) => {{
          const hiExp = r["曝光量"] >= medExp;
          const hiGpm = r["GPM"] >= medGpm;
          const key = hiExp ? (hiGpm ? "q1" : "q4") : (hiGpm ? "q2" : "q3");
          quadrants[key].push(r);
        }});

        // 计算全局最大支付金额用于气泡大小归一化
        const allPays = rows.map(r => r["支付金额"] || 0);
        const maxPay = Math.max(...allPays) || 1;
        const minBubble = 6;
        const maxBubble = 36;
        
        const series = Object.entries(quadrants).map(([key, data]) => ({{
          name: qLabels[key],
          type: "scatter",
          symbolSize: function(val) {{
            const pay = val[2] && val[2]["支付金额"] ? val[2]["支付金额"] : 0;
            // 对数缩放 + 线性映射，避免头部值过大
            const logPay = Math.log10(pay + 10);
            const logMax = Math.log10(maxPay + 10);
            const ratio = logPay / logMax;
            return minBubble + ratio * (maxBubble - minBubble);
          }},
          data: data.map(r => [r["曝光量"], r["GPM"], r]),
          itemStyle: {{ color: qColors[key], opacity: 0.75 }},
          emphasis: {{ itemStyle: {{ opacity: 1, shadowBlur: 10 }} }},
        }}));

        const maxExp = Math.max(...exps) * 1.05;
        const maxGpm = Math.max(...gpms) * 1.05;

        return {{
          ...chartBase(),
          color: [qColors.q1, qColors.q2, qColors.q3, qColors.q4],
          tooltip: {{
            trigger: "item",
            formatter: function(params) {{
              const row = params.data[2];
              return (row["笔记标题"] || "").slice(0, 24) +
                "<br/>笔记ID: " + (row["笔记ID"] || "") +
                "<br/>账号: " + (row["账号"] || "") +
                "<br/>曝光量: " + fmtNum(row["曝光量"]) +
                "<br/>GPM: " + row["GPM"].toFixed(2) +
                "<br/>支付金额: " + fmtMoney(row["支付金额"]) +
                "<br/>象限: " + params.seriesName;
            }}
          }},
          legend: {{
            data: Object.values(qLabels),
            bottom: 0,
            textStyle: {{ color: theme.text, fontSize: 11 }},
            itemWidth: 10,
            itemHeight: 10,
          }},
          grid: {{ left: 60, right: 24, top: 28, bottom: 56 }},
          xAxis: axisStyle({{
            type: "value",
            name: "曝光量",
            nameLocation: "middle",
            nameGap: 28,
            max: maxExp,
            axisLabel: {{ formatter: function(v) {{ return fmtNum(v) }} }},
          }}),
          yAxis: axisStyle({{
            type: "value",
            name: "GPM",
            nameLocation: "middle",
            nameGap: 36,
            max: maxGpm,
          }}),
          series: [
            {{
              type: "scatter",
              name: "象限分割线",
              data: [],
              markLine: {{
                silent: true,
                symbol: "none",
                lineStyle: {{ type: "dashed", color: theme.text, opacity: 0.3, width: 1 }},
                label: {{ show: true, position: "end", formatter: "中位数", fontSize: 10, color: theme.muted }},
                data: [
                  {{ xAxis: medExp, label: {{ position: "start", formatter: "曝光中位数", fontSize: 10, color: theme.muted }} }},
                  {{ yAxis: medGpm, label: {{ position: "end", formatter: "GPM中位数", fontSize: 10, color: theme.muted }} }},
                ],
              }},
            }},
            ...series,
            {{
              type: "scatter",
              name: "象限标签",
              data: [],
              markText: {{
                silent: true,
                data: [
                  {{ name: "优质素材", xAxis: maxExp * 0.85, yAxis: maxGpm * 0.92, label: {{ color: qColors.q1, fontSize: 11, fontWeight: 600 }} }},
                  {{ name: "潜力素材", xAxis: maxExp * 0.15, yAxis: maxGpm * 0.92, label: {{ color: qColors.q2, fontSize: 11, fontWeight: 600 }} }},
                  {{ name: "待优化", xAxis: maxExp * 0.15, yAxis: maxGpm * 0.08, label: {{ color: qColors.q3, fontSize: 11, fontWeight: 600 }} }},
                  {{ name: "需改进", xAxis: maxExp * 0.85, yAxis: maxGpm * 0.08, label: {{ color: qColors.q4, fontSize: 11, fontWeight: 600 }} }},
                ],
              }},
            }},
          ],
        }};
      }},
      // CTR-CVR matrix
      ctrCvrMatrix: function(type, filteredRows) {{
        const rows = filteredRows("paidRows").filter(r => r["曝光量"] > 0 && r["商品点击次数"] > 0);
        if (rows.length === 0) {{
          return {{ ...chartBase(), series: [] }};
        }}
        const theme = chartTheme();
        // CTR = 阅读量 / 曝光量, CVR = 支付订单数 / 商品点击次数
        const dataWithMetrics = rows.map(r => ({{
          ...r,
          CTR: (r["阅读量"] || 0) / (r["曝光量"] || 1),
          CVR: (r["支付订单数"] || 0) / (r["商品点击次数"] || 1),
        }}));
        const ctrs = dataWithMetrics.map(r => r.CTR).sort((a, b) => a - b);
        const cvrs = dataWithMetrics.map(r => r.CVR).sort((a, b) => a - b);
        const medCtr = ctrs[Math.floor(ctrs.length / 2)];
        const medCvr = cvrs[Math.floor(cvrs.length / 2)];

        const qColors = {{
          q1: theme["chart-1"] || "#22c55e", // 高CTR高CVR - 绿
          q2: theme["chart-2"] || "#3b82f6", // 低CTR高CVR - 蓝
          q3: theme["chart-5"] || "#9ca3af", // 低CTR低CVR - 灰
          q4: theme["chart-3"] || "#f59e0b", // 高CTR低CVR - 橙
        }};
        const qLabels = {{
          q1: "高效转化(高CTR·高CVR)",
          q2: "转化黑马(低CTR·高CVR)",
          q3: "待优化(低CTR·低CVR)",
          q4: "流量虚高(高CTR·低CVR)",
        }};

        const quadrants = {{ q1: [], q2: [], q3: [], q4: [] }};
        dataWithMetrics.forEach((r) => {{
          const hiCtr = r.CTR >= medCtr;
          const hiCvr = r.CVR >= medCvr;
          const key = hiCtr ? (hiCvr ? "q1" : "q4") : (hiCvr ? "q2" : "q3");
          quadrants[key].push(r);
        }});

        // 计算全局最大支付金额用于气泡大小归一化
        const allPays2 = dataWithMetrics.map(r => r["支付金额"] || 0);
        const maxPay2 = Math.max(...allPays2) || 1;
        
        const series = Object.entries(quadrants).map(([key, data]) => ({{
          name: qLabels[key],
          type: "scatter",
          symbolSize: function(val) {{
            const pay = val[2] && val[2]["支付金额"] ? val[2]["支付金额"] : 0;
            // 对数缩放 + 线性映射，避免头部值过大
            const logPay = Math.log10(pay + 10);
            const logMax = Math.log10(maxPay2 + 10);
            const ratio = logPay / logMax;
            return 6 + ratio * 30;
          }},
          data: data.map(r => [r.CTR * 100, r.CVR * 100, r]),
          itemStyle: {{ color: qColors[key], opacity: 0.75 }},
          emphasis: {{ itemStyle: {{ opacity: 1, shadowBlur: 10 }} }},
        }}));

        const maxCtr = Math.min(100, Math.max(...ctrs) * 100 * 1.05);
        const maxCvr = Math.min(50, Math.max(...cvrs) * 100 * 1.1);

        return {{
          ...chartBase(),
          color: [qColors.q1, qColors.q2, qColors.q3, qColors.q4],
          tooltip: {{
            trigger: "item",
            formatter: function(params) {{
              const row = params.data[2];
              return (row["笔记标题"] || "").slice(0, 24) +
                "<br/>笔记ID: " + (row["笔记ID"] || "") +
                "<br/>账号: " + (row["账号"] || "") +
                "<br/>CTR: " + row.CTR.toFixed(2) + "%" +
                "<br/>CVR: " + row.CVR.toFixed(2) + "%" +
                "<br/>曝光量: " + fmtNum(row["曝光量"]) +
                "<br/>支付金额: " + fmtMoney(row["支付金额"]) +
                "<br/>象限: " + params.seriesName;
            }}
          }},
          legend: {{
            data: Object.values(qLabels),
            bottom: 0,
            textStyle: {{ color: theme.text, fontSize: 11 }},
            itemWidth: 10,
            itemHeight: 10,
          }},
          grid: {{ left: 60, right: 24, top: 28, bottom: 56 }},
          xAxis: axisStyle({{
            type: "value",
            name: "CTR(点击率 %)",
            nameLocation: "middle",
            nameGap: 28,
            max: maxCtr,
            axisLabel: {{ formatter: function(v) {{ return v.toFixed(1) + "%" }} }},
          }}),
          yAxis: axisStyle({{
            type: "value",
            name: "CVR(转化率 %)",
            nameLocation: "middle",
            nameGap: 36,
            max: maxCvr,
            axisLabel: {{ formatter: function(v) {{ return v.toFixed(1) + "%" }} }},
          }}),
          series: [
            {{
              type: "scatter",
              name: "象限分割线",
              data: [],
              markLine: {{
                silent: true,
                symbol: "none",
                lineStyle: {{ type: "dashed", color: theme.text, opacity: 0.3, width: 1 }},
                data: [
                  {{ xAxis: medCtr * 100, label: {{ position: "start", formatter: "CTR中位数", fontSize: 10, color: theme.muted }} }},
                  {{ yAxis: medCvr * 100, label: {{ position: "end", formatter: "CVR中位数", fontSize: 10, color: theme.muted }} }},
                ],
              }},
            }},
            ...series,
            {{
              type: "scatter",
              name: "象限标签",
              data: [],
              markText: {{
                silent: true,
                data: [
                  {{ name: "高效转化", xAxis: maxCtr * 0.85, yAxis: maxCvr * 0.92, label: {{ color: qColors.q1, fontSize: 11, fontWeight: 600 }} }},
                  {{ name: "转化黑马", xAxis: maxCtr * 0.15, yAxis: maxCvr * 0.92, label: {{ color: qColors.q2, fontSize: 11, fontWeight: 600 }} }},
                  {{ name: "待优化", xAxis: maxCtr * 0.15, yAxis: maxCvr * 0.08, label: {{ color: qColors.q3, fontSize: 11, fontWeight: 600 }} }},
                  {{ name: "流量虚高", xAxis: maxCtr * 0.85, yAxis: maxCvr * 0.08, label: {{ color: qColors.q4, fontSize: 11, fontWeight: 600 }} }},
                ],
              }},
            }},
          ],
        }};
      }},
      // Product comparison (商品效率对比)
      productComparison: function(type, filteredRows, aggregate) {{
        const rows = aggregate().productSummary || [];
        if (rows.length === 0) return {{ ...chartBase(), series: [] }};
        const topRows = rows.slice(0, 10);
        const names = topRows.map(r => (r["商品名称"] || "").slice(0, 12));
        const theme = chartTheme();
        return {{
          ...chartBase("primary", "secondary"),
          tooltip: {{
            trigger: "axis",
            axisPointer: {{ type: "shadow" }},
            formatter: function(params) {{
              const idx = params[0].dataIndex;
              const r = topRows[idx];
              return (r["商品名称"] || "") +
                "<br/>笔记数: " + r["笔记数"] +
                "<br/>总支付: ¥" + Number(r["总支付金额"]).toFixed(2) +
                "<br/>平均GPM: " + Number(r["平均GPM"]).toFixed(2) +
                "<br/>平均CTR: " + Number(r["平均CTR"]).toFixed(2) + "%" +
                "<br/>平均CVR: " + Number(r["平均CVR"]).toFixed(2) + "%";
            }}
          }},
          legend: {{ data: ["总支付金额", "平均GPM"], textStyle: {{ color: cssToken("--chart-text") }} }},
          grid: {{ left: 74, right: 18, top: 36, bottom: 24 }},
          xAxis: axisStyle({{ type: "value" }}),
          yAxis: axisStyle({{ type: "category", data: names.reverse(), axisLabel: {{ overflow: "truncate", width: 100 }} }}),
          series: [
            {{ type: "bar", name: "总支付金额", data: topRows.map(r => r["总支付金额"]).reverse(), barMaxWidth: 20, barGap: "30%" }},
            {{ type: "bar", name: "平均GPM", data: topRows.map(r => r["平均GPM"]).reverse(), barMaxWidth: 20 }}
          ]
        }};
      }},
      // Conversion funnel (转化漏斗)
      conversionFunnel: function(type, filteredRows, aggregate) {{
        const funnel = aggregate().funnel || [];
        if (funnel.length === 0) return {{ ...chartBase(), series: [] }};
        const theme = chartTheme();
        const colors = [theme["primary"] || "#3b82f6", theme["secondary"] || "#22c55e", theme["tertiary"] || "#f59e0b", theme["chart-5"] || "#ef4444"];
        return {{
          ...chartBase(),
          tooltip: {{
            trigger: "item",
            formatter: function(params) {{
              const d = funnel[params.dataIndex];
              return d["环节"] +
                "<br/>数值: " + Number(d["数值"]).toLocaleString() +
                "<br/>转化率: " + Number(d["转化率"]).toFixed(2) + "%";
            }}
          }},
          series: [{{
            type: "funnel",
            left: "10%",
            top: 20,
            bottom: 20,
            width: "80%",
            min: 0,
            max: 100,
            minSize: "20%",
            maxSize: "100%",
            sort: "descending",
            gap: 4,
            label: {{
              show: true,
              position: "inside",
              formatter: function(params) {{
                const d = funnel[params.dataIndex];
                return d["环节"] + "\\n" + Number(d["转化率"]).toFixed(1) + "%";
              }},
              color: "#fff",
              fontSize: 12,
            }},
            labelLine: {{ show: false }},
            itemStyle: {{ borderColor: "#fff", borderWidth: 2 }},
            emphasis: {{ label: {{ fontSize: 14 }} }},
            data: funnel.map((d, i) => ({{
              name: d["环节"],
              value: d["转化率"],
              itemStyle: {{ color: colors[i % colors.length] }}
            }}))
          }}]
        }};
      }},
      // Three-tier distribution (三层分级)
      threeTierChart: function(type, filteredRows, aggregate) {{
        const tiers = aggregate().threeTier || [];
        if (tiers.length === 0) return {{ ...chartBase(), series: [] }};
        const theme = chartTheme();
        return {{
          ...chartBase("chart-1", "chart-2", "chart-3"),
          tooltip: {{
            trigger: "axis",
            axisPointer: {{ type: "shadow" }},
            formatter: function(params) {{
              const idx = params[0].dataIndex;
              const t = tiers[idx];
              return t["层级"] +
                "<br/>笔记数: " + t["笔记数"] +
                "<br/>支付金额: ¥" + Number(t["支付金额"]).toFixed(2) +
                "<br/>占比: " + Number(t["占比"]).toFixed(1) + "%";
            }}
          }},
          legend: {{ data: ["支付金额", "笔记数"], textStyle: {{ color: cssToken("--chart-text") }} }},
          grid: {{ left: 74, right: 24, top: 36, bottom: 24 }},
          xAxis: axisStyle({{ type: "value" }}),
          yAxis: axisStyle({{ type: "category", data: tiers.map(t => t["层级"]).reverse() }}),
          series: [
            {{ type: "bar", name: "支付金额", data: tiers.map(t => t["支付金额"]).reverse(), barMaxWidth: 24 }},
            {{ type: "bar", name: "笔记数", data: tiers.map(t => t["笔记数"]).reverse(), barMaxWidth: 24, yAxisIndex: 0 }}
          ]
        }};
      }},
      // Zero-payment analysis (零成交笔记四象限)
      zeroPayAnalysis: function(type, filteredRows, aggregate) {{
        const zero = aggregate().zeroAnalysis || {{}};
        const quads = zero["四象限"] || {{}};
        const medCtr = zero["中位数CTR"] || 0;
        const medClick = zero["中位数商品点击率"] || 0;
        const theme = chartTheme();
        const qColors = {{
          q1: theme["chart-3"] || "#f59e0b",  // 高CTR 高点击 - 橙：有潜力
          q2: theme["chart-2"] || "#22c55e",  // 低CTR 高点击 - 绿：缺流量
          q3: theme["chart-5"] || "#9ca3af",  // 低CTR 低点击 - 灰：双低
          q4: theme["chart-1"] || "#ef4444",  // 高CTR 低点击 - 红：标题党
        }};
        const qLabels = {{
          q1: "有潜力(高CTR·高点击)",
          q2: "缺流量(低CTR·高点击)",
          q3: "双低待优化(低CTR·低点击)",
          q4: "无效流量(高CTR·低点击)",
        }};
        const series = Object.entries(quads).map(([key, data]) => ({{
          name: qLabels[key],
          type: "scatter",
          symbolSize: function(val) {{
            const exp = val[2] && val[2]["曝光量"] ? val[2]["曝光量"] : 0;
            return Math.max(5, Math.sqrt(exp / 100 + 10) * 1.2);
          }},
          data: data.map(r => [r.CTR || 0, r["商品点击率"] || 0, r]),
          itemStyle: {{ color: qColors[key], opacity: 0.7 }},
          emphasis: {{ itemStyle: {{ opacity: 1, shadowBlur: 8 }} }},
        }}));
        const maxCtrShow = Math.min(100, (Math.max(...Object.values(quads).flat().map(r => r.CTR || 0), medCtr * 2) || 20) * 1.2);
        const maxClickShow = Math.min(30, (Math.max(...Object.values(quads).flat().map(r => r["商品点击率"] || 0), medClick * 2) || 10) * 1.2);
        return {{
          ...chartBase(),
          color: [qColors.q1, qColors.q2, qColors.q3, qColors.q4],
          tooltip: {{
            trigger: "item",
            formatter: function(params) {{
              const row = params.data[2];
              return (row["笔记标题"] || "").slice(0, 24) +
                "<br/>笔记ID: " + (row["笔记ID"] || "") +
                "<br/>CTR: " + Number(row.CTR || 0).toFixed(2) + "%" +
                "<br/>商品点击率: " + Number(row["商品点击率"] || 0).toFixed(2) + "%" +
                "<br/>曝光量: " + fmtNum(row["曝光量"] || 0) +
                "<br/>分类: " + params.seriesName;
            }}
          }},
          legend: {{
            data: Object.values(qLabels),
            bottom: 0,
            textStyle: {{ color: theme.text, fontSize: 11 }},
            itemWidth: 10,
            itemHeight: 10,
          }},
          grid: {{ left: 60, right: 24, top: 28, bottom: 56 }},
          xAxis: axisStyle({{
            type: "value",
            name: "CTR(点击率 %)",
            nameLocation: "middle",
            nameGap: 28,
            max: maxCtrShow,
          }}),
          yAxis: axisStyle({{
            type: "value",
            name: "商品点击率(%)",
            nameLocation: "middle",
            nameGap: 44,
            max: maxClickShow,
          }}),
          series: series,
          markLine: {{
            silent: true,
            symbol: "none",
            lineStyle: {{ type: "dashed", color: cssToken("--chart-grid") }},
            label: {{ show: false }},
            data: [
              {{ xAxis: medCtr }},
              {{ yAxis: medClick }},
            ]
          }}
        }};
      }},
      // Account comparison
      accountComparison: function(type, filteredRows, aggregate) {{
        const rows = aggregate().accountSummary;
        const names = rows.map(r => r["账号"]);
        if (type === "pie") {{
          return {{
            ...chartBase(),
            color: rows.map((r, i) => categoricalColor(r["账号"], i)),
            tooltip: {{ trigger: "item", formatter: function(params) {{
              return params.name + "<br/>总支付金额: " + fmtMoney(params.value) + "<br/>有成交: " + (rows[params.dataIndex]?.有成交 || "");
            }} }},
            series: [{{ type: "pie", radius: ["40%", "68%"], data: rows.map((r, i) => ({{ name: r["账号"], value: r["总支付金额"] }})), label: {{ show: true, formatter: "{{b}}" }} }}]
          }};
        }}
        return {{
          ...chartBase("primary", "secondary"),
          color: rows.map((r, i) => categoricalColor(r["账号"], i)),
          tooltip: {{ trigger: "axis", axisPointer: {{ type: "shadow" }} }},
          legend: {{ data: ["总支付金额", "平均GPM"], textStyle: {{ color: cssToken("--chart-text") }} }},
          grid: {{ left: 74, right: 18, top: 36, bottom: 24 }},
          xAxis: axisStyle({{ type: "value", axisLabel: {{ formatter: function(v) {{ return fmtMoney(v) }} }} }}),
          yAxis: axisStyle({{ type: "category", data: names }}),
          series: [
            {{ type: "bar", name: "总支付金额", data: rows.map(r => r["总支付金额"]), barMaxWidth: 20, barGap: "30%" }},
            {{ type: "bar", name: "平均GPM", data: rows.map(r => r["平均GPM"]), barMaxWidth: 20 }}
          ]
        }};
      }},
      // Daily payment trend
      dailyTrend: function(type, filteredRows, aggregate) {{
        const rows = aggregate().dailyTrend;
        return {{
          ...chartBase("primary", "secondary"),
          tooltip: {{ trigger: "axis" }},
          legend: {{ data: ["支付金额", "GPM"], textStyle: {{ color: cssToken("--chart-text") }} }},
          grid: {{ left: 52, right: 18, top: 36, bottom: 36 }},
          xAxis: axisStyle({{ type: "category", data: rows.map(r => r.date), axisLabel: {{ hideOverlap: true }} }}),
          yAxis: [
            axisStyle({{ type: "value", name: "支付金额", axisLabel: {{ formatter: function(v) {{ return fmtMoney(v) }} }} }}),
            axisStyle({{ type: "value", name: "GPM", axisLabel: {{ formatter: function(v) {{ return v.toFixed(1) }} }} }})
          ],
          series: [
            {{ type: type, name: "支付金额", data: rows.map(r => r["支付金额"]), yAxisIndex: 0, smooth: type === "line", areaStyle: type === "line" ? {{ opacity: 0.08 }} : undefined }},
            {{ type: type, name: "GPM", data: rows.map(r => r["GPM"]), yAxisIndex: 1, smooth: type === "line" }}
          ]
        }};
      }},
      // Promo status comparison
      promoComparison: function(type, filteredRows, aggregate) {{
        const rows = aggregate().promoSummary;
        if (type === "pie") {{
          return {{
            ...chartBase(),
            tooltip: {{ trigger: "item", formatter: function(params) {{
              return params.name + "<br/>总支付金额: " + fmtMoney(params.value) + "<br/>笔记数: " + (rows[params.dataIndex]?.笔记数 || "");
            }} }},
            series: [{{ type: "pie", radius: ["40%", "68%"], data: rows.map((r, i) => ({{ name: r["推广状态"], value: r["总支付金额"] }})), label: {{ show: true, formatter: "{{b}}: {{d}}%" }} }}]
          }};
        }}
        return {{
          ...chartBase("primary", "secondary"),
          tooltip: {{ trigger: "axis", axisPointer: {{ type: "shadow" }} }},
          legend: {{ data: ["总支付金额", "平均GPM"], textStyle: {{ color: cssToken("--chart-text") }} }},
          grid: {{ left: 74, right: 18, top: 36, bottom: 24 }},
          xAxis: axisStyle({{ type: "value" }}),
          yAxis: axisStyle({{ type: "category", data: rows.map(r => r["推广状态"]) }}),
          series: [
            {{ type: "bar", name: "总支付金额", data: rows.map(r => r["总支付金额"]), barMaxWidth: 24 }},
            {{ type: "bar", name: "平均GPM", data: rows.map(r => r["平均GPM"]), barMaxWidth: 24 }}
          ]
        }};
      }},
      // 生命周期分析
      lifecycleAnalysis: function(type, filteredRows, aggregate) {{
        const lifecycle = aggregate().lifecycleSummary || [];
        if (lifecycle.length === 0) return {{ ...chartBase(), series: [] }};
        const theme = chartTheme();
        const total = lifecycle.reduce((s, r) => s + r["笔记数"], 0);
        const lifecycleColors = ["#22c55e", "#3b82f6", "#f59e0b", "#8b5cf6", "#9ca3af"];
        
        if (type === "pie") {{
          const data = lifecycle.map((r, i) => ({{
            name: r["年龄段"],
            value: r["笔记数"],
            itemStyle: {{ color: lifecycleColors[i % lifecycleColors.length] }}
          }}));
          return {{
            ...chartBase(),
            tooltip: {{
              trigger: "item",
              formatter: function(params) {{
                const d = lifecycle[params.dataIndex];
                return d["年龄段"] +
                  "<br/>笔记数: " + d["笔记数"] + " (" + Math.round(d["笔记数"]/total*100) + "%)" +
                  "<br/>有成交: " + d["有成交"] + " (" + d["成交率"].toFixed(1) + "%)" +
                  "<br/>平均GPM: " + d["平均GPM"].toFixed(2);
              }}
            }},
            series: [{{
              type: "pie",
              radius: ["38%", "68%"],
              avoidLabelOverlap: true,
              itemStyle: {{
                borderRadius: 6,
                borderColor: "#fff",
                borderWidth: 2
              }},
              label: {{ show: true, formatter: "{{b}}\\n{{d}}%", fontSize: 11 }},
              labelLine: {{ show: true, length: 8, length2: 8 }},
              data: data
            }}]
          }};
        }}
        // 柱状图：GPM + CTR + CVR 多指标对比
        return {{
          ...chartBase(),
          tooltip: {{
            trigger: "axis",
            axisPointer: {{ type: "shadow" }},
            formatter: function(params) {{
              const idx = params[0].dataIndex;
              const d = lifecycle[idx];
              return d["年龄段"] +
                "<br/>笔记数: " + d["笔记数"] +
                "<br/>平均GPM: " + d["平均GPM"].toFixed(2) +
                "<br/>平均CTR: " + d["平均CTR"].toFixed(2) + "%" +
                "<br/>平均CVR: " + d["平均CVR"].toFixed(2) + "%" +
                "<br/>成交率: " + d["成交率"].toFixed(1) + "%";
            }}
          }},
          legend: {{
            data: ["平均GPM", "平均CTR(%)", "平均CVR(%)"],
            bottom: 0,
            textStyle: {{ color: theme.text, fontSize: 11 }},
            itemWidth: 12,
            itemHeight: 8,
          }},
          grid: {{ left: 56, right: 20, top: 28, bottom: 44 }},
          xAxis: axisStyle({{ type: "category", data: lifecycle.map(r => r["年龄段"]), axisLabel: {{ fontSize: 11 }} }}),
          yAxis: axisStyle({{ type: "value" }}),
          series: [
            {{
              type: "bar",
              name: "平均GPM",
              data: lifecycle.map(r => r["平均GPM"]),
              itemStyle: {{ color: lifecycleColors[0] }},
              barMaxWidth: 20
            }},
            {{
              type: "bar",
              name: "平均CTR(%)",
              data: lifecycle.map(r => r["平均CTR"]),
              itemStyle: {{ color: lifecycleColors[1] }},
              barMaxWidth: 20
            }},
            {{
              type: "bar",
              name: "平均CVR(%)",
              data: lifecycle.map(r => r["平均CVR"]),
              itemStyle: {{ color: lifecycleColors[2] }},
              barMaxWidth: 20
            }}
          ]
        }};
      }},
      // 基准对比分析
      benchmarkComparison: function(type, filteredRows, aggregate) {{
        const data = aggregate().benchmarkData || {{}};
        const dist = aggregate().benchmarkDistribution || {{ CTR: {{}}, CVR: {{}} }};
        const theme = chartTheme();
        
        const ctrData = data.CTR || {{ value: 0, low: 5.8, high: 7.84, level: "近似大盘", color: "#f59e0b" }};
        const cvrData = data.CVR || {{ value: 0, low: 6.54, high: 8.84, level: "近似大盘", color: "#f59e0b" }};
        
        function gaugeOption(metricData, title, unit) {{
          const range = metricData.high - metricData.low;
          const minVal = Math.min(metricData.low - range * 0.5, metricData.value * 0.8);
          const maxVal = Math.max(metricData.high + range * 0.5, metricData.value * 1.2);
          return {{
            type: "gauge",
            center: ["50%", "55%"],
            radius: "65%",
            startAngle: 210,
            endAngle: -30,
            min: minVal,
            max: maxVal,
            splitNumber: 6,
            axisLine: {{
              lineStyle: {{
                width: 14,
                color: [
                  [metricData.low / maxVal, "#ef4444"],
                  [metricData.high / maxVal, "#f59e0b"],
                  [1, "#22c55e"]
                ]
              }}
            }},
            pointer: {{
              itemStyle: {{ color: metricData.color }},
              width: 3,
              length: "60%"
            }},
            axisTick: {{ distance: -14, length: 4, lineStyle: {{ color: "#fff", width: 1 }} }},
            splitLine: {{ distance: -14, length: 8, lineStyle: {{ color: "#fff", width: 2 }} }},
            axisLabel: {{ color: theme.muted, distance: -24, fontSize: 9 }},
            anchor: {{ show: true, showAbove: true, size: 10, itemStyle: {{ borderWidth: 2, borderColor: metricData.color }} }},
            title: {{
              offsetCenter: [0, "28%"],
              fontSize: 12,
              color: theme.text,
              fontWeight: "normal"
            }},
            detail: {{
              valueAnimation: true,
              fontSize: 20,
              fontWeight: "bold",
              offsetCenter: [0, "0%"],
              formatter: function(value) {{ return value.toFixed(2) + unit; }},
              color: metricData.color
            }},
            data: [{{ value: metricData.value, name: title + "\\n" + metricData.level }}]
          }};
        }}
        
        return {{
          ...chartBase(),
          tooltip: {{
            formatter: function(params) {{
              if (params.seriesType === "gauge") {{
                return params.name + "<br/>当前值: " + params.value.toFixed(2) + "%";
              }}
            }}
          }},
          series: [
            {{
              ...gaugeOption(ctrData, "点击率CTR", "%"),
              center: ["28%", "55%"],
              radius: "65%"
            }},
            {{
              ...gaugeOption(cvrData, "转化率CVR", "%"),
              center: ["72%", "55%"],
              radius: "65%"
            }}
          ],
          graphic: [
            {{
              type: "text",
              left: "center",
              bottom: 4,
              style: {{
                text: "CTR参考: 5.80%~7.84%  |  CVR参考: 6.54%~8.84%",
                fontSize: 10,
                fill: theme.muted,
                textAlign: "center"
              }}
            }}
          ]
        }};
      }},
      // 商品深度分析 - 账号商品矩阵热力图
      accountProductHeatmap: function(type, filteredRows, aggregate) {{
        const depth = aggregate().productDepthAnalysis || {{}};
        const matrix = depth.accountProductMatrix || [];
        const accounts = depth.accountList || [];
        const products = depth.productList || [];
        const theme = chartTheme();
        
        if (matrix.length === 0) return {{ ...chartBase(), series: [] }};
        
        const values = matrix.map(m => m[2]).filter(v => v > 0);
        const maxVal = values.length ? Math.max(...values) : 100;
        
        // 商品名称截断显示，避免X轴过长
        const shortProducts = products.map(p => p.length > 6 ? p.slice(0, 6) + "…" : p);
        
        return {{
          ...chartBase(),
          tooltip: {{
            position: "top",
            formatter: function(params) {{
              const acc = accounts[params.data[0]] || "";
              const prod = products[params.data[1]] || "";
              return "账号: " + acc + "<br/>商品: " + prod + "<br/>平均GPM: " + params.data[2].toFixed(2);
            }}
          }},
          grid: {{ left: 80, right: 24, top: 24, bottom: 72 }},
          xAxis: axisStyle({{
            type: "category",
            data: shortProducts,
            axisLabel: {{ rotate: 45, fontSize: 10, interval: 0 }}
          }}),
          yAxis: axisStyle({{
            type: "category",
            data: accounts,
            axisLabel: {{ fontSize: 10 }}
          }}),
          visualMap: {{
            min: 0,
            max: maxVal,
            precision: 0,
            calculable: true,
            orient: "horizontal",
            left: "center",
            bottom: 10,
            itemWidth: 14,
            itemHeight: 120,
            textStyle: {{ color: theme.muted, fontSize: 10 }},
            inRange: {{
              color: ["#f0fdf4", "#86efac", "#22c55e", "#15803d"]
            }}
          }},
          series: [{{
            name: "平均GPM",
            type: "heatmap",
            data: matrix,
            label: {{
              show: true,
              fontSize: 10,
              formatter: function(params) {{ return params.data[2] > 0 ? params.data[2].toFixed(0) : ""; }},
              color: "#1f2937"
            }},
            emphasis: {{
              itemStyle: {{ shadowBlur: 10, shadowColor: "rgba(0, 0, 0, 0.3)" }}
            }}
          }}]
        }};
      }},
      // 商品深度分析 - 效率规模错位散点图
      efficiencyScale: function(type, filteredRows, aggregate) {{
        const depth = aggregate().productDepthAnalysis || {{}};
        const data = depth.efficiencyScale || [];
        const theme = chartTheme();
        
        if (data.length === 0) return {{ ...chartBase(), series: [] }};
        
        const exps = data.map(d => d["总曝光量"]);
        const gpms = data.map(d => d["平均GPM"]);
        const medExp = exps.sort((a, b) => a - b)[Math.floor(exps.length / 2)];
        const medGpm = gpms.sort((a, b) => a - b)[Math.floor(gpms.length / 2)];
        const maxExp = Math.max(...exps) * 1.1;
        const maxGpm = Math.max(...gpms) * 1.1;
        
        const qColors = {{
          q1: "#22c55e", // 高曝光高GPM - 优质
          q2: "#3b82f6", // 低曝光高GPM - 潜力
          q3: "#9ca3af", // 低曝光低GPM - 待优化
          q4: "#f59e0b", // 高曝光低GPM - 需改进
        }};
        const qLabels = {{
          q1: "高效规模型",
          q2: "高效潜力型",
          q3: "低效待优化",
          q4: "规模低效型",
        }};
        
        const quadrants = {{ q1: [], q2: [], q3: [], q4: [] }};
        data.forEach(d => {{
          const hiExp = d["总曝光量"] >= medExp;
          const hiGpm = d["平均GPM"] >= medGpm;
          const key = hiExp ? (hiGpm ? "q1" : "q4") : (hiGpm ? "q2" : "q3");
          quadrants[key].push(d);
        }});
        
        const series = Object.entries(quadrants).map(([key, items]) => {{
          // 按支付金额排序，只显示TOP5标签，避免遮挡
          const sortedItems = items.slice().sort((a, b) => b["总支付金额"] - a["总支付金额"]);
          const top5Names = new Set(sortedItems.slice(0, 5).map(d => d["商品ID"]));
          
          return {{
            name: qLabels[key],
            type: "scatter",
            symbolSize: function(val) {{
              const pay = val.rawData?.["总支付金额"] || val[2]?.["总支付金额"] || 0;
              return Math.max(8, Math.sqrt(pay + 100) * 0.6);
            }},
            data: items.map(d => [d["总曝光量"], d["平均GPM"], d]),
            itemStyle: {{ color: qColors[key], opacity: 0.75 }},
            emphasis: {{ itemStyle: {{ opacity: 1, shadowBlur: 10 }} }},
            label: {{
              show: false,
              formatter: function(params) {{ return (params.data[2]?.["商品名称"] || "").slice(0, 6); }},
              position: "top",
              fontSize: 10,
              color: theme.text
            }},
            labelLayout: {{ hideOverlap: true }},
            // 只对TOP5数据点显示标签
            data: items.map(d => ({{
              value: [d["总曝光量"], d["平均GPM"]],
              rawData: d,
              label: {{
                show: top5Names.has(d["商品ID"]),
                formatter: (d["商品名称"] || "").slice(0, 6),
                position: "top",
                fontSize: 10,
                color: theme.text
              }}
            }}))
          }};
        }});
        
        return {{
          ...chartBase(),
          color: [qColors.q1, qColors.q2, qColors.q3, qColors.q4],
          tooltip: {{
            trigger: "item",
            formatter: function(params) {{
              const d = params.data.rawData || params.data[2];
              if (!d) return "";
              return (d["商品名称"] || "") +
                "<br/>商品ID: " + (d["商品ID"] || "") +
                "<br/>总曝光量: " + fmtNum(d["总曝光量"]) +
                "<br/>平均GPM: " + d["平均GPM"].toFixed(2) +
                "<br/>总支付金额: " + fmtMoney(d["总支付金额"]) +
                "<br/>笔记数: " + d["笔记数"] +
                "<br/>类型: " + params.seriesName;
            }}
          }},
          legend: {{
            data: Object.values(qLabels),
            bottom: 0,
            textStyle: {{ color: theme.text, fontSize: 11 }},
            itemWidth: 10,
            itemHeight: 10,
          }},
          grid: {{ left: 60, right: 20, top: 28, bottom: 52 }},
          xAxis: axisStyle({{
            type: "value",
            name: "总曝光量",
            nameLocation: "middle",
            nameGap: 28,
            max: maxExp,
            axisLabel: {{ formatter: function(v) {{ return fmtNum(v) }} }}
          }}),
          yAxis: axisStyle({{
            type: "value",
            name: "平均GPM",
            nameLocation: "middle",
            nameGap: 36,
            max: maxGpm
          }}),
          series: [
            {{
              type: "scatter",
              name: "分割线",
              data: [],
              markLine: {{
                silent: true,
                symbol: "none",
                lineStyle: {{ type: "dashed", color: theme.text, opacity: 0.3, width: 1 }},
                label: {{ show: false }},
                data: [
                  {{ xAxis: medExp }},
                  {{ yAxis: medGpm }}
                ]
              }}
            }},
            ...series
          ]
        }};
      }}
    }};
    const sourceMap = {json_script(source_map)};
    const productFilter = {json_script(payload.get("productFilter") or {})};
    const kpiConfig = {{
      totalNotes: {{
        label: "笔记总数",
        value: (rows, paid) => String(rows.length),
        delta: (rows, paid) => `有${{paid.length}}条产生成交`,
        detail: (rows, paid) => rows.length ? `成交率 ${{(paid.length / rows.length * 100).toFixed(1)}}%` : "成交率 0.0%",
      }},
      totalPayment: {{
        label: "总支付金额",
        value: (rows, paid) => fmtMoney(paid.reduce((s, r) => s + (r["支付金额"] || 0), 0)),
        delta: (rows, paid) => `${{paid.reduce((s, r) => s + (r["支付订单数"] || 0), 0)}} 笔订单`,
        detail: (rows, paid) => {{
          const exp = rows.reduce((s, r) => s + (r["曝光量"] || 0), 0);
          const pay = paid.reduce((s, r) => s + (r["支付金额"] || 0), 0);
          return `有支付笔记平均GPM ${{exp ? (pay / exp * 1000).toFixed(2) : 0}}`;
        }},
      }},
      avgGpm30: {{
        label: "当前范围平均GPM",
        value: (rows, paid) => {{
          const exp = rows.reduce((s, r) => s + (r["曝光量"] || 0), 0);
          const pay = paid.reduce((s, r) => s + (r["支付金额"] || 0), 0);
          return exp ? (pay / exp * 1000).toFixed(2) : "0.00";
        }},
        delta: () => "随筛选范围联动",
        detail: () => "GPM = 支付金额 ÷ 曝光量 × 1000",
      }},
      stageSeed: {{
        label: "🌱 种子期 (0-5k曝光)",
        value: (rows, paid) => {{
          const stageRows = rows.filter(r => (r["曝光量"] || 0) < 5000);
          const stagePaid = stageRows.filter(r => (r["支付金额"] || 0) > 0);
          const exp = stageRows.reduce((s, r) => s + (r["曝光量"] || 0), 0);
          const pay = stagePaid.reduce((s, r) => s + (r["支付金额"] || 0), 0);
          return exp ? (pay / exp * 1000).toFixed(2) : "0.00";
        }},
        delta: (rows, paid) => {{
          const stageRows = rows.filter(r => (r["曝光量"] || 0) < 5000);
          const stagePaid = stageRows.filter(r => (r["支付金额"] || 0) > 0);
          return `${{stageRows.length}}条笔记 · ${{stagePaid.length}}条成交`;
        }},
        detail: (rows, paid) => {{
          const stageRows = rows.filter(r => (r["曝光量"] || 0) < 5000);
          const stagePaid = stageRows.filter(r => (r["支付金额"] || 0) > 0);
          const rate = stageRows.length ? (stagePaid.length / stageRows.length * 100).toFixed(1) : "0.0";
          return `成交率 ${{rate}}%`;
        }},
      }},
      stageClimb: {{
        label: "📈 爬坡期 (5k-2w曝光)",
        value: (rows, paid) => {{
          const stageRows = rows.filter(r => (r["曝光量"] || 0) >= 5000 && (r["曝光量"] || 0) < 20000);
          const stagePaid = stageRows.filter(r => (r["支付金额"] || 0) > 0);
          const exp = stageRows.reduce((s, r) => s + (r["曝光量"] || 0), 0);
          const pay = stagePaid.reduce((s, r) => s + (r["支付金额"] || 0), 0);
          return exp ? (pay / exp * 1000).toFixed(2) : "0.00";
        }},
        delta: (rows, paid) => {{
          const stageRows = rows.filter(r => (r["曝光量"] || 0) >= 5000 && (r["曝光量"] || 0) < 20000);
          const stagePaid = stageRows.filter(r => (r["支付金额"] || 0) > 0);
          return `${{stageRows.length}}条笔记 · ${{stagePaid.length}}条成交`;
        }},
        detail: (rows, paid) => {{
          const stageRows = rows.filter(r => (r["曝光量"] || 0) >= 5000 && (r["曝光量"] || 0) < 20000);
          const stagePaid = stageRows.filter(r => (r["支付金额"] || 0) > 0);
          const rate = stageRows.length ? (stagePaid.length / stageRows.length * 100).toFixed(1) : "0.0";
          return `成交率 ${{rate}}% · 效率洼地`;
        }},
      }},
      stageViral: {{
        label: "🔥 爆款期 (2w+曝光)",
        value: (rows, paid) => {{
          const stageRows = rows.filter(r => (r["曝光量"] || 0) >= 20000);
          const stagePaid = stageRows.filter(r => (r["支付金额"] || 0) > 0);
          const exp = stageRows.reduce((s, r) => s + (r["曝光量"] || 0), 0);
          const pay = stagePaid.reduce((s, r) => s + (r["支付金额"] || 0), 0);
          return exp ? (pay / exp * 1000).toFixed(2) : "0.00";
        }},
        delta: (rows, paid) => {{
          const stageRows = rows.filter(r => (r["曝光量"] || 0) >= 20000);
          const stagePaid = stageRows.filter(r => (r["支付金额"] || 0) > 0);
          const totalPay = paid.reduce((s, r) => s + (r["支付金额"] || 0), 0);
          const stagePay = stagePaid.reduce((s, r) => s + (r["支付金额"] || 0), 0);
          const pct = totalPay ? (stagePay / totalPay * 100).toFixed(1) : "0.0";
          return `${{stageRows.length}}条笔记 · 贡献${{pct}}%成交`;
        }},
        detail: (rows, paid) => {{
          const stageRows = rows.filter(r => (r["曝光量"] || 0) >= 20000);
          const stagePaid = stageRows.filter(r => (r["支付金额"] || 0) > 0);
          const rate = stageRows.length ? (stagePaid.length / stageRows.length * 100).toFixed(1) : "0.0";
          return `成交率 ${{rate}}%`;
        }},
      }},
    }};
    setupDashboardRuntime({{
      datasets: dashboardPayload.datasets,
      availableDates: dashboardPayload.availableDates,
      defaultRange: dashboardPayload.defaultRange,
      initialCharts: {json_script(initial_charts)},
      chartFactories,
      sourceMap,
      tables: {json_script(table_config)},
      productFilter,
      kpiConfig,
      fullScript: {js_string(ANALYSIS_LOGIC)},
      modalSubtitlePrefix: "Dashboard panel transform for "
    }});
    """

    return f"""<!-- Generated by Trae Work -->
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(payload["title"])}</title>
  <style>{css}</style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div>
        <h1>{html.escape(payload["title"])}</h1>
        <p class="subtitle">{html.escape(payload["subtitle"])}</p>
        <p class="freshness" id="dataFreshness">最新数据: {html.escape(payload["freshness"]["latestDataDate"])} | 来源: {html.escape(payload["freshness"]["source"])} | {html.escape(payload["timezone"])}</p>
      </div>
      <div class="controls" aria-label="Dashboard time controls">
        <span class="range-label" id="activeRangeLabel"></span>
        <div class="segmented" aria-label="Time preset">
          <button data-range-preset="7D">7D</button>
          <button data-range-preset="30D">30D</button>
          <button data-range-preset="MTD">MTD</button>
          <button data-range-preset="QTD">QTD</button>
          <button data-range-preset="YTD">YTD</button>
          <button data-range-preset="ALL">All</button>
        </div>
        <div class="date-fields">
          <input id="rangeStart" data-range-input type="date" aria-label="Start date">
          <input id="rangeEnd" data-range-input type="date" aria-label="End date">
        </div>
        <div class="product-select-wrap" aria-label="商品筛选">
          <label class="product-select-label" for="productSelect">商品筛选</label>
          <select id="productSelect" class="product-select">
            {product_options_html}
          </select>
        </div>
        <div class="segmented theme-switch" aria-label="Theme">
          <button data-theme-choice="light" type="button" aria-label="Light theme" title="Light">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
              <circle cx="12" cy="12" r="4"></circle>
              <path d="M12 2v2"></path>
              <path d="M12 20v2"></path>
              <path d="m4.93 4.93 1.41 1.41"></path>
              <path d="m17.66 17.66 1.41 1.41"></path>
              <path d="M2 12h2"></path>
              <path d="M20 12h2"></path>
              <path d="m6.34 17.66-1.41 1.41"></path>
              <path d="m19.07 4.93-1.41 1.41"></path>
            </svg>
          </button>
          <button data-theme-choice="trae-dark" type="button" aria-label="Dark theme" title="Dark">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
              <path d="M20.99 13.53A8.5 8.5 0 1 1 10.47 3.01 7 7 0 0 0 20.99 13.53Z"></path>
            </svg>
          </button>
        </div>
      </div>
    </div>
  </header>
  <main class="dashboard-shell">
    {content}
  </main>
  <div id="modalBackdrop" class="modal-backdrop" role="dialog" aria-modal="true">
    <section class="modal">
      <div class="modal-head">
        <div>
          <h3 id="modalTitle">Data Source</h3>
          <p class="modal-subtitle" id="modalSubtitle"></p>
        </div>
        <button class="close" aria-label="Close" onclick="closeModal()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
            <path d="M18 6 6 18"></path>
            <path d="m6 6 12 12"></path>
          </svg>
        </button>
      </div>
      <div class="modal-body">
        <section class="source-section">
          <h4>Panel transform</h4>
          <div class="code-wrap">
            <button class="copy-button" aria-label="Copy panel transform" onclick="copyCode('modalSnippet', this)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
                <rect x="9" y="9" width="11" height="11" rx="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
              </svg>
            </button>
            <pre><code id="modalSnippet"></code></pre>
          </div>
        </section>
        <section class="source-section">
          <h4>Analysis logic</h4>
          <div class="code-wrap">
            <button class="copy-button" aria-label="Copy analysis logic" onclick="copyCode('modalCode', this)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
                <rect x="9" y="9" width="11" height="11" rx="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
              </svg>
            </button>
            <pre><code id="modalCode"></code></pre>
          </div>
        </section>
      </div>
    </section>
  </div>
  <script>{echarts}</script>
  <script>{runtime}</script>
  <script>{chart_js}</script>
</body>
</html>
"""


def main() -> None:
    rows = normalize_snapshots(read_sources())
    if not rows:
        print("ERROR: No data found in data/notes_gpm.csv")
        return
    payload = make_dashboard_payload(rows)
    DASHBOARD_DATA.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    DASHBOARD_HTML.write_text(build_html(payload), encoding="utf-8")
    print(f"Wrote {DASHBOARD_HTML}")
    print(f"Wrote {DASHBOARD_DATA}")


if __name__ == "__main__":
    main()