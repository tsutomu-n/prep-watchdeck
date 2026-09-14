#!/usr/bin/env python3
"""資料と人工数値例だけを検査する。製品実装や上流コードの試験ではない。"""
from __future__ import annotations

import json
import math
import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def clamp(value: Decimal) -> Decimal:
    return min(Decimal(1), max(Decimal(0), value))


def score(case: dict) -> Decimal | None:
    profile = case['profile']
    if profile == 'momentum-1h-up':
        return Decimal(100) * clamp(case['r60'] / Decimal('0.05'))
    if profile == 'momentum-1h-down':
        return Decimal(100) * clamp(-case['r60'] / Decimal('0.05'))
    require(profile == 'attention-15m', f'不明profile: {profile}')
    if case['volume_ratio'] is None or case['r15'] is None:
        return None
    return (
        Decimal(50) * clamp(abs(case['r15']) / Decimal('0.02'))
        + Decimal(50) * clamp((case['volume_ratio'] - 1) / 2)
    )


def wilson(k: int, n: int) -> tuple[float, float, float]:
    require(type(k) is int and type(n) is int and 0 <= k <= n and n > 0,
            '不正な二項件数')
    z = 1.959963984540054
    p = k / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return p, max(0.0, center - half), min(1.0, center + half)


def main() -> dict:
    docs = sorted(ROOT.glob('*.md')) + [ROOT.parent / 'README.md']
    require(len(docs) == 16, f'Markdownファイル数が不一致: {len(docs)}')
    links = 0
    for path in docs:
        text = path.read_text(encoding='utf-8')
        require(text.startswith('# '), f'H1欠落: {path.name}')
        header = '\n'.join(text.splitlines()[:15])
        metadata = dict(re.findall(r'^- (作成|更新|検証|状態): `([^`]+)`$', header, re.M))
        for field in ('作成', '更新'):
            value = metadata.get(field, '')
            require(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00', value)
                    is not None, f'{path.name}: {field}形式')
            datetime.fromisoformat(value)
        require(metadata.get('状態') in {'参考', '実装計画', '検証記録', '設計判断', '現行'},
                f'{path.name}: 状態')
        require(metadata['更新'] >= metadata['作成'], f'{path.name}: 日時逆転')
        require('filecite' not in text and 'cite' not in text,
                f'{path.name}: GitHubで表示できない引用トークン')
        for href in re.findall(r'(?<!!)\[[^\]]+\]\(([^\s)]+)\)', text):
            parsed = urlsplit(href)
            if parsed.scheme or not parsed.path:
                continue
            target = (path.parent / unquote(parsed.path)).resolve()
            require(target.is_relative_to(ROOT.parent), f'参照pack外への相対リンク: {href}')
            require(target.exists(), f'リンク欠落 {path.name}: {href}')
            links += 1
        require(all(line.rstrip() == line for line in text.splitlines()),
                f'{path.name}: 行末空白')

    lock = json.loads((ROOT / 'sources.lock.json').read_text())
    def check_hashes(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {'commit', 'base_commit', 'blob', 'blob_sha', 'tree', 'base_tree'} and isinstance(item, str):
                    require(re.fullmatch('[0-9a-f]{40}', item) is not None, f'不正hash: {key}')
                check_hashes(item)
        elif isinstance(value, list):
            for item in value:
                check_hashes(item)
    check_hashes(lock)
    for path, sha, read_range in lock['watchdeck_files']:
        require(bool(path) and bool(read_range) and re.fullmatch('[0-9a-f]{40}', sha) is not None,
                'Watchdeck参照lock不正')
    cases = json.loads((ROOT / 'fixtures/acceptance-cases.json').read_text(), parse_float=Decimal)
    require(cases['kind'] == 'synthetic_specification_vectors_not_runtime_test_results',
            'fixtureの出自が不明')
    matrix = (ROOT / '11-TEST-MATRIX.md').read_text()
    ids = re.findall(r'^\| ([RSHEUO]\d{2}) \|', matrix, re.M)
    require(len(ids) == len(set(ids)) == 34, '受入IDの重複または不足')
    require(ids == cases['required_test_ids'], '受入IDとfixtureの順序/集合が不一致')
    for case in cases['score_cases']:
        require(score(case) == case['expected_score'], f"score例: {case['id']}")
    intervals = []
    for case in cases['wilson_cases']:
        actual = wilson(case['k'], case['n'])
        expected = [float(case[key]) for key in ('estimate', 'lo', 'hi')]
        require(all(math.isclose(a, b, rel_tol=0, abs_tol=1e-12)
                    for a, b in zip(actual, expected)), 'Wilson例不一致')
        intervals.append(actual)
    require(intervals[0][1] <= intervals[1][2] and intervals[1][1] <= intervals[0][2],
            '区間重複の反例不一致')
    for case in cases['guard_cases']:
        require((case['n'] >= 10) == case['estimate_allowed'], '表示guard不一致')
        require((case['n'] < 30) == case['low_sample'], '警告guard不一致')
    example = cases['counterexamples']['renormalization']
    pairs = list(zip(example['weights'], example['values']))
    total = sum(w * v for w, v in pairs) * 100 / sum(w for w, _ in pairs)
    reduced = [pair for i, pair in enumerate(pairs) if i != example['drop_index']]
    missing = sum(w * v for w, v in reduced) * 100 / sum(w for w, _ in reduced)
    require(total == example['complete_score'] and missing == example['missing_score'],
            '重み再正規化の反例不一致')
    return {
        'status': 'PASS',
        'scope': 'documentation_and_independent_synthetic_examples_only',
        'markdown_files': len(docs),
        'local_links_checked': links,
        'required_implementation_test_ids': len(ids),
        'score_examples': len(cases['score_cases']),
        'wilson_examples': len(cases['wilson_cases']),
        'guard_examples': len(cases['guard_cases']),
        'upstream_code_executed': False,
        'watchdeck_runtime_tests_executed': False,
    }


if __name__ == '__main__':
    try:
        print(json.dumps(main(), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'FAIL: {error}', file=sys.stderr)
        sys.exit(1)
