"""路演前预检：只读检查本地后端是否可用及其运行模式。"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.error import URLError
from urllib.request import urlopen


def fetch(url: str) -> dict:
    with urlopen(url, timeout=3) as response:  # noqa: S310 - URL is CLI/local operator input
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="检查学有所径演示服务")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    try:
        health = fetch(f"{base}/healthz")
        ready = fetch(f"{base}/readyz")
    except (OSError, URLError, ValueError) as exc:
        print(f"FAIL 后端不可用: {exc}")
        return 1

    if health.get("status") != "ok":
        print(f"FAIL healthz: {health}")
        return 1
    curriculum = ready.get("curriculum", {})
    rag = ready.get("rag", {})
    llm = ready.get("llm", {})
    print(f"OK 课程 {curriculum.get('course_id')} · {curriculum.get('concept_count')} 个知识点 · {curriculum.get('question_count')} 道题")
    print(f"OK RAG {rag.get('segment_count')} 条 · 索引 {rag.get('index_version')}")
    print(f"OK 模型 {llm.get('provider')} / {llm.get('model_id')} · 配置={'是' if llm.get('configured') else '否'} · 规则回退={'可用' if llm.get('rule_fallback_available') else '不可用'}")
    if ready.get("status") == "degraded":
        print("WARN 当前为降级模式：可继续演示，模型生成将使用规则回退；前端顶栏会显示该状态。")
    else:
        print("READY 可开始演示。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
