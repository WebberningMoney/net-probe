# 給 AI 助理（Claude 等）的協作守則

> 這份檔案是寫給「幫忙改這個專案的 AI 助理」看的。每次開始工作前請先讀完並照做。
> 一般使用者不需要看這份，請看 [README](README.md)。

## 1. 開始工作前：先設定 git（很重要，出過兩次問題）

在這個專案資料夾執行：

```bash
git config core.hooksPath scripts/git-hooks      # 啟用專案內建的自動檢查
git config commit.gpgsign false                  # 不要自動簽章
git config user.name  "$(git log -1 --format=%an origin/main)"   # 作者＝專案擁有者（Webber Huang）
git config user.email "$(git log -1 --format=%ae origin/main)"
git config netsonar.owneremail "$(git log -1 --format=%ae origin/main)"
```

為什麼：

- **作者必須是專案擁有者**，AI 助理只放在 commit 訊息最後的 `Co-Authored-By:`。
  雲端沙盒的預設 git 身分是 Claude，曾讓 15 個 commit 的作者都變成 Claude，事後得改寫歷史。
- **不要簽章**。沙盒會用它自己的金鑰簽 commit，那把金鑰沒有登記在擁有者的 GitHub 帳號，GitHub 會標成 **Unverified**。
- `scripts/git-hooks/` 的檢查會在 commit 和 push 前擋下上面兩種情況；推送後請再用
  `gh api repos/WebberningMoney/net-sonar/commits --jq '.[0] | .author.login, .commit.verification.reason'` 確認（應為擁有者、`unsigned`）。
- 需要改寫歷史或強制推送時，**一定要先問擁有者**。

## 2. 每次改了程式或畫面：一定要重新檢查文件與註解

擁有者的要求：**每一次**變更程式碼或畫面，都要自動 review 並更新相關說明。請照這個順序做：

1. **程式註解**：改到的檔案，開頭那段白話說明還正確嗎？改到的函式，註解有沒有過時？
2. **畫面文字**：新增的名詞有沒有加 ⓘ 說明（`dashboard/web/index.html` 的 `GL`）？提示文字是不是白話？
3. **README.md**：畫面導覽、怎麼看結果、名詞小辭典、隱私（會連到哪些網站）、常見問題、檔案列表。
4. **docs/ARCHITECTURE.md**：API 表格、檔案一覽、資料存放位置、運作方式。
5. **CHANGELOG.md**：在 `[Unreleased]` 記下這次改了什麼（用使用者看得懂的話）。
6. **跑測試**：`cd tests && python3 -m pytest -q`。其中 `tests/test_docs.py` 會自動抓「程式有、文件沒寫」的漏網之魚
   （新的 API 沒列進文件、新的對外連線沒寫進隱私說明、新分頁沒寫進 README…）。
   它抓不到「寫得不清楚」，所以第 1～5 步仍要自己重讀一遍。

commit 時如果改了程式卻沒有動到任何文件，`pre-commit` 會擋下來。

## 3. 寫作風格

- 所有文件、註解、畫面文字都用**繁體中文**，而且要**最白話**：讓沒有程式或網路背景的人也能輕鬆看懂。
- 專業名詞第一次出現要解釋，或改用白話說法（例：p95 →「慢的時候」、ISP →「網路公司」、hop →「站」）。
- 判斷與建議一律寫成「可能」「可以試試」，不要把推測寫成定論。
- 畫面要簡單乾淨：細節收進 ⓘ 或「進階資訊」。

## 4. 工作方式

- 需求有疑問時，**先跟擁有者釐清再動手寫程式**。
- 修改後要實際測試（自動化測試＋用瀏覽器操作畫面），並誠實說明哪些只能在真正的 Mac 上驗證
  （ping、Wi-Fi 資訊、系統通知、背景服務、「應用程式」圖示）。
- `net_probe.sh`（命令列腳本）除非擁有者要求，否則不要動。
- 不可復原的動作（清除紀錄、停止程式）在程式裡都要有確認步驟，並且只接受儀表板自己的網頁送出的請求。
