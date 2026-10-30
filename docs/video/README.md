# しくみ動画

段取りさんの裏側(1分ごとの見回り、10分ごとに集めるもの、1行入力と Claude、通知と作業記録、データの守り方)を、約3分の縦動画(1080×1920、読み上げ・字幕つき)で説明するための元ファイル。スキル `video-explainer` の道具で作っています。

| ファイル | 中身 |
|---|---|
| `script.json` | 場面ごとの台本。`sub` は字幕、`say` は読み上げ用(読み間違えないよう、かなで書く。なければ `sub` を読む) |
| `make_voice.py` | 台本を edge-tts の声(Nanami)で1行ずつ WAV にする。ネットが必要で、台本は Microsoft に送られる |
| `build.py` | 声の長さから時刻を決め、動く絵のページを1コマずつ撮って MP4 にする |
| `video.html` | 動く絵。`window.render(秒)` でその瞬間の絵になる |
| `stills.py` | 確認用。各場面の1コマを撮る |
| `out/` | 声・時刻・MP4。GitHub には上げない |

画面に出す例・数字はコードから写したもので、本物の授業名・メール・タスク・`data/` や `.env` の中身は入れていません。

## 作り方

```bash
pip install edge-tts playwright
python -m playwright install chromium
python make_voice.py
python build.py --timing
python stills.py
python build.py --name dandori-shikumi
```

できあがりは `out/dandori-shikumi.mp4`。
