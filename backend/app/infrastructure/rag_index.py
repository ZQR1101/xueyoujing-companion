"""T13-B 课程资源索引与混合检索（关键词 + 向量）。

- 索引从已登记课程包构建：course.json 注册的 resources/*.md 按 `##` 分节，
  每节为一个可检索条目，content_type 依节标题归类（explanation/example/hint/transfer）；
- index_version = 课程包内容的 sha256（固定索引下排序可复现的依据）；
- 关键词检索：查询字符 bigram 覆盖率（确定性）；
- 向量检索：本地 hashing trick（字符 bigram 哈希到固定维 + L2 归一，余弦相似度），
  不依赖外部服务；接口为 Protocol，便于日后接入真实 embedding 服务；
- 任何检索异常由服务层捕获并按规划书回退（向量失败→关键词；均失败→课程包固定资源）。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.infrastructure.curriculum import get_course_data

VECTOR_DIM = 512
_HEADING_TYPES: list[tuple[tuple[str, ...], str]] = [
    (("例", "试一试", "练习", "求值"), "example"),
    (("陷阱", "易错", "注意", "符号"), "hint"),
    (("迁移", "应用", "变式", "综合"), "transfer"),
    (("概念", "定义", "性质", "基本", "形式"), "explanation"),
]


@dataclass(frozen=True)
class RagSegment:
    source_id: str
    resource_id: str
    course_id: str
    concept_id: str
    title: str
    heading: str
    content_type: str
    text: str


def classify_content_type(heading: str, fallback: str = "explanation") -> str:
    heading_lower = heading.lower()
    for keys, ctype in _HEADING_TYPES:
        if any(k in heading or k in heading_lower for k in keys):
            return ctype
    return fallback


def _split_sections(markdown: str) -> list[tuple[str, str]]:
    """按 `## ` 分节，返回 (标题, 正文)。文件开头（标题前）若有无标题正文也算一节。"""
    sections: list[tuple[str, str]] = []
    current_heading = "概述"
    buffer: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if any(b.strip() for b in buffer):
                sections.append((current_heading, "\n".join(buffer).strip()))
            current_heading = line[3:].strip()
            buffer = []
        elif line.startswith("# "):
            continue  # 文件级 H1 标题不入正文（避免混进节文本）
        else:
            buffer.append(line)
    if any(b.strip() for b in buffer):
        sections.append((current_heading, "\n".join(buffer).strip()))
    return sections


def _bigrams(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", "", text)
    if len(cleaned) < 2:
        return [cleaned] if cleaned else []
    return [cleaned[i : i + 2] for i in range(len(cleaned) - 1)]


def keyword_score(text: str, query: str) -> float:
    """查询 bigram 在文本中的覆盖率（0~1，确定性）。"""
    qgrams = set(_bigrams(query))
    if not qgrams:
        return 0.0
    text_set = set(_bigrams(text))
    hit = sum(1 for g in qgrams if g in text_set)
    return round(hit / len(qgrams), 4)


def _hash_vector(text: str) -> list[float]:
    vec = [0.0] * VECTOR_DIM
    for gram in _bigrams(text):
        digest = hashlib.md5(gram.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "little") % VECTOR_DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = sum(v * v for v in vec) ** 0.5
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return round(sum(x * y for x, y in zip(a, b)), 4)


class RagIndex:
    """课程包资源索引（进程内构建，按 index_version 缓存）。"""

    def __init__(self) -> None:
        data = get_course_data()
        self.course_id = data.course_id
        segments: list[RagSegment] = []
        corpus: list[str] = []
        for resource in data.resources:
            rid = resource["id"]
            content = data.read_resource(rid)
            corpus.append(content)
            owner = next((c for c in data.concepts if rid in c["resource_ids"]), None)
            concept_id = owner["id"] if owner else data.course_id
            for i, (heading, text) in enumerate(_split_sections(content), start=1):
                if not text:
                    continue
                segments.append(
                    RagSegment(
                        source_id=f"{rid}-seg{i:02d}",
                        resource_id=rid,
                        course_id=data.course_id,
                        concept_id=concept_id,
                        title=resource["title"],
                        heading=heading,
                        content_type=classify_content_type(heading),
                        text=f"{heading}：{' '.join(text.split())}",
                    )
                )
        self.segments = segments
        self._version = hashlib.sha256(
            (_course_fingerprint(data) + "".join(corpus)).encode("utf-8")
        ).hexdigest()[:16]
        self._vectors = [_hash_vector(f"{s.title} {s.heading} {s.text}") for s in segments]

    @property
    def index_version(self) -> str:
        return self._version

    def by_source(self, source_id: str, course_id: str) -> RagSegment | None:
        """来源查询；跨课程资源一律不可见（404 语义）。"""
        for s in self.segments:
            if s.source_id == source_id and s.course_id == course_id:
                return s
        return None

    def keyword_search(self, query: str, top_k: int = 8) -> list[tuple[RagSegment, float]]:
        scored = [(s, keyword_score(f"{s.heading} {s.text}", query)) for s in self.segments]
        scored = [(s, sc) for s, sc in scored if sc > 0]
        scored.sort(key=lambda item: (-item[1], item[0].source_id))
        return scored[:top_k]

    def vector_search(self, query: str, top_k: int = 8) -> list[tuple[RagSegment, float]]:
        qvec = _hash_vector(query)
        scored = [(s, cosine(qvec, v)) for s, v in zip(self.segments, self._vectors)]
        scored = [(s, sc) for s, sc in scored if sc > 0]
        scored.sort(key=lambda item: (-item[1], item[0].source_id))
        return scored[:top_k]

    def fixed_fallback(self, concept_id: str | None) -> list[tuple[RagSegment, float]]:
        """课程包固定资源回退：该概念（或缺省时首个概念）主资源的首节。"""
        matched = [s for s in self.segments if concept_id is None or s.concept_id == concept_id]
        first = sorted(matched, key=lambda s: s.source_id)[:1]
        return [(s, 1.0) for s in first]


def _course_fingerprint(data) -> str:  # noqa: ANN001（CourseData，循环导入 avoidance）
    import json as _json

    return _json.dumps(
        {
            "course_id": data.course_id,
            "concepts": data.concepts,
            "resources": data.resources,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


_INDEX: RagIndex | None = None


def get_rag_index() -> RagIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = RagIndex()
    return _INDEX
