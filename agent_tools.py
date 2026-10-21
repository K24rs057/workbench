"""モッチの道具箱(MCP サーバー。基本設計 A40)。claude -p から標準入出力で呼ばれる。

道具の一覧は agent_toolbox.py から読み、呼び出しは段取りさんの本体(127.0.0.1)の /api/agent/tool に渡すだけ。
規程の判定・確認・元に戻す記録は、全部本体の側で行う。ここでは何も決めない。
本体の場所と、その頼みの番号・合言葉は、環境変数で受け取る(DANDORI_URL・DANDORI_RUN・DANDORI_TOKEN)。
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

URL = os.environ.get("DANDORI_URL", "http://127.0.0.1:8780")
RUN = os.environ.get("DANDORI_RUN", "")
TOKEN = os.environ.get("DANDORI_TOKEN", "")


def tool_list():
    import agent_toolbox
    return agent_toolbox.tool_list()


def call_tool(name, args):
    data = json.dumps({"run": RUN, "token": TOKEN, "tool": name, "args": args or {}}).encode("utf-8")
    req = urllib.request.Request(URL + "/api/agent/tool", data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return json.load(e)
        except ValueError:
            return {"error": f"段取りさんが答えませんでした({e.code})"}
    except OSError:
        return {"error": "段取りさんにつながりませんでした"}


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        ver = (msg.get("params") or {}).get("protocolVersion") or "2024-11-05"
        return {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": ver, "capabilities": {"tools": {}},
                                                        "serverInfo": {"name": "dandori", "version": "1.0"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tool_list()}}
    if method == "tools/call":
        p = msg.get("params") or {}
        res = call_tool(p.get("name"), p.get("arguments"))
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}],
                                                        "isError": bool(isinstance(res, dict) and res.get("error"))}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if mid is None:  # 知らせ(notifications/…)には答えない
        return None
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "その呼び出しはありません"}}


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            out = handle(json.loads(line))
        except Exception as e:  # 1つの失敗で道具箱ごと止めない
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)[:200]}}
        if out is not None:
            sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
