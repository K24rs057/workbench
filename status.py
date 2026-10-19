"""本体の様子(基本設計 Q19・S6-6)。裏の仕事ごとの最後に動いた時刻と、遅れているか。"""
from datetime import datetime, timedelta

# 遅れの目安(Claude の案。基本設計 エラー「裏の仕事が止まっている」)。①で動く仕事だけ
LIMITS = {"作業記録": timedelta(minutes=5), "通知": timedelta(minutes=5), "時間割の読み込み": timedelta(minutes=30),
          "Outlook": timedelta(minutes=30), "Gmail": timedelta(minutes=30),
          "Google カレンダー": timedelta(minutes=30), "git の取り込み": timedelta(minutes=30)}
OPTIONAL = {"Gmail", "Google カレンダー", "git の取り込み"}  # 許可・登録をしてから動く仕事。一度も動いていなければ出さない


def jobs(con, now=None):
    now = now or datetime.now()
    rows = {r["job"]: r for r in con.execute("SELECT * FROM job_status")}
    out = []
    for job, limit in LIMITS.items():
        r = rows.get(job)
        if job in OPTIONAL and not r:
            continue
        last = r["last_run_at"] if r else None
        late = (last is None) or (now - datetime.fromisoformat(last) > limit)
        out.append({"job": job, "last_run_at": last, "late": late, "error": r["last_error"] if r else None})
    return out


def late_jobs(con, now=None):
    """一度でも動いたことがあって、いま遅れている仕事(起動した直後は数えない)。"""
    return [j for j in jobs(con, now) if j["late"] and j["last_run_at"]]
