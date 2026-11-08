#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 【v2.6 新增】professional_profile.py —— S0 专业知识预分析（七镜头透视人物）
#
# 作用：
#   1) build_skeleton()  生成七镜头《专业透视档案》骨架（各节子维度 + 证据状态占位），喂给 AI 填内容；
#   2) scan_markers()    按七镜头各给一组轻量启发式标记词，扫全量语料，返回候选证据行（章号+行号），
#                        帮 AI 把结论挂到原文（注意：只给"候选"，结论仍由 AI 逐条回原文核验）。
# 定位：S0 的离线辅助工具，纯标准库、零依赖、--selftest PASS、不调模型、不自动下诊断。
# 重要：本脚本只产出"骨架 + 候选证据行"，不做任何心理/医学判断；真实分析由 AI 在提示词内完成。
# 复制到项目里再改；本包内只做模板（见 professional_profile.template.json）。

import sys
import os
import json
import argparse

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── 七镜头定义（子维度 + 每镜头启发式标记词）────────────────────────────────────
LENSES = {
    "逻辑学": {
        "desc": "推理一致性 / 决策链路 / 言行一致",
        "dims": [
            "推理是否自洽（有无自相矛盾、双标）",
            "决策链路是否可解释（手段→目的）",
            "口头承诺 vs 实际行为是否一致",
            "是否出现典型逻辑谬误（以偏概全/偷换概念/诉诸…）",
        ],
        "markers": ["自相矛盾", "前后不一", "口是心非", "说一套", "做一套", "偷换",
                    "以偏概全", "荒谬", "推不出", "逻辑", "双标", "明明", "却说"],
    },
    "心理学": {
        "desc": "动机结构 / 防御机制 / 依恋关系 / 创伤应激 / 情绪调节",
        "dims": [
            "需求层次与核心动机（安全/归属/权力/意义…）",
            "防御机制（否认/投射/合理化/升华…）",
            "依恋与关系模式（对谁信任/对谁防御）",
            "创伤与应激反应（什么情境触发、表现是什么）",
            "情绪调节方式（压抑/爆发/转移/解离）",
        ],
        "markers": ["害怕", "恐惧", "愤怒", "悲伤", "孤独", "创伤", "童年", "母亲",
                    "父亲", "信任", "依赖", "防御", "否认", "合理化", "投射", "崩溃",
                    "眼泪", "颤抖", "沉默", "压抑"],
    },
    "犯罪学": {
        "desc": "仅当人物有越轨/违法/伤害行为时启用：MO / 风险因子 / 情境触发",
        "dims": [
            "行为模式 MO（手段、节奏、对象选择）",
            "风险因子（什么让行为升级）",
            "情境触发（哪类情境诱发）",
            "收益-成本权衡（人物自己怎么算账）",
            "升级/再犯信号（有无逐步加码）",
        ],
        "markers": ["杀", "杀人", "抢劫", "偷", "骗", "绑架", "威胁", "伤害", "违法",
                    "犯罪", "越轨", "复仇", "报复", "黑吃黑", "灭口"],
    },
    "病理学": {
        "desc": "文中行为模式刻画（非真实诊断）：适应不良模式 / 功能损害",
        "dims": [
            "反复出现的适应不良模式（标注：文中表现）",
            "功能损害维度（关系/决策/情绪哪处受损）",
            "是否为情境性而非特质性（避免误判）",
        ],
        "markers": ["疯", "癫", "幻觉", "妄想", "强迫", "偏执", "成瘾", "自残",
                    "自杀", "失控", "解离", "歇斯底里"],
    },
    "刑侦学": {
        "desc": "证据重建：行动时间线 / MOM 三角 / 言行矛盾点",
        "dims": [
            "关键行动时间线（锚章号重建）",
            "手段-机会-动机(MOM)三角是否闭合",
            "言行矛盾点（喂 S7 自检找编造）",
        ],
        "markers": ["那天", "当时", "现场", "证据", "不在场", "动机", "手段", "机会",
                    "时间线", "笔录", "证词", "破绽", "矛盾"],
    },
    "测写师": {
        "desc": "综合侧写：核心驱动力 / 默认反应 / 识别特征 / 盲点",
        "dims": [
            "核心驱动力（什么情形下行动、为什么）",
            "典型情境下的默认反应（本能/下意识）",
            "识别特征（说话方式/决策偏好/关系模式）",
            "盲点与脆弱点（被什么拿捏、哪类信息会误判）",
        ],
        "markers": ["习惯", "本能", "下意识", "第一反应", "默认", "条件反射", "招牌",
                    "标志", "特征", "弱点", "软肋", "盲区", "条件反射"],
    },
    "经济学": {
        "desc": "稀缺与取舍 / 激励与约束 / 谈判与权力 / 信息与制度",
        "dims": [
            "稀缺资源与优先级（钱、时间、注意力、机会、关系）",
            "机会成本与边际取舍（放弃什么换取什么）",
            "激励结构与约束（奖励、惩罚、承诺、制度）",
            "谈判与议价权（替代选项、筹码、可信承诺）",
            "信息不对称与信号（谁知道什么、如何隐藏或证明）",
            "合作、博弈与委托代理（共同利益、背叛、代理成本）",
            "路径依赖与制度环境（阶层、市场、组织和时代约束）",
        ],
        "markers": ["钱", "银子", "价格", "成本", "收益", "利润", "债", "欠", "利息",
                    "买", "卖", "交易", "契约", "合同", "筹码", "谈判", "交换", "资源",
                    "机会", "代价", "便宜", "昂贵", "赏", "罚", "报酬", "分配", "权力",
                    "信息", "秘密", "情报", "垄断", "市场", "生意", "投资", "风险"],
    },
}

# 七镜头顺序（决定输出与 JSON 键顺序）
LENS_ORDER = ["逻辑学", "心理学", "犯罪学", "病理学", "刑侦学", "测写师", "经济学"]

# 七镜头对应的专业框架速查（写 S0 时参考，详见 09_专业知识参考库_S0.md 与 10_经济学知识参考库_S0.md）
FRAMEWORKS = {
    "逻辑学": [
        "逻辑四律（同一/矛盾/排中/充足理由）",
        "逻辑谬误表（诉诸/以偏概全/滑坡/偷换概念/循环/稻草人）",
        "手段-目的链闭合检验",
        "认知偏差（Kahneman：锚定/确认偏误/沉没成本/损失厌恶/框架效应）",
    ],
    "心理学": [
        "需求层次 Maslow",
        "防御机制层级 Vaillant（不成熟/神经症性/成熟）",
        "依恋理论 Bowlby/Ainsworth（安全/焦虑/回避/混乱）",
        "应激四反应 Porges（Fight/Flight/Freeze/Fawn）",
        "人格维度（大五 OCEAN / 黑暗三联征）",
        "情绪调节 Gross 过程模型",
        "自我决定论 SDT（自主/胜任/关系）",
    ],
    "犯罪学": [
        "日常活动理论 Cohen & Felson",
        "MO 与签名区分",
        "风险因子 Farrington",
        "中性化技术 Sykes & Matza",
        "理性选择视角 Cornish & Clarke",
        "情境犯罪预防五类",
    ],
    "病理学": [
        "功能损害三轴（关系/决策/情绪）",
        "情境性 vs 特质性区分",
        "文中行为刻画（非 DSM 真实诊断）",
        "必标「【推断·文中表现】」+ 非诊断声明",
    ],
    "刑侦学": [
        "MOM 三角（手段/机会/动机）",
        "时间线重建（相对/绝对锚）",
        "陈述分析（用词变化/时间模糊/细节缺失）",
        "印证规则（多源互证）",
    ],
    "测写师": [
        "行为一致性假设",
        "侧写四要素（核心驱动力/默认反应/识别特征/盲点）",
        "若涉案件：行动半径/节奏/升级信号",
    ],
    "经济学": [
        "稀缺性与机会成本：人物在有限资源下放弃了什么",
        "激励相容：奖励/惩罚/制度是否解释行为，是否存在激励错位",
        "边际分析：人物为何在某个临界点改变策略",
        "议价与权力：替代选项、筹码、承诺和退出威胁",
        "信息不对称：隐藏信息、信号、筛选、逆向选择与道德风险",
        "博弈与委托代理：合作、背叛、搭便车、代理成本和重复博弈",
        "制度与路径依赖：阶层、组织、市场和时代如何塑造可选行动",
    ],
}


def build_skeleton(character="<角色名>"):
    """返回七镜头透视档案骨架（dict）。每个镜头含子维度 + 证据状态占位。"""
    skeleton = {"角色": character, "镜头": []}
    for name in LENS_ORDER:
        spec = LENSES[name]
        skeleton["镜头"].append({
            "镜头": name,
            "定位": spec["desc"],
            "参考框架": FRAMEWORKS.get(name, []),
            "分析维度": [
                {"维度": d, "证据状态": "待填", "结论": "", "证据标注": ""}
                for d in spec["dims"]
            ],
        })
    # 综合侧写（测写师镜头汇总）
    skeleton["综合侧写"] = {
        "核心驱动力": "",
        "典型情境默认反应": "",
        "识别特征": "",
        "盲点与脆弱点": "",
        "非诊断声明": "以上为虚构角色「文中行为刻画」，非真实医学/心理学诊断。",
    }
    return skeleton


def _scan_file(path, markers, cap):
    """扫单个章节文件，返回命中的(行号, 文本)列表（上限 cap）。"""
    hits = []
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            for i, line in enumerate(fh, 1):
                if any(m in line for m in markers):
                    hits.append((i, line.strip()[:120]))
                    if len(hits) >= cap:
                        break
    except OSError:
        return hits
    return hits


def scan_markers(corpus_dir, character="<角色名>", cap=50):
    """扫全量语料，按七镜头返回候选证据行（章号+行号+片段）。"""
    result = {"角色": character, "候选证据": {}}
    if not corpus_dir or not os.path.isdir(corpus_dir):
        return result
    files = sorted(
        f for f in os.listdir(corpus_dir)
        if f.lower().endswith('.txt')
    )
    for name in LENS_ORDER:
        collected = []
        for fn in files:
            chap = fn
            for ln, text in _scan_file(os.path.join(corpus_dir, fn), LENSES[name]["markers"], cap):
                collected.append({"章": chap, "行": ln, "片段": text})
                if len(collected) >= cap:
                    break
            if len(collected) >= cap:
                break
        result["候选证据"][name] = collected
    return result


def render_markdown(skeleton):
    """把骨架渲染成可填写的 Markdown。"""
    lines = []
    lines.append(f"# {skeleton['角色']} · 专业透视档案（S0 · 七镜头）")
    lines.append("")
    lines.append("> 本档案由 `professional_profile.py` 生成骨架，结论须由 AI 逐条回原文核验后填写。")
    lines.append("> 每条结论必须带【直引·第N章】/【统计】/【推断】之一。虚构角色不得下真实诊断。")
    lines.append("")
    for lens in skeleton["镜头"]:
        lines.append(f"## {lens['镜头']}（{lens['定位']}）")
        lines.append("")
        for d in lens["分析维度"]:
            lines.append(f"- **{d['维度']}**")
            lines.append(f"  - 证据状态：{d['证据状态']}")
            lines.append(f"  - 结论：{d['结论']}")
            lines.append(f"  - 证据标注：{d['证据标注']}")
        lines.append("")
    cs = skeleton["综合侧写"]
    lines.append("## 综合侧写（测写师镜头汇总）")
    lines.append("")
    lines.append(f"- 核心驱动力：{cs['核心驱动力']}")
    lines.append(f"- 典型情境默认反应：{cs['典型情境默认反应']}")
    lines.append(f"- 识别特征：{cs['识别特征']}")
    lines.append(f"- 盲点与脆弱点：{cs['盲点与脆弱点']}")
    lines.append(f"- {cs['非诊断声明']}")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="S0 专业知识预分析 · 七镜头透视骨架生成器")
    ap.add_argument("--char", default="<角色名>", help="角色名")
    ap.add_argument("--corpus", default="", help="语料目录（含 pN.txt），启用候选证据扫描")
    ap.add_argument("--out", default="", help="输出目录（默认当前目录）")
    ap.add_argument("--cap", type=int, default=50, help="每镜头候选证据行上限")
    ap.add_argument("--selftest", action="store_true", help="离线自检（不依赖语料）")
    ap.add_argument("--knowledge", action="store_true", help="打印七镜头专业框架速查（写 S0 前参考）")
    args = ap.parse_args()

    if args.knowledge:
        for name in LENS_ORDER:
            print(f"## {name}")
            for fw in FRAMEWORKS[name]:
                print(f"  - {fw}")
        print("\n完整框架与核查清单见 09_专业知识参考库_S0.md、10_经济学知识参考库_S0.md")
        return 0

    if args.selftest:
        sk = build_skeleton("自检角色")
        assert len(sk["镜头"]) == 7, "镜头数应为 7"
        for lens in sk["镜头"]:
            assert lens["分析维度"], f"{lens['镜头']} 子维度为空"
        # 用内联临时语料验证扫描不崩溃
        import tempfile
        td = tempfile.mkdtemp()
        p = os.path.join(td, "p1.txt")
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write("他明明说过不杀人的，却说一套做一套。\n")
            fh.write("童年创伤让他恐惧依赖别人。\n")
        sc = scan_markers(td, "自检角色", cap=10)
        assert "逻辑学" in sc["候选证据"] and "心理学" in sc["候选证据"]
        md = render_markdown(sk)
        assert "核心驱动力" in md
        assert "经济学" in sc["候选证据"]
        print("[selftest] PASS · 七镜头骨架键齐全 / 扫描不崩溃 / Markdown 可渲染")
        return 0

    sk = build_skeleton(args.char)
    md = render_markdown(sk)
    out_dir = args.out or "."
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, f"{args.char}_专业透视档案.md")
    json_path = os.path.join(out_dir, f"{args.char}_专业透视档案.json")
    with open(md_path, 'w', encoding='utf-8') as fh:
        fh.write(md)
    with open(json_path, 'w', encoding='utf-8') as fh:
        json.dump(sk, fh, ensure_ascii=False, indent=2)

    print(f"[skeleton] 已生成骨架：{md_path}")
    print(f"[skeleton] 已生成 JSON：{json_path}")

    if args.corpus:
        sc = scan_markers(args.corpus, args.char, cap=args.cap)
        total = sum(len(v) for v in sc["候选证据"].values())
        print(f"[markers] 语料 {args.corpus} 候选证据行合计 {total}（各镜头见下方，需 AI 逐条回原文核验）")
        for name in LENS_ORDER:
            hits = sc["候选证据"][name]
            if hits:
                print(f"  · {name}：{len(hits)} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
