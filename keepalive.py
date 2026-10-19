"""本体が止まっていたら動かす(タスクスケジューラから呼ぶ。画面は開かない)。

コードが新しくなっていたら、古い本体を止めて動かし直す。
"""
import open_app


def main():
    open_app.stop_old_server()
    if not open_app.is_running():
        open_app.start_server()


if __name__ == "__main__":
    main()
