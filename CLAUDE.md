# workbench

大学の作業と自分の開発を一元管理する Web アプリ。spec-excel(`/spec-excel`)の工程で進める。

## 分担
- 要件定義・構想設計・基本設計・テストの判断はユーザー。Claude は質問・おすすめ・清書・点検まで
- 実装は Claude が書く。基本設計書と違う作りにしたくなったら、先にユーザーに聞き、基本設計書の版を上げる
- ユーザーが決めていないことを設計書に書かない

## 置き場所
- `docs/` — 設計書(`requirements-v0.1.xlsx` など)、`spec-excel-status.md`、`ai-log/`
- `docs/src/` — make_xlsx.py で作る資料の中身 JSON
- `data/` — 作業記録・授業名などの個人データと DB。**コミットしない**(公開リポジトリのため)

## GitHub
- K24rs057/workbench(PUBLIC)。区切りごとにコミットして push する
- 授業の配布資料、ほかの人の要件定義書は入れない
