#!/usr/bin/env python3
"""Regenerate index.html from cases.json.

Usage (from this directory):
  python3 build.py

cases.json is a JSON array. Each case object uses these fields:
  id, title, platform, meta, tools, description, takeaway,
  url, link_label, screenshot, shot_source, alt

platform is "Threads", "Instagram", or "X".
screenshot is a filename under shots/, or null when no image could be captured.
Array order is the book order (newest first).

Also writes /workspace/ai-game-cases.html when that directory exists.
Stdlib only.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LABEL = {"Threads": "스레드", "Instagram": "인스타그램", "X": "X"}
UPDATED = "2026-10-09"


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def render(cases: list[dict]) -> str:
    counts: dict[str, int] = {k: 0 for k in LABEL}
    for case in cases:
        counts[case["platform"]] = counts.get(case["platform"], 0) + 1
    count_bits = " · ".join(
        "%s %d" % (LABEL.get(key, key), counts.get(key, 0)) for key in ("Threads", "Instagram", "X")
    )
    cards = []
    for i, case in enumerate(cases, start=1):
        n = "%02d" % i
        platform = case["platform"]
        if case.get("screenshot"):
            shot = (
                '<a class="shot" href="%s" target="_blank" rel="noopener noreferrer">'
                '<img src="shots/%s" alt="%s" loading="lazy" width="430" height="720">'
                "</a>"
            ) % (esc(case["url"]), esc(case["screenshot"]), esc(case.get("alt") or case["title"]))
        else:
            shot = (
                '<a class="shot placeholder" href="%s" target="_blank" rel="noopener noreferrer">'
                "<span>이 글의 화면을 캡처하지 못했습니다.</span>"
                "<span>원문 열기</span>"
                "</a>"
            ) % esc(case["url"])
        cards.append(
            """
    <article class="case" data-platform="%s" id="%s">
      <div class="body">
        <p class="num">%s</p>
        <h2>%s</h2>
        <p class="sub">%s</p>
        <p class="tool">AI 도구 · %s</p>
        <p class="desc">%s</p>
        <p class="take"><span>참고할 점</span> %s</p>
        <p class="more"><a href="%s" target="_blank" rel="noopener noreferrer">%s</a></p>
      </div>
      %s
    </article>"""
            % (
                esc(platform),
                esc(case.get("id") or n),
                n,
                esc(case["title"]),
                esc(case["meta"]),
                esc(case["tools"]),
                esc(case["description"]),
                esc(case["takeaway"]),
                esc(case["url"]),
                esc(case.get("link_label") or "원문 보기"),
                shot,
            )
        )

    return """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI 게임 제작 사례집</title>
<style>
  :root {
    --paper: #f3ecdf;
    --card: #fffaf3;
    --ink: #2b241c;
    --muted: #6f6456;
    --line: #e4d5c2;
    --accent: #8c3e22;
    --chip: #f6e6d4;
    --chip-on: #2b241c;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    color: var(--ink);
    background:
      radial-gradient(900px 420px at 50%% -80px, #fff8ee, transparent 70%%),
      var(--paper);
    font-family: "Nanum Myeongjo", "Apple SD Gothic Neo", "Noto Serif CJK KR", "Noto Sans KR", "Malgun Gothic", serif;
    line-height: 1.7;
  }
  main { max-width: 980px; margin: 0 auto; padding: 48px 20px 96px; }
  header h1 {
    margin: 0;
    font-size: clamp(32px, 5vw, 46px);
    font-weight: 700;
    letter-spacing: -0.03em;
    line-height: 1.25;
  }
  .intro { margin: 12px 0 0; max-width: 40em; font-size: 17px; }
  .meta { margin: 16px 0 0; color: var(--accent); font-size: 14px; }
  .tools {
    display: flex; flex-wrap: wrap; gap: 8px;
    margin: 22px 0 8px; align-items: center;
  }
  button, .search {
    font: inherit; color: var(--ink);
    background: var(--card); border: 1px solid var(--line);
    border-radius: 999px; padding: 6px 12px; cursor: pointer;
  }
  button[aria-pressed="true"] { background: var(--chip-on); color: #fffaf3; border-color: var(--chip-on); }
  .search { border-radius: 12px; min-width: min(100%%, 220px); padding: 8px 12px; }
  .case {
    display: grid; grid-template-columns: 1fr;
    gap: 18px; background: var(--card);
    border: 1px solid var(--line); border-radius: 22px;
    padding: 22px; margin: 16px 0;
    box-shadow: 0 10px 30px rgba(80, 50, 20, 0.04);
  }
  .num { margin: 0; color: var(--accent); font-size: 13px; letter-spacing: 0.12em; }
  h2 { margin: 2px 0 6px; font-size: 22px; line-height: 1.35; letter-spacing: -0.02em; }
  .sub, .tool { margin: 0 0 8px; color: var(--muted); font-size: 14px; }
  .tool { color: var(--accent); }
  .desc { margin: 0 0 10px; }
  .take { margin: 0 0 12px; background: var(--chip); border-radius: 12px; padding: 10px 12px; }
  .take span { display: block; font-size: 12px; letter-spacing: 0.08em; color: var(--accent); }
  a { color: var(--accent); }
  .more { margin: 0; }
  .shot {
    display: block; border-radius: 18px; overflow: hidden;
    border: 1px solid var(--line); background: #221c17;
    align-self: start;
  }
  .shot img { display: block; width: 100%%; height: auto; max-height: 640px; object-fit: cover; object-position: top; }
  .placeholder {
    min-height: 220px; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 8px;
    text-align: center; text-decoration: none; color: #f6efe4;
    padding: 24px; background:
      repeating-linear-gradient(-45deg, #3a3128, #3a3128 8px, #2b241c 8px, #2b241c 16px);
  }
  footer { margin-top: 28px; color: var(--muted); font-size: 14px; }
  @media (min-width: 860px) {
    .case { grid-template-columns: 1fr 250px; align-items: start; }
    .shot { position: sticky; top: 16px; }
  }
</style>
</head>
<body>
<main>
  <header>
    <h1>AI 게임 제작 사례집</h1>
    <p class="intro">인스타그램, 스레드, X의 공개 글에서 확인한 AI 게임 제작 사례입니다. 로그인해야 보이는 글은 넣지 않고, 최근 글부터 정렬했습니다.</p>
    <p class="meta">마지막 갱신 %s · %d건 · %s</p>
  </header>
  <div class="tools">
    <button type="button" data-filter="all" aria-pressed="true">전체</button>
    <button type="button" data-filter="Threads" aria-pressed="false">스레드</button>
    <button type="button" data-filter="Instagram" aria-pressed="false">인스타그램</button>
    <button type="button" data-filter="X" aria-pressed="false">X</button>
    <input class="search" type="search" placeholder="제목, 도구, 계정 검색" aria-label="사례 검색">
  </div>
  <div id="cases">
%s
  </div>
  <footer>
    <p>평일 아침마다 새 사례만 이 페이지에 더합니다. 다른 사람의 작업을 소개한 글은 소개한 계정과 원작자를 함께 적었습니다.</p>
    <p>기간, 비용, 조회수, 처음이라는 표현은 각 글에서 게시자가 밝힌 말입니다.</p>
  </footer>
</main>
<script>
(function () {
  var buttons = document.querySelectorAll("[data-filter]");
  var cards = Array.prototype.slice.call(document.querySelectorAll(".case"));
  var search = document.querySelector(".search");
  var platform = "all";
  function apply() {
    var q = (search && search.value || "").trim().toLowerCase();
    cards.forEach(function (card) {
      var okPlatform = platform === "all" || card.getAttribute("data-platform") === platform;
      var okText = !q || card.textContent.toLowerCase().indexOf(q) !== -1;
      card.hidden = !(okPlatform && okText);
    });
  }
  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      platform = btn.getAttribute("data-filter");
      buttons.forEach(function (b) { b.setAttribute("aria-pressed", b === btn ? "true" : "false"); });
      apply();
    });
  });
  if (search) search.addEventListener("input", apply);
})();
</script>
</body>
</html>
""" % (UPDATED, len(cases), count_bits, "\n".join(cards))


def main() -> None:
    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise SystemExit("cases.json must be an array")
    page = render(cases)
    (ROOT / "index.html").write_text(page, encoding="utf-8")
    extra = Path("/workspace/ai-game-cases.html")
    if extra.parent.is_dir():
        extra.write_text(page, encoding="utf-8")
    print("wrote %s (%d cases)" % (ROOT / "index.html", len(cases)))


if __name__ == "__main__":
    main()
