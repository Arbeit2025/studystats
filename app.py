# ============================================================
# studystats（学習ログ分析レポート）
# 目次
#   Unit 1: 設定・共通
#   Unit 2: CSV パース
#   Unit 3: 集計（合計・科目別・streak・理解度・直近7日比較）
#   Unit 4: サンプル CSV 生成
#   Unit 5: 画面テンプレート
#   Unit 6: ルーティング
# ============================================================
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from flask import Flask, Response, render_template_string, request

# ============================================================
# Unit 1: 設定・共通
# ============================================================
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # アップロード上限 1MB

Record = Dict[str, object]  # {"date": date, "subject": str, "minutes": float, "understanding": int}

HEADER_CANDIDATES = [
    ["日付", "科目", "学習分", "理解度"],
    ["date", "subject", "minutes", "understanding"],
]


def fmt_minutes(minutes: float) -> str:
    """分を「X時間Y分」表記にする（60分未満は「Y分」）。"""
    total = int(round(minutes))
    h, m = divmod(total, 60)
    if h > 0:
        return f"{h}時間{m}分" if m else f"{h}時間"
    return f"{m}分"


# ============================================================
# Unit 2: CSV パース
# 列：日付, 科目, 学習分, 理解度(1-5)
# 不正な行はスキップして件数を数える。ファイルは保存しない。
# ============================================================
def _parse_date(text: str) -> Optional[date]:
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _is_header(row: List[str]) -> bool:
    cells = [c.strip() for c in row[:4]]
    return cells in HEADER_CANDIDATES


def decode_csv_bytes(raw: bytes) -> str:
    """UTF-8（BOM付き含む）→ Shift_JIS の順に試す。"""
    for enc in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_csv(text: str) -> Tuple[List[Record], int]:
    """CSV テキストをパースし、(レコード一覧, スキップ件数) を返す。"""
    records: List[Record] = []
    skipped = 0
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if not row or all(not c.strip() for c in row):
            continue  # 空行はスキップ件数に数えない
        if _is_header(row):
            continue
        if len(row) < 4:
            skipped += 1
            continue
        d = _parse_date(row[0])
        subject = row[1].strip()
        try:
            minutes = float(row[2].strip())
        except ValueError:
            minutes = -1
        try:
            understanding = int(row[3].strip())
        except ValueError:
            understanding = -1
        if (
            d is None
            or not subject
            or minutes <= 0
            or not (1 <= understanding <= 5)
        ):
            skipped += 1
            continue
        records.append(
            {
                "date": d,
                "subject": subject,
                "minutes": minutes,
                "understanding": understanding,
            }
        )
    return records, skipped


# ============================================================
# Unit 3: 集計
# ============================================================
def current_streak(days_sorted: List[date]) -> int:
    """最新の記録日から遡った連続学習日数。"""
    if not days_sorted:
        return 0
    streak = 1
    cursor = days_sorted[-1]
    for d in reversed(days_sorted[:-1]):
        if (cursor - d).days == 1:
            streak += 1
            cursor = d
        else:
            break
    return streak


def analyze(records: List[Record]) -> Dict[str, object]:
    """レコード一覧からレポート用サマリを組み立てる。"""
    if not records:
        return {"has_data": False}

    total_minutes = sum(float(r["minutes"]) for r in records)
    days = sorted({r["date"] for r in records})
    streak = current_streak(days)

    subject_map: Dict[str, float] = defaultdict(float)
    for r in records:
        subject_map[str(r["subject"])] += float(r["minutes"])
    subject_totals = sorted(subject_map.items(), key=lambda kv: kv[1], reverse=True)
    max_subject_minutes = subject_totals[0][1] if subject_totals else 0
    subject_rows = [
        {
            "subject": name,
            "minutes": mins,
            "label": fmt_minutes(mins),
            "pct": (mins / max_subject_minutes * 100) if max_subject_minutes else 0,
            "share": (mins / total_minutes * 100) if total_minutes else 0,
        }
        for name, mins in subject_totals
    ]

    avg_understanding = sum(int(r["understanding"]) for r in records) / len(records)

    latest = days[-1]
    recent_start = latest - timedelta(days=6)
    prev_start = latest - timedelta(days=13)
    prev_end = latest - timedelta(days=7)
    recent7 = sum(
        float(r["minutes"]) for r in records if recent_start <= r["date"] <= latest
    )
    prev7 = sum(
        float(r["minutes"]) for r in records if prev_start <= r["date"] <= prev_end
    )
    diff7 = recent7 - prev7
    if prev7 > 0:
        diff7_pct: Optional[float] = diff7 / prev7 * 100
    else:
        diff7_pct = None

    top_subject = subject_totals[0][0] if subject_totals else ""
    top_minutes = subject_totals[0][1] if subject_totals else 0

    if diff7 > 0:
        trend_text = "増えています"
    elif diff7 < 0:
        trend_text = "減っています"
    else:
        trend_text = "同じペースです"
    summary = (
        f"期間中は合計 {fmt_minutes(total_minutes)} 学習し、"
        f"最も学習した科目は「{top_subject}」（{fmt_minutes(top_minutes)}）でした。"
        f"学習ペースは直近7日が {fmt_minutes(recent7)} で、その前7日と比べて{trend_text}。"
        f"平均の理解度は {avg_understanding:.1f} / 5 です。"
    )

    return {
        "has_data": True,
        "total_minutes": total_minutes,
        "total_label": fmt_minutes(total_minutes),
        "study_days": len(days),
        "streak": streak,
        "subject_rows": subject_rows,
        "avg_understanding": avg_understanding,
        "recent7": recent7,
        "recent7_label": fmt_minutes(recent7),
        "prev7": prev7,
        "prev7_label": fmt_minutes(prev7),
        "diff7": diff7,
        "diff7_label": fmt_minutes(abs(diff7)),
        "diff7_pct": diff7_pct,
        "top_subject": top_subject,
        "record_count": len(records),
        "first_date": days[0].isoformat(),
        "last_date": days[-1].isoformat(),
        "summary": summary,
    }


# ============================================================
# Unit 4: サンプル CSV 生成（ダウンロード用）
# ============================================================
def build_sample_csv(today: Optional[date] = None) -> str:
    today = today or date.today()
    subjects = ["数学", "英語", "情報", "国語"]
    minutes_cycle = [60, 45, 90, 30, 75, 50, 100, 40, 65, 80, 55, 70, 35, 85]
    understanding_cycle = [4, 3, 5, 4, 3, 4, 5, 3, 4, 4, 5, 3, 4, 5]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["日付", "科目", "学習分", "理解度"])
    # 直近14日ぶん（今日を含む連続記録＋科目ローテーション）
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        idx = 13 - i
        writer.writerow(
            [
                d.isoformat(),
                subjects[idx % len(subjects)],
                minutes_cycle[idx % len(minutes_cycle)],
                understanding_cycle[idx % len(understanding_cycle)],
            ]
        )
        if idx % 3 == 0:  # 一部は2科目目も記録
            writer.writerow(
                [
                    d.isoformat(),
                    subjects[(idx + 1) % len(subjects)],
                    25,
                    4,
                ]
            )
    return out.getvalue()


# ============================================================
# Unit 5: 画面テンプレート
# ============================================================
PAGE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>studystats｜学習ログ分析レポート</title>
<style>
  body { font-family: sans-serif; margin: 0; background: #f6f8fb; color: #222; }
  .wrap { max-width: 760px; margin: 0 auto; padding: 24px 16px 48px; }
  h1 { font-size: 1.5rem; }
  .card { background: #fff; border-radius: 12px; padding: 20px; margin: 16px 0;
          box-shadow: 0 1px 4px rgba(0,0,0,.08); }
  textarea { width: 100%; min-height: 140px; box-sizing: border-box; }
  .stats { display: flex; flex-wrap: wrap; gap: 12px; }
  .stat { flex: 1 1 150px; background: #eef4ff; border-radius: 10px; padding: 12px; }
  .stat .num { font-size: 1.4rem; font-weight: bold; }
  .bar-row { display: flex; align-items: center; gap: 8px; margin: 6px 0; }
  .bar-name { width: 6em; text-align: right; }
  .bar-track { flex: 1; background: #e5e9f0; border-radius: 6px; height: 18px; }
  .bar-fill { background: #4a7ddb; height: 18px; border-radius: 6px; }
  .warn { color: #a33; }
  button { background: #4a7ddb; color: #fff; border: 0; border-radius: 8px;
           padding: 10px 20px; font-size: 1rem; cursor: pointer; }
</style>
</head>
<body>
<div class="wrap">
  <h1>📊 studystats｜学習ログ分析レポート</h1>
  <p>学習ログの CSV（日付, 科目, 学習分, 理解度（1〜5））をアップロードするか、
     下の欄に貼り付けると、学習の傾向をレポートにまとめます。
     ファイルはサーバーに保存されません（上限 1MB）。</p>

  <div class="card">
    <form method="post" action="/analyze" enctype="multipart/form-data">
      <p><label>CSVファイル：<input type="file" name="file" accept=".csv,text/csv"></label></p>
      <p><label>または CSV を貼り付け：</label><br>
      <textarea name="csv_text" placeholder="日付,科目,学習分,理解度&#10;2026-10-31,数学,60,4"></textarea></p>
      <p><button type="submit">分析する</button></p>
    </form>
    <p>形式が分からないときは <a href="/sample.csv">サンプルCSV</a> をダウンロードして試せます。</p>
  </div>

  {% if error %}
  <div class="card warn">{{ error }}</div>
  {% endif %}

  {% if result and result.has_data %}
  <div class="card">
    <h2>レポート（{{ result.first_date }} 〜 {{ result.last_date }}、{{ result.record_count }}件）</h2>
    <p>{{ result.summary }}</p>
    <div class="stats">
      <div class="stat"><div>総学習時間</div><div class="num">{{ result.total_label }}</div></div>
      <div class="stat"><div>学習した日数</div><div class="num">{{ result.study_days }}日</div></div>
      <div class="stat"><div>連続日数（最新記録日から）</div><div class="num">{{ result.streak }}日</div></div>
      <div class="stat"><div>理解度の平均</div><div class="num">{{ "%.1f"|format(result.avg_understanding) }} / 5</div></div>
    </div>
    {% if skipped %}
    <p class="warn">不正な行 {{ skipped }} 件をスキップしました。</p>
    {% endif %}
  </div>

  <div class="card">
    <h2>科目別の合計時間</h2>
    {% for row in result.subject_rows %}
    <div class="bar-row">
      <div class="bar-name">{{ row.subject }}</div>
      <div class="bar-track"><div class="bar-fill" style="width: {{ "%.1f"|format(row.pct) }}%"></div></div>
      <div>{{ row.label }}（{{ "%.0f"|format(row.share) }}%）</div>
    </div>
    {% endfor %}
  </div>

  <div class="card">
    <h2>直近7日とその前7日の比較</h2>
    <p>直近7日：{{ result.recent7_label }}／その前7日：{{ result.prev7_label }}／
       差：{% if result.diff7 > 0 %}+{% elif result.diff7 < 0 %}-{% endif %}{{ result.diff7_label }}
       {% if result.diff7_pct is not none %}（{{ "%+.0f"|format(result.diff7_pct) }}%）{% endif %}</p>
  </div>
  {% elif result %}
  <div class="card">
    <p>有効な記録がありませんでした。CSVの形式（日付, 科目, 学習分, 理解度（1〜5））を確認してください。</p>
    {% if skipped %}
    <p class="warn">不正な行 {{ skipped }} 件をスキップしました。</p>
    {% endif %}
  </div>
  {% endif %}
</div>
</body>
</html>
"""


# ============================================================
# Unit 6: ルーティング
# ============================================================
@app.route("/", methods=["GET"])
def index():
    return render_template_string(PAGE, result=None, skipped=0, error=None)


@app.route("/analyze", methods=["POST"])
def analyze_view():
    text = ""
    uploaded = request.files.get("file")
    pasted = (request.form.get("csv_text") or "").strip()
    if uploaded is not None and uploaded.filename:
        text = decode_csv_bytes(uploaded.read())
    elif pasted:
        text = pasted
    if not text.strip():
        return render_template_string(
            PAGE,
            result=None,
            skipped=0,
            error="CSVファイルを選ぶか、CSVを貼り付けてください。",
        )
    records, skipped = parse_csv(text)
    result = analyze(records)
    return render_template_string(PAGE, result=result, skipped=skipped, error=None)


@app.route("/sample.csv", methods=["GET"])
def sample_csv():
    body = build_sample_csv()
    return Response(
        body,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=sample.csv"},
    )


@app.route("/healthz", methods=["GET"])
def healthz():
    return {"status": "ok"}


@app.errorhandler(413)
def too_large(_e):
    return (
        render_template_string(
            PAGE,
            result=None,
            skipped=0,
            error="ファイルサイズが上限（1MB）を超えています。",
        ),
        413,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
