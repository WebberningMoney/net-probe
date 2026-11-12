"""文件自動檢查：程式或畫面改了，說明文件有沒有跟上？

每次跑測試都會檢查這些「容易忘記更新」的地方。哪一項沒過，訊息會直接說缺了什麼、該補在哪裡。
（這只能抓「漏寫」，抓不到「寫得不清楚」；文字品質仍要人或 AI 助理在每次修改後重讀一遍，見 CLAUDE.md。）
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASH = ROOT / "dashboard"
README = (ROOT / "README.md").read_text(encoding="utf-8")
ARCH = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
HTML = (DASH / "web" / "index.html").read_text(encoding="utf-8")
APP = (DASH / "app.py").read_text(encoding="utf-8")


def test_every_api_route_is_listed_in_architecture():
    routes = set(re.findall(r'@app\.(?:get|post|put|patch|delete)\("(/api/[^"{]+)', APP))
    missing = sorted(r.rstrip("/") for r in routes if r.rstrip("/") not in ARCH)
    assert not missing, f"docs/ARCHITECTURE.md 的「網頁拿資料的網址」表格少了：{missing}"


def test_every_python_file_has_a_header_and_is_listed_in_architecture():
    for f in sorted(DASH.glob("*.py")):
        doc = ast.get_docstring(ast.parse(f.read_text(encoding="utf-8")))
        assert doc and f.name in doc.splitlines()[0], f"{f.name} 開頭要有一段白話說明，第一行以「{f.name} ——」開始"
        assert f.name in ARCH, f"docs/ARCHITECTURE.md 的檔案一覽少了 {f.name}"


def test_readme_covers_every_tab_and_user_facing_file():
    tabs = re.findall(r'<button data-t="\w+"[^>]*>([^<]+)</button>', HTML)
    assert len(tabs) >= 5
    for t in tabs:
        assert f"**{t}**" in README, f"README「畫面導覽」少了分頁「{t}」"
    for name in ("安裝.command", "解除安裝.command", "run_dashboard.sh", "net_probe.sh", "CHANGELOG.md", "CLAUDE.md"):
        assert (ROOT / name).exists() and name in README, f"README 沒有提到 {name}（或檔案不存在）"


def test_readme_links_point_to_existing_files():
    for target in re.findall(r"\]\((?!https?://|#)([^)#]+)", README):
        assert (ROOT / target).exists(), f"README 連到不存在的檔案：{target}"
    heads = {re.sub(r"[^\w一-鿿 -]", "", h).strip().lower().replace(" ", "-") for h in re.findall(r"^#+\s+(.+)$", README, re.M)}
    for anchor in re.findall(r"\]\(#([^)]+)\)", README):
        assert anchor in heads, f"README 內部連結 #{anchor} 找不到對應的標題"


def test_every_outside_host_is_disclosed_in_readme_privacy_section():
    privacy = README[README.index("隱私：它會連到哪些地方"):]
    hosts = set()
    for f in DASH.glob("*.py"):
        hosts |= set(re.findall(r'https://([a-z0-9.-]+\.[a-z]{2,})', f.read_text(encoding="utf-8")))
    hosts -= {"evil.example"}
    assert hosts, "應該至少找得到 ipinfo.io"
    for h in sorted(hosts):
        assert h in privacy, f"程式會連到 {h}，但 README 的「隱私」一節沒有列出"


def test_glossary_covers_every_info_icon_and_readme_has_the_terms():
    gl = HTML[HTML.index("const GL={"):HTML.index("};", HTML.index("const GL={"))]
    keys = set(re.findall(r'^(\w+):"', gl, re.M))
    used = set(re.findall(r'data-g="(\w+)"', HTML)) | set(re.findall(r'ti\("(\w+)"\)', HTML))
    used |= set(re.findall(r':"(\w+)"', HTML[HTML.index("const secG={"):HTML.index("}", HTML.index("const secG={"))]))
    assert used <= keys, f"畫面上的 ⓘ 用到了沒有說明的名詞：{sorted(used - keys)}"
    for term in ("延遲", "抖動", "丟包", "慢的時候", "MOS", "DNS", "VPN", "訊噪比", "MTU"):
        assert term in README[README.index("名詞小辭典"):], f"README 名詞小辭典少了「{term}」"


def test_clear_and_export_buttons_are_documented():
    kinds = set(re.findall(r'data-clear="(\w+)"', HTML))
    assert kinds == {"samples", "alerts", "reports", "curl", "trace", "all"}, f"清除按鈕的種類變了：{sorted(kinds)}，請同步更新 README 與這個測試"
    assert "清除紀錄" in README and "下載 CSV" in README, "README 要說明「清除紀錄」與「下載 CSV」"


def test_changelog_has_unreleased_section_and_no_stale_names():
    assert "## [Unreleased]" in CHANGELOG
    for text, where in ((README, "README"), (ARCH, "ARCHITECTURE")):
        for stale in ("rdap.org", "Chart.js", "dashboard.py", "引擎健康度", "程式健康度"):
            assert stale not in text, f"{where} 還留著過時的說法：{stale}"


def test_info_tab_explains_how_it_works_and_holds_status_and_about():
    info = HTML[HTML.index('<section id="info">'):HTML.index('<section id="trace">')]
    for must in ("NetSonar 怎麼檢測你的網路", "運作狀態", "關於這個程式", 'id="ehealth"', 'id="about"', 'id="quit"', 'data-clear="all"'):
        assert must in info, f"「說明」分頁少了：{must}"
    assert "100 −（丟包% × 2 ＋ 平均 ÷ 2 ＋ 抖動 × 1.5）" in info, "說明頁的分數公式要和 stats.ping_score 一致，改公式時兩邊一起改"
    assert "程式健康度" not in HTML
